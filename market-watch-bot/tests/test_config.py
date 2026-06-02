from pathlib import Path

import pytest

from bot_worker.config import Settings, load_settings
from bot_worker.db.models import AppSetting, NewsSource
from bot_worker.services.sources import seed_configuration_presets, seed_starter_sources


def test_load_settings_merges_env_and_yaml(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    settings_file = tmp_path / "settings.yml"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app",
                "API_AUTH_TOKEN=api-secret",
                "OPENROUTER_API_KEY=secret-key",
                "BRAVE_SEARCH_API_KEY=brave-key",
            ]
        ),
        encoding="utf-8",
    )
    settings_file.write_text(
        """
app:
  name: custom-watch
  environment: test
bot:
  polling_interval_seconds: 42
alerts:
  immediate_threshold: 77
""",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, settings_file=settings_file)

    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/app"
    assert settings.api_auth_token == "api-secret"
    assert settings.openrouter_api_key == "secret-key"
    assert settings.brave_search_api_key == "brave-key"
    assert settings.app.name == "custom-watch"
    assert settings.app.environment == "test"
    assert settings.bot.polling_interval_seconds == 42
    assert settings.alerts.immediate_threshold == 77


def test_load_settings_requires_database_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        load_settings(env_file=tmp_path / "missing.env", settings_file=tmp_path / "missing.yml")


def test_load_settings_uses_documented_defaults_with_explicit_database_url(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, settings_file=tmp_path / "missing.yml")

    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/app"
    assert settings.api_auth_token is None
    assert settings.bot.default_retention_days == 60
    assert settings.alerts.watchlist_threshold == 55
    assert settings.llm.enabled is False
    assert settings.embeddings.max_concurrency == 3
    assert settings.llm.provider == "openrouter"
    assert settings.llm.model == "openai/gpt-4.1-mini"
    assert settings.llm.max_concurrency == 3
    assert settings.llm.min_modifier == -10
    assert settings.llm.max_modifier == 10
    assert settings.llm.cluster_decision_enabled is True
    assert settings.llm.cluster_ambiguous_min_similarity == 0.78
    assert settings.llm.cluster_decision_min_confidence == 70
    assert settings.llm.cluster_decision_candidate_limit == 3
    assert settings.investigation.enabled is False
    assert settings.investigation.max_search_results == 10
    assert settings.investigation.max_evidence_items == 12
    assert settings.investigation.local_evidence_limit == 10
    assert settings.investigation.local_evidence_lookback_days == 3
    assert settings.investigation.auto_event_score_threshold == 80
    assert settings.bot.command_poll_interval_seconds == 2
    assert settings.bot.command_drain_limit == 25
    assert "utm_source" in settings.ingestion.tracking_params
    assert "sec.gov" in settings.investigation.official_domains
    assert "reuters.com" in settings.investigation.high_quality_domains
    assert settings.market_data.global_provider == "yahoo"
    assert settings.market_data.symbol_map["SPY"] == "SPY"
    assert settings.configuration_presets.sources.source_types == ["rss", "crawler"]
    assert settings.configuration_presets.watchlist.tiers == ["S", "A", "B", "C", "D"]


class PresetSeedSession:
    def __init__(self, existing: AppSetting | None = None) -> None:
        self.existing = existing
        self.added: list[AppSetting] = []

    async def get(self, _model, key: str) -> AppSetting | None:
        assert key == "configuration_presets"
        return self.existing

    def add(self, value: AppSetting) -> None:
        self.added.append(value)


async def test_seed_configuration_presets_writes_bot_settings_to_shared_app_settings() -> None:
    session = PresetSeedSession()

    changed = await seed_configuration_presets(session, Settings())

    assert changed is True
    assert session.added[0].key == "configuration_presets"
    assert session.added[0].value["sources"]["source_types"] == ["rss", "crawler"]
    assert session.added[0].value["watchlist"]["tiers"] == ["S", "A", "B", "C", "D"]


async def test_seed_configuration_presets_updates_existing_shared_app_setting() -> None:
    existing = AppSetting(key="configuration_presets", value={"sources": {}, "watchlist": {}})
    session = PresetSeedSession(existing)

    changed = await seed_configuration_presets(session, Settings())

    assert changed is True
    assert existing.value["sources"]["categories"][0] == "global_macro"


def test_vietnam_starter_source_points_to_real_rss_feed() -> None:
    import yaml
    paths_to_try = [
        Path("starter-sources.yml"),
        Path(__file__).resolve().parent.parent / "starter-sources.yml",
    ]
    sources_path = next(p for p in paths_to_try if p.exists())
    data = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    vietstock = next(
        source for source in data["sources"] if source["name"] == "Vietstock - Chung Khoan"
    )

    assert vietstock["url"] == "http://vietstock.vn/144/chung-khoan.rss"


def test_coindesk_starter_source_uses_reachable_rss_feed() -> None:
    import yaml
    paths_to_try = [
        Path("starter-sources.yml"),
        Path(__file__).resolve().parent.parent / "starter-sources.yml",
    ]
    sources_path = next(p for p in paths_to_try if p.exists())
    data = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    coindesk = next(
        source for source in data["sources"] if source["name"] == "CoinDesk"
    )

    assert coindesk["url"] == "https://www.coindesk.com/arc/outboundfeeds/rss/"


def test_starter_crawler_sources_keep_known_access_denied_sections_disabled() -> None:
    import yaml
    paths_to_try = [
        Path("starter-sources.yml"),
        Path(__file__).resolve().parent.parent / "starter-sources.yml",
    ]
    sources_path = next(p for p in paths_to_try if p.exists())
    data = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    crawler_sources = [source for source in data["sources"] if source["type"] == "crawler"]
    blocked_sources = [
        source
        for source in crawler_sources
        if "reuters.com" in source["url"] or "ft.com" in source["url"]
    ]

    assert crawler_sources
    assert blocked_sources
    assert all(source["enabled"] is False for source in blocked_sources)


async def test_seed_starter_sources_preserves_disabled_source_flag(monkeypatch, tmp_path) -> None:
    starter = tmp_path / "starter-sources.yml"
    starter.write_text(
        """
sources:
  - name: Blocked Crawler
    url: https://www.reuters.com/business/
    region: global
    category: global_macro
    type: crawler
    language: en
    score: 85
    interval: 900
    enabled: false
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    added: list[NewsSource] = []

    class SeedSession:
        async def scalar(self, _stmt):
            return None

        async def execute(self, stmt):
            source = NewsSource(**stmt.compile().params)
            added.append(source)

            class Result:
                rowcount = 1

            return Result()

    changed = await seed_starter_sources(SeedSession())

    assert changed == 1
    assert added[0].source_type == "crawler"
    assert added[0].enabled is False
