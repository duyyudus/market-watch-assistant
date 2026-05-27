from typer.testing import CliRunner

import bot_worker.cli as cli
from bot_worker.cli import app
from bot_worker.db.models import EventCluster, LLMAnalysisRun, NormalizedNewsItem

runner = CliRunner()


def test_cli_init_creates_templates(tmp_path) -> None:
    result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / ".env").exists()
    assert (tmp_path / ".env.example").exists()
    assert (tmp_path / "settings.yml").exists()
    assert "Initialized" in result.output


def test_cli_dry_run_pipeline_does_not_require_database() -> None:
    result = runner.invoke(app, ["pipeline", "run", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run pipeline" in result.output


def test_cli_health_pipeline_does_not_require_database() -> None:
    result = runner.invoke(app, ["health", "pipeline"])

    assert result.exit_code == 0
    assert "pipeline jobs:" in result.output
    assert "retention cutoffs:" in result.output


def test_cli_alert_list_reports_empty_decisions(monkeypatch) -> None:
    class EmptyResult:
        def all(self) -> list:
            return []

    class EmptySession:
        async def execute(self, _stmt):
            return EmptyResult()

    async def fake_with_session(fn):
        return await fn(EmptySession())

    monkeypatch.setattr(cli, "_with_session", fake_with_session)

    result = runner.invoke(app, ["alert", "list"])

    assert result.exit_code == 0
    assert "No alert decisions found" in result.output


def test_cli_source_purge_requires_explicit_confirmation(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_purge_source(_session, identifier: str):
        calls.append(identifier)
        return {"status": "purged", "source": identifier, "news_sources": 1}

    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    monkeypatch.setattr(cli, "_with_session", fake_with_session)
    monkeypatch.setattr(cli, "purge_source", fake_purge_source)

    result = runner.invoke(app, ["source", "purge", "Investing.com News"])

    assert result.exit_code == 1
    assert calls == []
    assert "Refusing to purge without --yes" in result.output


def test_cli_source_purge_reports_deleted_counts(monkeypatch) -> None:
    async def fake_purge_source(_session, identifier: str):
        return {
            "status": "purged",
            "source": identifier,
            "source_fetch_logs": 2,
            "raw_news_items": 3,
            "normalized_news_items": 4,
            "event_clusters": 1,
            "news_sources": 1,
        }

    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    monkeypatch.setattr(cli, "_with_session", fake_with_session)
    monkeypatch.setattr(cli, "purge_source", fake_purge_source)

    result = runner.invoke(app, ["source", "purge", "Investing.com News", "--yes"])

    assert result.exit_code == 0
    assert "Purged source Investing.com News" in result.output
    assert "source_fetch_logs: 2" in result.output
    assert "event_clusters: 1" in result.output


def test_cli_llm_test_show_prompt_does_not_require_network(monkeypatch) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Fed announces emergency liquidity facility",
        final_score=84,
        source_count=1,
        top_source_score=100,
    )

    class PromptSession:
        async def get(self, model, key):
            assert model is EventCluster
            assert key == "evt_1"
            return event

    async def fake_with_session(fn):
        return await fn(PromptSession())

    monkeypatch.setattr(cli, "_with_session", fake_with_session)

    result = runner.invoke(app, ["llm", "test", "--event", "evt_1", "--show-prompt"])

    assert result.exit_code == 0
    assert "Fed announces emergency liquidity facility" in result.output
    assert "Return only JSON" in result.output


def test_cli_llm_test_invalid_event_exits_cleanly(monkeypatch) -> None:
    class MissingSession:
        async def get(self, _model, _key):
            return None

    async def fake_with_session(fn):
        return await fn(MissingSession())

    monkeypatch.setattr(cli, "_with_session", fake_with_session)

    result = runner.invoke(app, ["llm", "test", "--event", "missing", "--show-prompt"])

    assert result.exit_code == 1
    assert "Event cluster not found" in result.output


def test_cli_llm_usage_summarizes_stored_runs(monkeypatch) -> None:
    class Rows:
        def all(self):
            return [
                LLMAnalysisRun(
                    target_type="event_cluster",
                    target_id="evt_1",
                    provider="openrouter",
                    model="openai/gpt-4.1-mini",
                    prompt_version="event-v1",
                    prompt_hash="hash",
                    input_snapshot={},
                    status="succeeded",
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            ]

    class UsageSession:
        async def scalars(self, _stmt):
            return Rows()

    async def fake_with_session(fn):
        return await fn(UsageSession())

    monkeypatch.setattr(cli, "_with_session", fake_with_session)

    result = runner.invoke(app, ["llm", "usage", "--since", "7d"])

    assert result.exit_code == 0
    assert '"runs": 1' in result.output
    assert '"total_tokens": 15' in result.output


def test_cli_llm_enrich_reports_latest_failed_run(monkeypatch) -> None:
    event = EventCluster(
        id="evt_failed",
        canonical_headline="Failed LLM event",
        final_score=84,
        source_count=1,
        top_source_score=100,
    )
    failed = LLMAnalysisRun(
        id="llm_failed",
        target_type="event_cluster",
        target_id="evt_failed",
        provider="openrouter",
        model="openai/gpt-5.4-mini",
        prompt_version="event-v1",
        prompt_hash="hash",
        input_snapshot={},
        status="failed",
        error_message="OpenRouter chat completion failed with HTTP 400: bad request",
    )

    class FailedSession:
        async def get(self, model, key):
            assert model is EventCluster
            assert key == "evt_failed"
            return event

    async def fake_with_session(fn):
        return await fn(FailedSession())

    async def fake_enrich_event_clusters_with_llm(*_args, **_kwargs):
        return 0

    async def fake_latest_successful_llm_analysis(_session, _event_id):
        return None

    async def fake_latest_llm_analysis(_session, _event_id, **_kwargs):
        return failed

    monkeypatch.setattr(cli, "_with_session", fake_with_session)
    monkeypatch.setattr(
        cli,
        "enrich_event_clusters_with_llm",
        fake_enrich_event_clusters_with_llm,
    )
    monkeypatch.setattr(
        cli,
        "latest_successful_llm_analysis",
        fake_latest_successful_llm_analysis,
    )
    monkeypatch.setattr(cli, "latest_llm_analysis", fake_latest_llm_analysis)

    result = runner.invoke(app, ["llm", "enrich", "--event", "evt_failed"])

    assert result.exit_code == 0
    assert '"status": "failed"' in result.output
    assert "HTTP 400" in result.output


def test_cli_llm_classify_uses_news_item_task(monkeypatch) -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Vietnam bank stocks rise",
        source_name="Vietstock",
        source_type="rss",
        source_score=75,
        region="vietnam",
        asset_classes=["equity"],
        language="en",
        url="https://example.test/news",
        title_hash="title",
        normalized_text_hash="text",
    )
    run = LLMAnalysisRun(
        id="llm_classify",
        target_type="news_item",
        target_id="news_1",
        provider="openrouter",
        model="openai/gpt-4.1-mini",
        prompt_version="classify-v1",
        prompt_hash="hash",
        input_snapshot={},
        status="succeeded",
        result={"item_type": "market_news", "actionability": "medium"},
    )

    class ItemSession:
        async def get(self, model, key):
            assert model is NormalizedNewsItem
            assert key == "news_1"
            return item

    async def fake_with_session(fn):
        return await fn(ItemSession())

    async def fake_classify_news_item_with_llm(_session, *, item_id, config, force):
        assert item_id == "news_1"
        assert config.enabled
        assert force
        return run

    monkeypatch.setattr(cli, "_with_session", fake_with_session)
    monkeypatch.setattr(cli, "classify_news_item_with_llm", fake_classify_news_item_with_llm)

    result = runner.invoke(app, ["llm", "classify", "--item", "news_1"])

    assert result.exit_code == 0
    assert '"task": "classify"' in result.output
    assert '"target_type": "news_item"' in result.output


def test_cli_llm_summarize_uses_event_summary_task(monkeypatch) -> None:
    event = EventCluster(id="evt_1", canonical_headline="Oil jumps", final_score=84)
    run = LLMAnalysisRun(
        id="llm_summary",
        target_type="event_cluster",
        target_id="evt_1",
        provider="openrouter",
        model="openai/gpt-4.1-mini",
        prompt_version="summarize-v1",
        prompt_hash="hash",
        input_snapshot={},
        status="succeeded",
        result={"summary": "Oil jumped after a shipping incident."},
    )

    class EventSession:
        async def get(self, model, key):
            assert model is EventCluster
            assert key == "evt_1"
            return event

    async def fake_with_session(fn):
        return await fn(EventSession())

    async def fake_summarize_event_with_llm(_session, *, event_cluster_id, config, force):
        assert event_cluster_id == "evt_1"
        assert config.enabled
        assert force
        return run

    monkeypatch.setattr(cli, "_with_session", fake_with_session)
    monkeypatch.setattr(cli, "summarize_event_with_llm", fake_summarize_event_with_llm)

    result = runner.invoke(app, ["llm", "summarize", "--event", "evt_1"])

    assert result.exit_code == 0
    assert '"task": "summarize"' in result.output
    assert '"prompt_version": "summarize-v1"' in result.output


def test_cli_llm_score_uses_event_score_task(monkeypatch) -> None:
    event = EventCluster(id="evt_1", canonical_headline="Oil jumps", final_score=84)
    run = LLMAnalysisRun(
        id="llm_score",
        target_type="event_cluster",
        target_id="evt_1",
        provider="openrouter",
        model="openai/gpt-4.1-mini",
        prompt_version="score-v1",
        prompt_hash="hash",
        input_snapshot={},
        status="succeeded",
        result={"score_modifier": 4, "modifier_reason": "Market reaction confirms impact."},
    )

    class EventSession:
        async def get(self, model, key):
            assert model is EventCluster
            assert key == "evt_1"
            return event

    async def fake_with_session(fn):
        return await fn(EventSession())

    async def fake_score_event_with_llm(_session, *, event_cluster_id, config, force):
        assert event_cluster_id == "evt_1"
        assert config.enabled
        assert force
        return run

    monkeypatch.setattr(cli, "_with_session", fake_with_session)
    monkeypatch.setattr(cli, "score_event_with_llm", fake_score_event_with_llm)

    result = runner.invoke(app, ["llm", "score", "--event", "evt_1"])

    assert result.exit_code == 0
    assert '"task": "score"' in result.output
    assert '"score_modifier": 4' in result.output
