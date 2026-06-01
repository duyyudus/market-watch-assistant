from __future__ import annotations

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


def setup_logging(settings: Settings) -> None:
    """Configure logging for the application."""
    logger = logging.getLogger("bot_worker")
    logger.setLevel(settings.logging.level.upper())

    # Clear existing handlers to prevent duplicate output if re-initialized
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    redaction_filter = SecretRedactionFilter([settings.telegram_bot_token or ""])
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    json_formatter = JsonLogFormatter(redacted_secrets=[settings.telegram_bot_token or ""])

    if settings.logging.console:
        # Standard StreamHandler prints to stderr by default
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(console_formatter)
        console_handler.addFilter(redaction_filter)
        logger.addHandler(console_handler)

    if settings.logging.log_file:
        log_path = Path(settings.logging.log_file)
        # Ensure log directory exists (e.g. .log/ folder)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = LineRotatingFileHandler(
            log_path,
            encoding="utf-8",
            max_lines=settings.logging.max_lines,
            backupCount=settings.logging.backup_count,
        )
        file_handler.setFormatter(json_formatter)
        file_handler.addFilter(redaction_filter)
        logger.addHandler(file_handler)

