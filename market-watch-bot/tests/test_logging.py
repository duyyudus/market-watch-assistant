import logging
from pathlib import Path

from bot_worker.config import load_settings
from bot_worker.logging import LineRotatingFileHandler


def test_logging_config_defaults(tmp_path: Path) -> None:
    # Verify defaults are merged correctly
    settings = load_settings(
        env_file=tmp_path / "missing.env", settings_file=tmp_path / "missing.yml"
    )
    assert settings.logging.max_lines == 10000
    assert settings.logging.backup_count == 5


def test_logging_config_custom(tmp_path: Path) -> None:
    # Verify custom settings are loaded correctly
    settings_file = tmp_path / "settings.yml"
    settings_file.write_text(
        """
logging:
  level: DEBUG
  log_file: .log/custom.log
  console: false
  max_lines: 50
  backup_count: 2
""",
        encoding="utf-8",
    )
    settings = load_settings(
        env_file=tmp_path / "missing.env", settings_file=settings_file
    )
    assert settings.logging.level == "DEBUG"
    assert settings.logging.log_file == ".log/custom.log"
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
