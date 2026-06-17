import json
import logging
from pathlib import Path

from bot_worker.config import load_settings
from bot_worker.logging import (
    JsonLogFormatter,
    LineRotatingFileHandler,
    log_component,
    setup_logging,
)


def _settings_with_log_dir(tmp_path: Path, **logging_overrides):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=sqlite+aiosqlite:///:memory:\n", encoding="utf-8")
    settings = load_settings(env_file=env_file, settings_file=tmp_path / "missing.yml")
    settings.logging.log_dir = str(tmp_path / "logs")
    settings.logging.console = False
    for key, value in logging_overrides.items():
        setattr(settings.logging, key, value)
    return settings


def _teardown_logger() -> None:
    logger = logging.getLogger("bot_worker")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_logging_config_defaults(tmp_path: Path) -> None:
    # Verify defaults are merged correctly
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=sqlite+aiosqlite:///:memory:\n", encoding="utf-8")
    settings = load_settings(env_file=env_file, settings_file=tmp_path / "missing.yml")
    assert settings.logging.log_dir == ".log"
    assert settings.logging.max_lines == 10000
    assert settings.logging.backup_count == 5


def test_logging_config_custom(tmp_path: Path) -> None:
    # Verify custom settings are loaded correctly
    settings_file = tmp_path / "settings.yml"
    settings_file.write_text(
        """
logging:
  level: DEBUG
  log_dir: .log/custom
  console: false
  max_lines: 50
  backup_count: 2
""",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=sqlite+aiosqlite:///:memory:\n", encoding="utf-8")
    settings = load_settings(env_file=env_file, settings_file=settings_file)
    assert settings.logging.level == "DEBUG"
    assert settings.logging.log_dir == ".log/custom"
    assert settings.logging.console is False
    assert settings.logging.max_lines == 50
    assert settings.logging.backup_count == 2


def test_line_rotating_file_handler_rotates_on_limit(tmp_path: Path) -> None:
    log_file = tmp_path / "test.log"
    
    # Initialize with a small max_lines limit of 3
    handler = LineRotatingFileHandler(log_file, mode="w", max_lines=3, backupCount=2)
    handler.setFormatter(logging.Formatter("%(message)s"))
    
    logger = logging.getLogger("test_line_rotation")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    try:
        # Write 3 log messages
        # Message 1
        logger.info("line 1")
        # Message 2
        logger.info("line 2")
        # Message 3
        logger.info("line 3")
        
        # Verify 3 lines are in the active log file
        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert lines == ["line 1", "line 2", "line 3"]
        assert not Path(f"{log_file}.1").exists()
        
        # Write 4th log message, which triggers rollover in emit() BEFORE writing line 4
        logger.info("line 4")
        
        # Now, test.log should have been rotated to test.log.1,
        # and test.log should contain only the new message "line 4"
        assert log_file.exists()
        assert Path(f"{log_file}.1").exists()
        
        active_lines = log_file.read_text(encoding="utf-8").splitlines()
        assert active_lines == ["line 4"]
        
        rotated_lines = Path(f"{log_file}.1").read_text(encoding="utf-8").splitlines()
        assert rotated_lines == ["line 1", "line 2", "line 3"]
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_line_rotating_file_handler_lazy_counting(tmp_path: Path) -> None:
    log_file = tmp_path / "lazy_test.log"
    
    # Write existing 2 lines to the log file manually
    log_file.write_text("existing line 1\nexisting line 2\n", encoding="utf-8")
    
    # Open in append mode ("a") with max_lines=3
    handler = LineRotatingFileHandler(log_file, mode="a", max_lines=3, backupCount=2)
    handler.setFormatter(logging.Formatter("%(message)s"))
    
    logger = logging.getLogger("test_lazy_rotation")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    try:
        # At this stage, handler hasn't processed any records.
        # Once we log one more line, the count will be 3 lines total.
        logger.info("new line 3")
        
        # Verify it hasn't rotated yet, since limit is 3 and we are at exactly 3 lines.
        assert log_file.exists()
        assert not Path(f"{log_file}.1").exists()
        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert lines == ["existing line 1", "existing line 2", "new line 3"]
        
        # Logging a 4th line triggers rollover
        logger.info("new line 4")
        
        assert log_file.exists()
        assert Path(f"{log_file}.1").exists()
        
        active_lines = log_file.read_text(encoding="utf-8").splitlines()
        assert active_lines == ["new line 4"]
        
        rotated_lines = Path(f"{log_file}.1").read_text(encoding="utf-8").splitlines()
        assert rotated_lines == ["existing line 1", "existing line 2", "new line 3"]
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_json_log_formatter_outputs_structured_fields_and_redacts_token() -> None:
    formatter = JsonLogFormatter(redacted_secrets=["secret-token"])
    record = logging.LogRecord(
        name="bot_worker.pipeline",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="LLM call used secret-token",
        args=(),
        exc_info=None,
    )
    record.stage_name = "extract_entities"
    record.duration_ms = 42
    record.items_processed = 7

    payload = json.loads(formatter.format(record))

    assert payload["timestamp"]
    assert payload["level"] == "INFO"
    assert payload["logger"] == "bot_worker.pipeline"
    assert payload["message"] == "LLM call used [REDACTED_TELEGRAM_TOKEN]"
    assert payload["stage_name"] == "extract_entities"
    assert payload["duration_ms"] == 42
    assert payload["items_processed"] == 7


def test_worker_setup_routes_tasks_to_separate_files(tmp_path: Path) -> None:
    settings = _settings_with_log_dir(tmp_path)
    log_dir = Path(settings.logging.log_dir)
    setup_logging(settings, component="worker")
    logger = logging.getLogger("bot_worker")
    try:
        token = log_component.set("pipeline")
        logger.info("pipeline tick ran")
        log_component.reset(token)

        token = log_component.set("command")
        logger.info("command drained")
        log_component.reset(token)

        # No component set -> worker lifecycle file.
        logger.info("worker starting up")

        pipeline_lines = (log_dir / "worker-pipeline.log").read_text("utf-8").splitlines()
        command_lines = (log_dir / "worker-command.log").read_text("utf-8").splitlines()
        worker_lines = (log_dir / "worker.log").read_text("utf-8").splitlines()

        assert [json.loads(line)["message"] for line in pipeline_lines] == [
            "pipeline tick ran"
        ]
        assert [json.loads(line)["message"] for line in command_lines] == [
            "command drained"
        ]
        assert [json.loads(line)["message"] for line in worker_lines] == [
            "worker starting up"
        ]
        # Records are stamped with their component for in-file attribution.
        assert json.loads(pipeline_lines[0])["component"] == "pipeline"
        assert json.loads(worker_lines[0])["component"] == "worker"
    finally:
        _teardown_logger()


def test_component_setup_writes_single_named_file(tmp_path: Path) -> None:
    settings = _settings_with_log_dir(tmp_path)
    log_dir = Path(settings.logging.log_dir)
    setup_logging(settings, component="api")
    logger = logging.getLogger("bot_worker")
    try:
        logger.info("request handled")
        api_lines = (log_dir / "api.log").read_text("utf-8").splitlines()
        assert [json.loads(line)["message"] for line in api_lines] == ["request handled"]
        assert json.loads(api_lines[0])["component"] == "api"
        # Worker task files are not created for a non-worker component.
        assert not (log_dir / "worker-pipeline.log").exists()
    finally:
        _teardown_logger()


def test_line_rotating_file_handler_counts_lines_from_single_formatted_message(
    tmp_path: Path,
) -> None:
    class CountingFormatter(logging.Formatter):
        def __init__(self) -> None:
            super().__init__("%(message)s")
            self.calls = 0

        def format(self, record: logging.LogRecord) -> str:
            self.calls += 1
            return super().format(record)

    log_file = tmp_path / "single_format.log"
    formatter = CountingFormatter()
    handler = LineRotatingFileHandler(log_file, mode="w", max_lines=5, backupCount=1)
    handler.setFormatter(formatter)
    logger = logging.getLogger("test_single_format_rotation")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        logger.info("line one")
        assert formatter.calls == 1
        assert log_file.read_text(encoding="utf-8").splitlines() == ["line one"]
    finally:
        logger.removeHandler(handler)
        handler.close()
