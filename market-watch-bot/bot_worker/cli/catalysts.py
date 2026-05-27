from __future__ import annotations

from typing import Annotated

import typer

from bot_worker.cli.apps import catalyst_app
from bot_worker.cli.common import _echo_json, _run, _with_session
from bot_worker.services import (
    run_missed_catalyst_review,
)


@catalyst_app.command("review")
def catalyst_review(window: Annotated[str, typer.Option("--window")] = "1d") -> None:
    """Run automated review of missed catalysts over a specified window."""
    async def action(session):
        count = await run_missed_catalyst_review(session, window=window)
        _echo_json({"created": count, "window": window})

    _run(_with_session(action))
