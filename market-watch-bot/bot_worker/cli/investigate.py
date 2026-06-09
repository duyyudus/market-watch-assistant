from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from bot_worker.cli.apps import investigate_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import AgentInvestigation, MarketMove
from bot_worker.investigation import InvestigationConfig
from bot_worker.services.investigation import (
    list_pending_investigations,
    run_asset_investigation,
    run_event_investigation,
    run_move_investigation,
    run_pending_investigations,
)
from common.llm import LLMConfig


def _enabled_investigation_config() -> InvestigationConfig:
    config = InvestigationConfig.from_settings(_settings())
    if not config.enabled:
        config = replace(config, enabled=True)
    return config


def _enabled_llm_config() -> LLMConfig:
    config = LLMConfig.from_settings(_settings())
    if not config.enabled:
        config = replace(config, enabled=True)
    return config


def _run_payload(run: AgentInvestigation) -> dict[str, object]:
    return {
        "investigation_id": run.id,
        "target_type": run.target_type,
        "target_id": run.target_id,
        "trigger_reason": run.trigger_reason,
        "status": run.status,
        "result": run.result,
        "error": run.error_message,
    }


def _since_cutoff(value: str) -> datetime:
    now = datetime.now(UTC)
    stripped = value.strip().lower()
    if stripped.endswith("d") and stripped[:-1].isdigit():
        return now - timedelta(days=int(stripped[:-1]))
    if stripped.endswith("h") and stripped[:-1].isdigit():
        return now - timedelta(hours=int(stripped[:-1]))
    return datetime.fromisoformat(value).astimezone(UTC)


@investigate_app.command("event")
def investigate_event(event_id: str) -> None:
    """Run a constrained investigation for an event cluster."""
    config = _enabled_investigation_config()
    llm_config = _enabled_llm_config()

    async def action(session):
        run = await run_event_investigation(
            session,
            event_id=event_id,
            config=config,
            llm_config=llm_config,
        )
        _echo_json(_run_payload(run))

    _run(_with_session(action))


@investigate_app.command("move")
def investigate_move(
    symbol: Annotated[str, typer.Option("--symbol")],
    window: Annotated[str, typer.Option("--window")] = "1d",
) -> None:
    """Run a constrained investigation for the latest stored market move."""
    config = _enabled_investigation_config()
    llm_config = _enabled_llm_config()

    async def action(session):
        from sqlalchemy import select

        move = await session.scalar(
            select(MarketMove)
            .where(MarketMove.asset_symbol == symbol.upper())
            .where(MarketMove.window == window)
            .order_by(MarketMove.timestamp.desc())
            .limit(1)
        )
        if move is None:
            typer.echo("Market move not found")
            raise typer.Exit(1)
        run = await run_move_investigation(
            session,
            move_id=move.id,
            config=config,
            llm_config=llm_config,
        )
        _echo_json(_run_payload(run))

    _run(_with_session(action))


@investigate_app.command("asset")
def investigate_asset(
    symbol: Annotated[str, typer.Option("--symbol")],
    since: Annotated[str, typer.Option("--since")] = "24h",
) -> None:
    """Run a constrained investigation for an asset symbol."""
    config = _enabled_investigation_config()
    llm_config = _enabled_llm_config()

    async def action(session):
        run = await run_asset_investigation(
            session,
            symbol=symbol,
            since=_since_cutoff(since),
            config=config,
            llm_config=llm_config,
        )
        _echo_json(_run_payload(run))

    _run(_with_session(action))


@investigate_app.command("pending")
def investigate_pending(limit: Annotated[int, typer.Option("--limit")] = 20) -> None:
    """Show pending agent investigations."""

    async def action(session):
        rows = await list_pending_investigations(session, limit=limit)
        _echo_json(
            [
                {
                    "id": row.id,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "trigger_reason": row.trigger_reason,
                    "status": row.status,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        )

    _run(_with_session(action))


@investigate_app.command("run-pending")
def investigate_run_pending(limit: Annotated[int, typer.Option("--limit")] = 20) -> None:
    """Run pending agent investigations."""
    config = _enabled_investigation_config()
    llm_config = _enabled_llm_config()

    async def action(session):
        result = await run_pending_investigations(
            session,
            config=config,
            llm_config=llm_config,
            limit=limit,
        )
        _echo_json(result)

    _run(_with_session(action))


@investigate_app.command("show")
def investigate_show(investigation_id: str) -> None:
    """Show a stored agent investigation."""

    async def action(session):
        run = await session.get(AgentInvestigation, investigation_id)
        if run is None:
            typer.echo("Investigation not found")
            raise typer.Exit(1)
        _echo_json(
            {
                "id": run.id,
                "target_type": run.target_type,
                "target_id": run.target_id,
                "trigger_reason": run.trigger_reason,
                "status": run.status,
                "input_snapshot": run.input_snapshot,
                "evidence": run.evidence,
                "result": run.result,
                "error": run.error_message,
                "usage": run.usage,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            }
        )

    _run(_with_session(action))
