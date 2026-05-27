from __future__ import annotations

from bot_worker.cli.apps import retention_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.retention import RetentionPolicy
from bot_worker.services import (
    retention_preview,
    run_retention,
)


@retention_app.command("show")
def retention_show() -> None:
    """Display the active database retention policy configuration."""
    settings = _settings()
    _echo_json(settings.retention.model_dump())
@retention_app.command("preview")
def retention_preview_command() -> None:
    """Preview which database records would be cleaned up under the retention policy."""
    settings = _settings()
    policy = RetentionPolicy(**settings.retention.model_dump())

    async def action(session):
        _echo_json(await retention_preview(session, policy))

    _run(_with_session(action))
@retention_app.command("run")
def retention_run() -> None:
    """Execute retention cleanup to purge expired news, event, and run records."""
    settings = _settings()
    policy = RetentionPolicy(**settings.retention.model_dump())

    async def action(session):
        _echo_json(await run_retention(session, policy))

    _run(_with_session(action))
