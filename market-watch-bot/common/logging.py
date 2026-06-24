from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.config import Settings

# Tracks which logical component a log record belongs to. asyncio copies the
# active context per task, so setting this at the top of a worker task routes
# every record emitted downstream within that task — even from shared service
# code that logs to the flat ``bot_worker`` logger — to the right file.
log_component: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_component", default=None
)

# One log file per long-lived process / CLI invocation.
COMPONENT_LOG_FILES = {
    "api": "api.log",
    "cli": "cli.log",
    "worker": "worker.log",
}
# Within the single worker process, each concurrent asyncio task gets its own
# file, keyed by the ``log_component`` contextvar value it sets.
WORKER_TASK_LOG_FILES = {
    "pipeline": "worker-pipeline.log",
    "command": "worker-command.log",
    "telegram": "worker-telegram.log",
}
# uvicorn's own loggers are routed into the API file so request/error logs land
# alongside application logs in the same process.
EXTRA_API_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, redacted_secrets: list[str] | None = None) -> None:
        super().__init__()
        self.redacted_secrets = [secret for secret in redacted_secrets or [] if secret]

    def format(self, record: logging.LogRecord) -> str:
        message = self._redact(record.getMessage())
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        for key, value in record.__dict__.items():
            if key in STANDARD_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = self._safe_value(value)
        if record.exc_info:
            payload["exception"] = self._redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _redact(self, value: str) -> str:
        for secret in self.redacted_secrets:
            value = value.replace(secret, "[REDACTED_TELEGRAM_TOKEN]")
        return value

    def _safe_value(self, value: object) -> object:
        if isinstance(value, str):
            return self._redact(value)
        if isinstance(value, dict):
            return {str(key): self._safe_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._safe_value(item) for item in value]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return self._redact(str(value))


class LineRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A logging handler that rotates log files based on a maximum line count."""

    def __init__(
        self,
        filename: str | Path,
        mode: str = "a",
        encoding: str | None = None,
        delay: bool = False,
        max_lines: int = 10000,
        backupCount: int = 5,
    ) -> None:
        super().__init__(
            filename,
            mode=mode,
            maxBytes=0,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
        )
        self.max_lines = max_lines
        
        # If we open in write mode, the file will be truncated, so start at 0.
        # Otherwise, lazily count lines on first emit or rollover check.
        if "w" in self.mode:
            self._line_count = 0
        else:
            self._line_count = -1

    def _count_lines(self, filename: str) -> int:
        try:
            if not os.path.exists(filename):
                return 0
            with open(filename, encoding=self.encoding or "utf-8", errors="replace") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if self.stream is None:
            self.stream = self._open()
        if self._line_count == -1:
            self._line_count = self._count_lines(self.baseFilename)
        return self._line_count >= self.max_lines

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._line_count == -1:
                self._line_count = self._count_lines(self.baseFilename)
            if self.shouldRollover(record):
                self.doRollover()
            msg = self.format(record)
            stream = self.stream
            if stream is None:
                stream = self._open()
                self.stream = stream
            stream.write(msg + self.terminator)
            self.flush()
            self._line_count += msg.count("\n") + 1
        except Exception:
            self.handleError(record)

    def doRollover(self) -> None:
        super().doRollover()
        self._line_count = 0


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED_TELEGRAM_TOKEN]")
        record.msg = message
        record.args = ()
        return True


class ComponentStampFilter(logging.Filter):
    """Stamp each record with its component (from the contextvar or a default).

    The value surfaces as a ``component`` field in the JSON file output and in
    the ``[component]`` segment of the console line, so records remain
    attributable even when several components share a file.
    """

    def __init__(self, default: str) -> None:
        super().__init__()
        self.default = default

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = log_component.get() or self.default
        return True


class ComponentRouteFilter(logging.Filter):
    """Admit a record onto a handler only if its active component matches.

    Routing reads the ``log_component`` contextvar directly (not the stamped
    attribute) so it works regardless of filter ordering on the handler.
    """

    def __init__(
        self, *, accept: set[str] | None = None, accept_untagged: bool = False
    ) -> None:
        super().__init__()
        self.accept = set(accept or ())
        self.accept_untagged = accept_untagged

    def filter(self, record: logging.LogRecord) -> bool:
        current = log_component.get()
        if current is None:
            return self.accept_untagged
        return current in self.accept


def setup_logging(settings: Settings, component: str = "cli") -> None:
    """Configure logging for one process (``api``/``worker``/``cli``).

    Each process writes to its own file under ``settings.logging.log_dir`` so
    separate OS processes never contend on a single rotating file. The
    ``worker`` process additionally fans its two concurrent asyncio tasks into
    ``worker-pipeline.log`` and ``worker-command.log`` (with lifecycle/untagged
    records going to ``worker.log``) via the ``log_component`` contextvar.
    """
    logger = logging.getLogger("bot_worker")
    logger.setLevel(settings.logging.level.upper())

    # Clear handlers (on bot_worker and any extra loggers we manage) so repeated
    # initialization — e.g. the CLI callback then ``worker start`` — doesn't
    # duplicate output.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    for name in EXTRA_API_LOGGERS:
        extra_logger = logging.getLogger(name)
        for handler in list(extra_logger.handlers):
            if getattr(handler, "_market_watch_managed", False):
                extra_logger.removeHandler(handler)

    secrets = [settings.telegram_bot_token or ""]
    redaction_filter = SecretRedactionFilter(secrets)
    stamp_filter = ComponentStampFilter(default=component)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(component)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    json_formatter = JsonLogFormatter(redacted_secrets=secrets)

    if settings.logging.console:
        # Standard StreamHandler prints to stderr by default
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(console_formatter)
        console_handler.addFilter(redaction_filter)
        console_handler.addFilter(stamp_filter)
        logger.addHandler(console_handler)

    if not settings.logging.log_dir:
        return

    log_dir = Path(settings.logging.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    def _file_handler(
        filename: str, route_filter: ComponentRouteFilter | None = None
    ) -> LineRotatingFileHandler:
        handler = LineRotatingFileHandler(
            log_dir / filename,
            encoding="utf-8",
            max_lines=settings.logging.max_lines,
            backupCount=settings.logging.backup_count,
        )
        handler.setFormatter(json_formatter)
        handler.addFilter(redaction_filter)
        handler.addFilter(stamp_filter)
        if route_filter is not None:
            handler.addFilter(route_filter)
        handler._market_watch_managed = True  # type: ignore[attr-defined]
        return handler

    if component == "worker":
        logger.addHandler(
            _file_handler(
                WORKER_TASK_LOG_FILES["pipeline"],
                ComponentRouteFilter(accept={"pipeline"}),
            )
        )
        logger.addHandler(
            _file_handler(
                WORKER_TASK_LOG_FILES["command"],
                ComponentRouteFilter(accept={"command"}),
            )
        )
        logger.addHandler(
            _file_handler(
                COMPONENT_LOG_FILES["worker"],
                ComponentRouteFilter(accept_untagged=True),
            )
        )
        return

    file_handler = _file_handler(COMPONENT_LOG_FILES.get(component, f"{component}.log"))
    logger.addHandler(file_handler)
    if component == "api":
        # Route uvicorn's own loggers to the same API file (additive — uvicorn
        # keeps its console handlers).
        for name in EXTRA_API_LOGGERS:
            extra_logger = logging.getLogger(name)
            extra_logger.addHandler(file_handler)
