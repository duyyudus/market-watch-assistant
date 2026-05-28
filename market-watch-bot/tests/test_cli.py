from typer.testing import CliRunner

import bot_worker.cli.alerts as alert_cli
import bot_worker.cli.events as event_cli
import bot_worker.cli.investigate as investigate_cli
import bot_worker.cli.llm as llm_cli
import bot_worker.cli.retention as retention_cli
import bot_worker.cli.source as source_cli
import bot_worker.cli.worker as worker_cli
from bot_worker.cli import app
from bot_worker.db.models import (
    AgentInvestigation,
    AlertDecisionRecord,
    EventCluster,
    LLMAnalysisRun,
    NormalizedNewsItem,
)

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

    monkeypatch.setattr(alert_cli, "_with_session", fake_with_session)

    result = runner.invoke(app, ["alert", "list"])

    assert result.exit_code == 0
    assert "No alert decisions found" in result.output


def test_cli_alert_channel_show_reports_telegram_configuration(monkeypatch) -> None:
    class Settings:
        telegram_bot_token = "token"
        telegram_chat_id = "chat_1"

        class alerts:
            default_channel = "telegram"

    monkeypatch.setattr(alert_cli, "_settings", lambda: Settings())

    result = runner.invoke(app, ["alert", "channel", "show"])

    assert result.exit_code == 0
    assert '"default_channel": "telegram"' in result.output
    assert '"telegram_bot_token_configured": true' in result.output
    assert '"telegram_chat_id_configured": true' in result.output


def test_cli_alert_send_test_requires_telegram_credentials(monkeypatch) -> None:
    class Settings:
        telegram_bot_token = None
        telegram_chat_id = None

        class alerts:
            default_channel = "telegram"

    monkeypatch.setattr(alert_cli, "_settings", lambda: Settings())

    result = runner.invoke(app, ["alert", "send-test", "--channel", "telegram"])

    assert result.exit_code == 1
    assert "Telegram delivery requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID" in result.output


