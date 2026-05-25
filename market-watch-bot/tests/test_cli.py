from typer.testing import CliRunner

import bot_worker.cli as cli
from bot_worker.cli import app

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
