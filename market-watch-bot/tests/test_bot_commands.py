from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from bot_worker.db.models import BotCommand, EventCluster
from bot_worker.services.bot_commands import (
    ALLOWED_COMMAND_TYPES,
    claim_pending_bot_command,
    complete_bot_command,
    execute_bot_command,
    fail_bot_command,
    process_pending_bot_commands,
    score_event_cluster,
)


class ScalarResult:
    def __init__(self, rows: list[BotCommand]) -> None:
        self.rows = rows

    def first(self) -> BotCommand | None:
        return self.rows[0] if self.rows else None


class CommandSession:
    def __init__(self, commands: list[BotCommand]) -> None:
        self.commands = commands

    async def scalars(self, _stmt):
        pending = [command for command in self.commands if command.status == "pending"]
        pending.sort(key=lambda command: command.created_at or datetime.now(UTC))
        return ScalarResult(pending)

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_claim_pending_bot_command_marks_oldest_command_running() -> None:
    command = BotCommand(
        id="cmd_1",
        command_type="pipeline.run",
        status="pending",
        payload={"dry_run": True},
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    session = CommandSession([command])

    claimed = await claim_pending_bot_command(session)

    assert claimed is command
    assert claimed.status == "running"
    assert claimed.started_at is not None
    assert "pipeline.run" in ALLOWED_COMMAND_TYPES


def test_complete_and_fail_bot_command_record_terminal_state() -> None:
    command = BotCommand(
        id="cmd_1",
        command_type="pipeline.run",
        status="running",
        payload={"dry_run": True},
    )

    complete_bot_command(command, {"status": "dry_run"})
    assert command.status == "succeeded"
    assert command.result == {"status": "dry_run"}
    assert command.completed_at is not None

    failed = BotCommand(
        id="cmd_2",
        command_type="pipeline.run",
        status="running",
        payload={"dry_run": False},
    )
    fail_bot_command(failed, RuntimeError("database unavailable"))
    assert failed.status == "failed"
    assert failed.error_message == "database unavailable"
    assert failed.completed_at is not None


@pytest.mark.asyncio
async def test_score_event_cluster_uses_watchlist_relevance_for_affected_entities(
    monkeypatch,
) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after Gulf shipping disruption",
        status="reported",
        affected_entities=["Brent"],
        source_count=2,
        top_source_score=90,
    )

    async def fake_market_score(_session, _event):
        return 0

    monkeypatch.setattr(
        "bot_worker.services.bot_commands.market_move_score_for_cluster",
        fake_market_score,
    )

    breakdown = await score_event_cluster(SimpleNamespace(), event)

    assert breakdown.relevance_score == 95


@pytest.mark.asyncio
async def test_score_event_cluster_keeps_low_relevance_without_affected_entities(
    monkeypatch,
) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Generic market update",
        status="reported",
        affected_entities=[],
        source_count=2,
        top_source_score=90,
    )

    async def fake_market_score(_session, _event):
        return 0

    monkeypatch.setattr(
        "bot_worker.services.bot_commands.market_move_score_for_cluster",
        fake_market_score,
    )

    breakdown = await score_event_cluster(SimpleNamespace(), event)

    assert breakdown.relevance_score == 35


@pytest.mark.asyncio
async def test_event_rescore_command_uses_shared_scoring_helper(monkeypatch) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after Gulf shipping disruption",
        status="reported",
        affected_entities=["Brent"],
        source_count=2,
        top_source_score=90,
    )

    class RescoreSession:
        async def get(self, model, key):
            assert model is EventCluster
            assert key == "evt_1"
            return event

    async def fake_market_score(_session, _event):
        return 0

    monkeypatch.setattr(
        "bot_worker.services.bot_commands.market_move_score_for_cluster",
        fake_market_score,
    )

    result = await execute_bot_command(
        RescoreSession(),
        BotCommand(command_type="event.rescore", payload={"event_id": "evt_1"}),
        settings=SimpleNamespace(),
    )

    assert result == {"event_id": "evt_1", "final_score": event.final_score}
    assert event.relevance_score == 95


@pytest.mark.asyncio
async def test_process_pending_bot_commands_drains_multiple_commands(monkeypatch) -> None:
    commands = [
        BotCommand(id="cmd_1", command_type="event.mark", status="pending", payload={}),
        BotCommand(id="cmd_2", command_type="event.mark", status="pending", payload={}),
        BotCommand(id="cmd_3", command_type="event.mark", status="pending", payload={}),
    ]
    session = CommandSession(commands)

    async def fake_execute(_session, command, *, settings):
        return {"command": command.id, "settings": settings.name}

    monkeypatch.setattr("bot_worker.services.bot_commands.execute_bot_command", fake_execute)

    processed = await process_pending_bot_commands(
        session,
        settings=SimpleNamespace(name="test"),
        limit=25,
    )

    assert [command.id for command in processed] == ["cmd_1", "cmd_2", "cmd_3"]
    assert [command.status for command in commands] == ["succeeded", "succeeded", "succeeded"]


@pytest.mark.asyncio
async def test_process_pending_bot_commands_stops_at_limit(monkeypatch) -> None:
    commands = [
        BotCommand(id="cmd_1", command_type="event.mark", status="pending", payload={}),
        BotCommand(id="cmd_2", command_type="event.mark", status="pending", payload={}),
        BotCommand(id="cmd_3", command_type="event.mark", status="pending", payload={}),
    ]
    session = CommandSession(commands)

    async def fake_execute(_session, command, *, settings):
        return {"command": command.id}

    monkeypatch.setattr("bot_worker.services.bot_commands.execute_bot_command", fake_execute)

    processed = await process_pending_bot_commands(
        session,
        settings=SimpleNamespace(),
        limit=2,
    )

    assert [command.id for command in processed] == ["cmd_1", "cmd_2"]
    assert [command.status for command in commands] == ["succeeded", "succeeded", "pending"]


@pytest.mark.asyncio
async def test_execute_bot_command_rejects_unsupported_type() -> None:
    command = BotCommand(command_type="shell.exec", payload={})

    with pytest.raises(ValueError, match="Unsupported bot command"):
        await execute_bot_command(
            SimpleNamespace(),
            command,
            settings=SimpleNamespace(),
        )


@pytest.mark.asyncio
async def test_event_mark_rejects_invalid_status() -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Test event",
        status="reported",
        source_count=1,
        top_source_score=50,
    )

    class MarkSession:
        async def get(self, model, key):
            return event

        async def flush(self):
            pass

    command = BotCommand(
        command_type="event.mark",
        payload={"event_id": "evt_1", "status": "invalid_status"},
    )

    with pytest.raises(ValueError, match="Unsupported event status"):
        await execute_bot_command(
            MarkSession(),
            command,
            settings=SimpleNamespace(),
        )


@pytest.mark.asyncio
async def test_event_mark_applies_valid_status() -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Test event",
        status="reported",
        source_count=1,
        top_source_score=50,
    )

    class MarkSession:
        async def get(self, model, key):
            return event

        async def flush(self):
            pass

    command = BotCommand(
        command_type="event.mark",
        payload={"event_id": "evt_1", "status": "confirmed"},
    )

    result = await execute_bot_command(
        MarkSession(),
        command,
        settings=SimpleNamespace(),
    )

    assert result == {"event_id": "evt_1", "status": "confirmed"}
    assert event.status == "confirmed"