def test_cli_alert_send_test_calls_delivery_service(monkeypatch) -> None:
    class Settings:
        telegram_bot_token = "token"
        telegram_chat_id = "chat_1"

        class alerts:
            default_channel = "telegram"

    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    calls: list[tuple[object, str]] = []

    async def fake_send_test_alert(session, config, message):
        assert isinstance(session, EmptySession)
        calls.append((config, message))
        return {"status": "sent", "channel": "telegram", "recipient": "chat_1"}

    monkeypatch.setattr(alert_cli, "_settings", lambda: Settings())
    monkeypatch.setattr(alert_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(alert_cli, "send_test_alert", fake_send_test_alert)

    result = runner.invoke(
        app,
        ["alert", "send-test", "--channel", "telegram", "--message", "hello"],
    )

    assert result.exit_code == 0
    assert calls[0][1] == "hello"
    assert '"status": "sent"' in result.output


def test_cli_alert_dispatch_dry_run_prints_pending_counts(monkeypatch) -> None:
    class Settings:
        telegram_bot_token = "token"
        telegram_chat_id = "chat_1"

        class alerts:
            default_channel = "telegram"

    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    async def fake_dispatch_pending_alerts(session, config, *, limit, dry_run):
        assert isinstance(session, EmptySession)
        assert config.channel == "telegram"
        assert limit == 5
        assert dry_run is True
        return {"pending": 2, "attempted": 0, "sent": 0, "failed": 0, "skipped": 1}

    monkeypatch.setattr(alert_cli, "_settings", lambda: Settings())
    monkeypatch.setattr(alert_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(alert_cli, "dispatch_pending_alerts", fake_dispatch_pending_alerts)

    result = runner.invoke(
        app,
        ["alert", "dispatch", "--channel", "telegram", "--limit", "5", "--dry-run"],
    )

    assert result.exit_code == 0
    assert '"pending": 2' in result.output
    assert '"attempted": 0' in result.output
    assert '"skipped": 1' in result.output


def test_cli_investigate_event_runs_service(monkeypatch) -> None:
    class EmptySession:
        pass

    class Settings:
        brave_search_api_key = "brave-key"
        openrouter_api_key = "llm-key"

        class investigation:
            enabled = True
            brave_search_api_key_env = "BRAVE_SEARCH_API_KEY"
            max_search_results = 10
            max_evidence_items = 12
            local_evidence_limit = 10
            local_evidence_lookback_days = 3
            timeout_seconds = 20
            max_concurrency = 2
            auto_event_score_threshold = 80
            auto_single_source_score_threshold = 90
            auto_market_move_score_threshold = 70
            min_modifier = -10
            max_modifier = 10

        class llm:
            enabled = True
            provider = "openrouter"
            api_base_url = "https://openrouter.ai/api/v1"
            model = "model"
            api_key_env = "OPENROUTER_API_KEY"
            prompt_version = "event-v1"
            temperature = 0.1
            max_tokens = 700
            timeout_seconds = 45
            max_concurrency = 3
            high_score_threshold = 80
            single_source_score_threshold = 90
            market_move_score_threshold = 70
            relevance_score_threshold = 80
            min_modifier = -10
            max_modifier = 10
            cluster_decision_enabled = True
            cluster_ambiguous_min_similarity = 0.78
            cluster_decision_min_confidence = 70
            cluster_decision_candidate_limit = 3

    async def fake_with_session(fn):
        return await fn(EmptySession())

    async def fake_run_event_investigation(session, *, event_id, config, llm_config):
        assert isinstance(session, EmptySession)
        assert event_id == "evt_1"
        assert config.brave_search_api_key == "brave-key"
        assert llm_config.api_key == "llm-key"
        return AgentInvestigation(
            id="inv_1",
            target_type="event_cluster",
            target_id=event_id,
            trigger_reason="manual",
            status="succeeded",
            input_snapshot={},
            evidence=[],
            provider="openrouter",
            model="model",
            prompt_version="investigation-v1",
            prompt_hash="hash",
            result={"summary": "checked"},
        )

    monkeypatch.setattr(investigate_cli, "_settings", lambda: Settings())
    monkeypatch.setattr(investigate_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(
        investigate_cli,
        "run_event_investigation",
        fake_run_event_investigation,
    )

    result = runner.invoke(app, ["investigate", "event", "evt_1"])

    assert result.exit_code == 0
    assert '"investigation_id": "inv_1"' in result.output
    assert '"status": "succeeded"' in result.output


def test_cli_investigate_pending_lists_pending_runs(monkeypatch) -> None:
    class PendingSession:
        pass

    async def fake_with_session(fn):
        return await fn(PendingSession())

    async def fake_list_pending_investigations(_session, *, limit):
        assert limit == 10
        return [
            AgentInvestigation(
                id="inv_1",
                target_type="event_cluster",
                target_id="evt_1",
                trigger_reason="auto_event_uncertain",
                status="pending",
                input_snapshot={},
                evidence=[],
            )
        ]

    monkeypatch.setattr(investigate_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(
        investigate_cli,
        "list_pending_investigations",
        fake_list_pending_investigations,
    )

    result = runner.invoke(app, ["investigate", "pending", "--limit", "10"])

    assert result.exit_code == 0
    assert '"id": "inv_1"' in result.output
    assert '"target_type": "event_cluster"' in result.output


def test_cli_investigate_run_pending_executes_pending_runs(monkeypatch) -> None:
    class PendingSession:
        pass

    class Settings:
        brave_search_api_key = "brave-key"
        openrouter_api_key = "llm-key"

        class investigation:
            enabled = True
            brave_search_api_key_env = "BRAVE_SEARCH_API_KEY"
            max_search_results = 10
            max_evidence_items = 12
            local_evidence_limit = 10
            local_evidence_lookback_days = 3
            timeout_seconds = 20
            max_concurrency = 2
            auto_event_score_threshold = 80
            auto_single_source_score_threshold = 90
            auto_market_move_score_threshold = 70
            min_modifier = -10
            max_modifier = 10

        class llm:
            enabled = True
            provider = "openrouter"
            api_base_url = "https://openrouter.ai/api/v1"
            model = "model"
            api_key_env = "OPENROUTER_API_KEY"
            prompt_version = "event-v1"
            temperature = 0.1
            max_tokens = 700
            timeout_seconds = 45
            max_concurrency = 3
            high_score_threshold = 80
            single_source_score_threshold = 90
            market_move_score_threshold = 70
            relevance_score_threshold = 80
            min_modifier = -10
            max_modifier = 10
            cluster_decision_enabled = True
            cluster_ambiguous_min_similarity = 0.78
            cluster_decision_min_confidence = 70
            cluster_decision_candidate_limit = 3

    async def fake_with_session(fn):
        return await fn(PendingSession())

    async def fake_run_pending_investigations(session, *, config, llm_config, limit):
        assert isinstance(session, PendingSession)
        assert config.brave_search_api_key == "brave-key"
        assert llm_config.api_key == "llm-key"
        assert limit == 7
        return {"pending": 2, "completed": 1, "failed": 1}

    monkeypatch.setattr(investigate_cli, "_settings", lambda: Settings())
    monkeypatch.setattr(investigate_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(
        investigate_cli,
        "run_pending_investigations",
        fake_run_pending_investigations,
    )

    result = runner.invoke(app, ["investigate", "run-pending", "--limit", "7"])

    assert result.exit_code == 0
    assert '"completed": 1' in result.output
    assert '"failed": 1' in result.output


def test_cli_investigate_show_reports_result(monkeypatch) -> None:
    class ShowSession:
        async def get(self, _model, key):
            assert key == "inv_1"
            return AgentInvestigation(
                id="inv_1",
                target_type="event_cluster",
                target_id="evt_1",
                trigger_reason="manual",
                status="succeeded",
                input_snapshot={},
                evidence=[],
                result={"summary": "checked"},
            )

    async def fake_with_session(fn):
        return await fn(ShowSession())

    monkeypatch.setattr(investigate_cli, "_with_session", fake_with_session)

    result = runner.invoke(app, ["investigate", "show", "inv_1"])

    assert result.exit_code == 0
    assert '"id": "inv_1"' in result.output
    assert '"summary": "checked"' in result.output


def test_worker_loop_passes_investigation_config_and_runs_pending(monkeypatch) -> None:
    class StopLoop(Exception):
        pass

    class Session:
        pass

    class Settings:
        brave_search_api_key = "brave-key"
        openrouter_api_key = "llm-key"
        telegram_bot_token = None
        telegram_chat_id = None

        class bot:
            polling_interval_seconds = 300

        class ingestion:
            rss_freshness_hours = 24

        class alerts:
            default_channel = "log"

        class embeddings:
            provider = "openrouter"
            api_base_url = "https://openrouter.ai/api/v1"
            model = "embedding-model"
            dimensions = 1536
            api_key_env = "OPENROUTER_API_KEY"
            version = "v1"
            cluster_attach_enabled = True
            cluster_attach_lookback_days = 7
            cluster_attach_min_similarity = 0.88
            cluster_attach_candidate_limit = 20
            max_concurrency = 3

        class llm:
            enabled = True
            provider = "openrouter"
            api_base_url = "https://openrouter.ai/api/v1"
            model = "model"
            api_key_env = "OPENROUTER_API_KEY"
            prompt_version = "event-v1"
            temperature = 0.1
            max_tokens = 700
            timeout_seconds = 45
            max_concurrency = 3
            high_score_threshold = 80
            single_source_score_threshold = 90
            market_move_score_threshold = 70
            relevance_score_threshold = 80
            min_modifier = -10
            max_modifier = 10
            cluster_decision_enabled = True
            cluster_ambiguous_min_similarity = 0.78
            cluster_decision_min_confidence = 70
            cluster_decision_candidate_limit = 3

        class investigation:
            enabled = True
            brave_search_api_key_env = "BRAVE_SEARCH_API_KEY"
            max_search_results = 10
            max_evidence_items = 12
            local_evidence_limit = 10
            local_evidence_lookback_days = 3
            timeout_seconds = 20
            max_concurrency = 2
            auto_event_score_threshold = 80
            auto_single_source_score_threshold = 90
            auto_market_move_score_threshold = 70
            min_modifier = -10
            max_modifier = 10

    async def fake_with_session(fn):
        return await fn(Session())

    async def fake_run_pipeline(session, **kwargs):
        assert isinstance(session, Session)
        assert kwargs["investigation_config"].enabled is True
        return {"status": "ok"}

    async def fake_run_pending(session, *, config, llm_config, limit):
        assert isinstance(session, Session)
        assert config.enabled is True
        assert llm_config.enabled is True
        assert limit == 2
        return {"pending": 0, "completed": 0, "failed": 0}

    async def fake_record_job_run(*_args, **_kwargs):
        return None

    async def stop_sleep(_seconds):
        raise StopLoop

    monkeypatch.setattr(worker_cli, "_settings", lambda: Settings())
    monkeypatch.setattr(worker_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(worker_cli, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(worker_cli, "run_pending_investigations", fake_run_pending)
    monkeypatch.setattr(worker_cli, "record_job_run", fake_record_job_run)
    monkeypatch.setattr(worker_cli.asyncio, "sleep", stop_sleep)

    result = runner.invoke(app, ["worker", "start"])

    assert result.exit_code == 1
    assert isinstance(result.exception, StopLoop)


def test_cli_event_show_reports_event_details(monkeypatch) -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after Gulf shipping disruption",
        summary="Oil rose after reported shipping disruption.",
        status="reported",
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["Brent"],
        affected_tickers=["USO"],
        source_count=2,
        top_source_score=90,
        final_score=82,
    )
    alert = AlertDecisionRecord(
        id="alert_1",
        event_cluster_id="evt_1",
        decision="immediate_alert",
        reason="score_above_immediate_threshold",
        score_breakdown={"final_score": 82},
    )
    investigation = AgentInvestigation(
        id="inv_1",
        target_type="event_cluster",
        target_id="evt_1",
        trigger_reason="auto_event_uncertain",
        status="pending",
        input_snapshot={},
        evidence=[],
    )

    class ShowSession:
        async def get(self, model, key):
            assert model is EventCluster
            assert key == "evt_1"
            return event

        async def scalar(self, stmt):
            text = str(stmt)
            if "alert_decisions" in text:
                return alert
            if "agent_investigations" in text:
                return investigation
            return None

    async def fake_with_session(fn):
        return await fn(ShowSession())

    async def fake_event_report_time_range(_session, event_id):
        assert event_id == "evt_1"
        return None

    monkeypatch.setattr(event_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(event_cli, "event_report_time_range", fake_event_report_time_range)

    result = runner.invoke(app, ["event", "show", "evt_1"])

    assert result.exit_code == 0
    assert '"id": "evt_1"' in result.output
    assert '"headline": "Oil jumps after Gulf shipping disruption"' in result.output
    assert '"latest_alert"' in result.output
    assert '"latest_investigation"' in result.output
    assert "requires event_clusters data" not in result.output


def test_cli_source_purge_requires_explicit_confirmation(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_purge_source(_session, identifier: str):
        calls.append(identifier)
        return {"status": "purged", "source": identifier, "news_sources": 1}

    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    monkeypatch.setattr(source_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(source_cli, "purge_source", fake_purge_source)

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

    monkeypatch.setattr(source_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(source_cli, "purge_source", fake_purge_source)

    result = runner.invoke(app, ["source", "purge", "Investing.com News", "--yes"])

    assert result.exit_code == 0
    assert "Purged source Investing.com News" in result.output
    assert "source_fetch_logs: 2" in result.output
    assert "event_clusters: 1" in result.output


def test_cli_retention_reset_baseline_requires_explicit_confirmation(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_baseline_reset_preview(_session):
        calls.append("preview")
        return {"event_clusters": 2, "news_item_embeddings": 3}

    async def fake_run_baseline_reset(_session):
        calls.append("run")
        return {"event_clusters": 2, "news_item_embeddings": 3}

    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    monkeypatch.setattr(retention_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(retention_cli, "baseline_reset_preview", fake_baseline_reset_preview)
    monkeypatch.setattr(retention_cli, "run_baseline_reset", fake_run_baseline_reset)

    result = runner.invoke(app, ["retention", "reset-baseline"])

    assert result.exit_code == 1
    assert calls == ["preview"]
    assert "Refusing to reset baseline without --yes; preview follows:" in result.output
    assert '"event_clusters": 2' in result.output


def test_cli_retention_reset_baseline_yes_reports_deleted_counts(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_baseline_reset_preview(_session):
        calls.append("preview")
        return {"event_clusters": 2, "news_item_embeddings": 3}

    async def fake_run_baseline_reset(_session):
        calls.append("run")
        return {"event_clusters": 2, "news_item_embeddings": 3}

    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    monkeypatch.setattr(retention_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(retention_cli, "baseline_reset_preview", fake_baseline_reset_preview)
    monkeypatch.setattr(retention_cli, "run_baseline_reset", fake_run_baseline_reset)

    result = runner.invoke(app, ["retention", "reset-baseline", "--yes"])

    assert result.exit_code == 0
    assert calls == ["run"]
    assert '"event_clusters": 2' in result.output
    assert '"news_item_embeddings": 3' in result.output


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

    monkeypatch.setattr(llm_cli, "_with_session", fake_with_session)

    result = runner.invoke(app, ["llm", "test", "--event", "evt_1", "--show-prompt"])

    assert result.exit_code == 0
    assert "Fed announces emergency liquidity facility" in result.output
    assert "Return only JSON" in result.output


def test_cli_event_recluster_dry_run_reports_result(monkeypatch) -> None:
    class EmptySession:
        pass

    async def fake_with_session(fn):
        return await fn(EmptySession())

    async def fake_recluster(_session, *, since, dry_run, limit):
        assert since.tzinfo is not None
        assert dry_run is True
        assert limit == 500
        return {
            "status": "dry_run",
            "affected_clusters": 2,
            "news_items": 2,
            "new_clusters": 0,
        }

    monkeypatch.setattr(event_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(event_cli, "recluster_recent_event_clusters", fake_recluster)

    result = runner.invoke(app, ["event", "recluster", "--since", "48h"])

    assert result.exit_code == 0
    assert '"status": "dry_run"' in result.output
    assert '"affected_clusters": 2' in result.output


def test_cli_event_recluster_requires_confirm_for_mutation() -> None:
    result = runner.invoke(app, ["event", "recluster", "--since", "48h", "--apply"])

    assert result.exit_code == 1
    assert "Use --confirm with --apply" in result.output


def test_cli_llm_test_invalid_event_exits_cleanly(monkeypatch) -> None:
    class MissingSession:
        async def get(self, _model, _key):
            return None

    async def fake_with_session(fn):
        return await fn(MissingSession())

    monkeypatch.setattr(llm_cli, "_with_session", fake_with_session)

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

    monkeypatch.setattr(llm_cli, "_with_session", fake_with_session)

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

    monkeypatch.setattr(llm_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(
        llm_cli,
        "enrich_event_clusters_with_llm",
        fake_enrich_event_clusters_with_llm,
    )
    monkeypatch.setattr(
        llm_cli,
        "latest_successful_llm_analysis",
        fake_latest_successful_llm_analysis,
    )
    monkeypatch.setattr(llm_cli, "latest_llm_analysis", fake_latest_llm_analysis)

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

    monkeypatch.setattr(llm_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(llm_cli, "classify_news_item_with_llm", fake_classify_news_item_with_llm)

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

    monkeypatch.setattr(llm_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(llm_cli, "summarize_event_with_llm", fake_summarize_event_with_llm)

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

    monkeypatch.setattr(llm_cli, "_with_session", fake_with_session)
    monkeypatch.setattr(llm_cli, "score_event_with_llm", fake_score_event_with_llm)

    result = runner.invoke(app, ["llm", "score", "--event", "evt_1"])

    assert result.exit_code == 0
    assert '"task": "score"' in result.output
    assert '"score_modifier": 4' in result.output
