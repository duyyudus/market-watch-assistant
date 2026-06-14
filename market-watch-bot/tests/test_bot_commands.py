from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import bot_worker.services.bot_commands as bot_commands
from bot_worker.db.models import BotCommand, EventCluster
from bot_worker.services.bot_commands import (
    ALLOWED_COMMAND_TYPES,
    claim_pending_bot_command,
    complete_bot_command,
    execute_bot_command,
    fail_bot_command,
    process_pending_bot_commands,
    reap_stale_running_bot_commands,
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


class RunningCommandSession:
    def __init__(self, commands: list[BotCommand]) -> None:
        self.commands = commands

    async def scalars(self, _stmt):
        return ScalarResult([command for command in self.commands if command.status == "running"])

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


@pytest.mark.asyncio
async def test_reap_stale_running_bot_commands_marks_timed_out_commands_failed() -> None:
    now = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    stale = BotCommand(
        id="cmd_stale",
        command_type="pipeline.run",
        status="running",
        payload={},
        started_at=now - timedelta(minutes=11),
    )
    fresh = BotCommand(
        id="cmd_fresh",
        command_type="pipeline.run",
        status="running",
        payload={},
        started_at=now - timedelta(minutes=2),
    )
    session = RunningCommandSession([stale, fresh])

    reaped = await reap_stale_running_bot_commands(
        session,
        timeout_seconds=600,
        now=now,
    )

    assert reaped == 1
    assert stale.status == "failed"
    assert stale.error_message == "timed out (worker restart?)"
    assert stale.completed_at == now
    assert fresh.status == "running"


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

    assert breakdown.relevance_score == 90


@pytest.mark.asyncio
async def test_score_event_cluster_uses_d_tier_baseline_without_watchlist_tier(
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

    # An untiered / off-watchlist cluster falls back to the D-tier baseline (35),
    # not the demoted 20 (see M6 regression fix in scoring.score_event).
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
    assert event.relevance_score == 90


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


@pytest.mark.asyncio
async def test_event_recluster_passes_enabled_llm_config_when_requested(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_recluster(
        _session,
        *,
        since,
        dry_run,
        limit,
        llm_config=None,
        embedding_config=None,
        progress=None,
        use_vector_signal=False,
    ):
        captured["llm_config"] = llm_config
        return {"status": "dry_run", "new_clusters": 0}

    monkeypatch.setattr(bot_commands, "recluster_recent_event_clusters", fake_recluster)
    monkeypatch.setattr(
        bot_commands.LLMConfig,
        "from_settings",
        classmethod(lambda cls, _settings: cls(enabled=False, api_key="secret")),
    )
    monkeypatch.setattr(
        bot_commands.EmbeddingConfig,
        "from_settings",
        classmethod(lambda cls, _settings: cls(provider="local")),
    )

    command = BotCommand(command_type="event.recluster", payload={"since": "168h", "llm": True})
    result = await execute_bot_command(object(), command, settings=SimpleNamespace())

    config = captured["llm_config"]
    assert config is not None
    # Parity with the CLI --llm flag: a disabled config is coerced to enabled.
    assert config.enabled is True
    assert config.api_key == "secret"
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_event_recluster_defaults_to_no_llm(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_recluster(
        _session,
        *,
        since,
        dry_run,
        limit,
        llm_config=None,
        embedding_config=None,
        progress=None,
        use_vector_signal=False,
    ):
        captured["llm_config"] = llm_config
        captured["embedding_config"] = embedding_config
        captured["use_vector_signal"] = use_vector_signal
        return {"status": "dry_run", "new_clusters": 0}

    monkeypatch.setattr(bot_commands, "recluster_recent_event_clusters", fake_recluster)
    monkeypatch.setattr(
        bot_commands.EmbeddingConfig,
        "from_settings",
        classmethod(lambda cls, _settings: cls(provider="local")),
    )

    command = BotCommand(command_type="event.recluster", payload={"since": "48h"})
    await execute_bot_command(object(), command, settings=SimpleNamespace())

    assert captured["llm_config"] is None
    # No embed flag: vector grouping is off, but the embedding config is still built so
    # recluster re-embeds the clusters it invalidates on apply.
    assert captured["embedding_config"] is not None
    assert captured["use_vector_signal"] is False


@pytest.mark.asyncio
async def test_event_recluster_passes_embedding_config_when_requested(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = bot_commands.EmbeddingConfig(provider="local")

    async def fake_recluster(
        _session,
        *,
        since,
        dry_run,
        limit,
        llm_config=None,
        embedding_config=None,
        progress=None,
        use_vector_signal=False,
    ):
        captured["embedding_config"] = embedding_config
        captured["use_vector_signal"] = use_vector_signal
        return {"status": "dry_run", "new_clusters": 0}

    monkeypatch.setattr(bot_commands, "recluster_recent_event_clusters", fake_recluster)
    monkeypatch.setattr(
        bot_commands.EmbeddingConfig,
        "from_settings",
        classmethod(lambda cls, _settings: sentinel),
    )

    command = BotCommand(command_type="event.recluster", payload={"embed": True})
    await execute_bot_command(object(), command, settings=SimpleNamespace())

    assert captured["embedding_config"] is sentinel
    # The embed flag turns on the vector grouping signal.
    assert captured["use_vector_signal"] is True


@pytest.mark.asyncio
async def test_event_recluster_llm_without_api_key_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        bot_commands.LLMConfig,
        "from_settings",
        classmethod(lambda cls, _settings: cls(enabled=True, api_key=None)),
    )

    command = BotCommand(command_type="event.recluster", payload={"llm": True})
    with pytest.raises(ValueError, match="no LLM API key"):
        await execute_bot_command(object(), command, settings=SimpleNamespace())


@pytest.mark.asyncio
async def test_execute_bot_commands_market_fetch_and_catalyst_review(monkeypatch) -> None:
    class MockSession:
        pass

    fetch_kwargs = {}

    async def fake_fetch_market_moves(*args, **kwargs):
        fetch_kwargs.update(kwargs)
        from bot_worker.market_data import MarketMoveDraft
        return [
            MarketMoveDraft(
                asset_symbol="BTC",
                asset_class="crypto",
                exchange="BINANCE",
                timestamp=datetime.now(UTC),
                window="1d",
                price_change_pct=1.2,
            )
        ]

    async def fake_store_market_moves(*args, **kwargs):
        return 1

    async def fake_run_missed_catalyst_review(*args, **kwargs):
        return 2

    monkeypatch.setattr(
        "bot_worker.services.bot_commands.fetch_market_moves",
        fake_fetch_market_moves,
    )
    monkeypatch.setattr(
        "bot_worker.services.bot_commands.store_market_moves",
        fake_store_market_moves,
    )
    monkeypatch.setattr(
        "bot_worker.services.bot_commands.run_missed_catalyst_review",
        fake_run_missed_catalyst_review,
    )

    settings = SimpleNamespace(
        market_data=SimpleNamespace(
            vn_base_url="http://mock",
            symbol_map={"BTC": "bitcoin"},
            crypto_provider="coingecko",
            crypto_fallback_provider="binance",
        ),
        coingecko_api_key="demo-key",
    )

    # Test market.fetch command
    cmd_fetch = BotCommand(
        command_type="market.fetch",
        payload={"symbols": "BTC", "window": "1d"}
    )
    res_fetch = await execute_bot_command(MockSession(), cmd_fetch, settings=settings)
    assert res_fetch == {"inserted": 1, "symbols": ["BTC"], "window": "1d"}
    assert fetch_kwargs["crypto_provider"] == "coingecko"
    assert fetch_kwargs["crypto_fallback_provider"] == "binance"
    assert fetch_kwargs["coingecko_api_key"] == "demo-key"

    # Test catalyst.review command
    cmd_review = BotCommand(
        command_type="catalyst.review",
        payload={"window": "1d"}
    )
    res_review = await execute_bot_command(MockSession(), cmd_review, settings=settings)
    assert res_review == {"created": 2, "window": "1d"}
