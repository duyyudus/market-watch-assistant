from pathlib import Path

import pytest
import yaml

from bot_worker.config import Settings, load_settings, validate_source_type
from bot_worker.db.models import AppSetting, NewsSource
from bot_worker.services.sources import seed_configuration_presets, seed_starter_sources


def _load_repo_yaml(filename: str) -> dict[str, object]:
    paths_to_try = [
        Path(filename),
        Path(__file__).resolve().parent.parent / filename,
    ]
    path = next(p for p in paths_to_try if p.exists())
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
                "COINGECKO_API_KEY=coingecko-key",
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
    assert settings.coingecko_api_key == "coingecko-key"
    assert settings.app.name == "custom-watch"
    assert settings.app.environment == "test"
    assert settings.bot.polling_interval_seconds == 42
    assert settings.alerts.immediate_threshold == 77


def test_load_settings_reads_coingecko_api_key_from_process_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COINGECKO_API_KEY", "process-coingecko-key")

    settings = load_settings(env_file=env_file, settings_file=tmp_path / "missing.yml")

    assert settings.coingecko_api_key == "process-coingecko-key"


def test_load_settings_ignores_redundant_api_base_url(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app",
                "API_BASE_URL=https://api.example.test",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, settings_file=tmp_path / "missing.yml")

    assert "api_base_url" not in Settings.model_fields
    assert not hasattr(settings, "api_base_url")


def test_load_settings_reads_api_cors_configuration(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app",
                "API_CORS_ORIGINS=http://localhost:3040,https://dashboard.example.test",
                r"API_CORS_ORIGIN_REGEX=^https?://dashboard\.example\.test(:\d+)?$",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, settings_file=tmp_path / "missing.yml")

    assert settings.api_cors_origins == [
        "http://localhost:3040",
        "https://dashboard.example.test",
    ]
    assert settings.api_cors_origin_regex == r"^https?://dashboard\.example\.test(:\d+)?$"


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
    assert settings.llm.service_tier is None
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
    assert settings.market_data.global_provider == "hyperliquid"
    assert settings.market_data.hyperliquid_base_url == "https://api.hyperliquid.xyz"
    assert settings.market_data.hyperliquid_dex == "xyz"
    assert settings.market_data.hyperliquid_min_day_notional_volume == 100000
    assert settings.market_data.symbol_map["SPX"] == "xyz:SP500"
    assert settings.market_data.symbol_map["GOLD"] == "xyz:GOLD"
    assert settings.market_data.symbol_map["CL"] == "xyz:CL"
    assert settings.configuration_presets.sources.source_types == ["rss", "google-rss", "crawler"]
    assert settings.configuration_presets.watchlist.tiers == ["S", "A", "B", "C", "D"]


def test_load_settings_accepts_openrouter_service_tier(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    settings_file = tmp_path / "settings.yml"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app\n",
        encoding="utf-8",
    )
    settings_file.write_text(
        """
llm:
  service_tier: priority
""",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, settings_file=settings_file)

    assert settings.llm.service_tier == "priority"


def test_load_settings_rejects_invalid_openrouter_service_tier(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    settings_file = tmp_path / "settings.yml"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app\n",
        encoding="utf-8",
    )
    settings_file.write_text(
        """
llm:
  service_tier: standard
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="service_tier"):
        load_settings(env_file=env_file, settings_file=settings_file)


def test_validate_source_type_accepts_google_rss() -> None:
    assert validate_source_type("google-rss") == "google-rss"


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
    assert session.added[0].value["sources"]["source_types"] == ["rss", "google-rss", "crawler"]
    assert session.added[0].value["watchlist"]["tiers"] == ["S", "A", "B", "C", "D"]


async def test_seed_configuration_presets_updates_existing_shared_app_setting() -> None:
    existing = AppSetting(key="configuration_presets", value={"sources": {}, "watchlist": {}})
    session = PresetSeedSession(existing)

    changed = await seed_configuration_presets(session, Settings())

    assert changed is True
    assert existing.value["sources"]["categories"][0] == "global_macro"


def test_vietnam_starter_source_points_to_real_rss_feed() -> None:
    data = _load_repo_yaml("starter-sources.yml")
    vietstock = next(
        source for source in data["sources"] if source["name"] == "Vietstock - Tai Chinh"
    )

    assert vietstock["url"] == "http://vietstock.vn/734/tai-chinh.rss"


def test_coindesk_starter_source_uses_reachable_rss_feed() -> None:
    data = _load_repo_yaml("starter-sources.yml")
    coindesk = next(
        source for source in data["sources"] if source["name"] == "CoinDesk"
    )

    assert coindesk["url"] == "https://www.coindesk.com/arc/outboundfeeds/rss/"


def test_starter_sources_use_google_rss_instead_of_blocked_ft_reuters_crawlers() -> None:
    data = _load_repo_yaml("starter-sources.yml")
    crawler_sources = [source for source in data["sources"] if source["type"] == "crawler"]
    blocked_crawler_sources = [
        source
        for source in crawler_sources
        if "reuters.com" in source["url"] or "ft.com" in source["url"]
    ]
    google_source_names = {
        source["name"]
        for source in data["sources"]
        if source["type"] == "google-rss"
    }

    assert crawler_sources
    assert blocked_crawler_sources == []
    assert google_source_names >= {
        "Financial Times Google News Markets",
        "Reuters Google News Markets",
    }


def test_starter_sources_include_enabled_google_rss_fallbacks() -> None:
    data = _load_repo_yaml("starter-sources.yml")
    google_sources = {
        source["name"]: source
        for source in data["sources"]
        if source["type"] == "google-rss"
    }

    ft_source = google_sources["Financial Times Google News Markets"]
    reuters_source = google_sources["Reuters Google News Markets"]

    assert "site:ft.com" in ft_source["url"]
    assert "site:reuters.com" in reuters_source["url"]
    assert ft_source.get("enabled", True) is True
    assert reuters_source.get("enabled", True) is True


def test_starter_watchlist_uses_import_export_shape_and_valid_presets() -> None:
    data = _load_repo_yaml("starter-watchlist.yml")
    rows = data["watchlist"]
    presets = Settings().configuration_presets.watchlist
    required_fields = {
        "name",
        "symbol",
        "entity_type",
        "tier",
        "region",
        "asset_class",
        "aliases",
        "enabled",
    }

    assert isinstance(rows, list)
    assert len(rows) >= 30
    for row in rows:
        assert required_fields <= row.keys()
        assert isinstance(row["name"], str) and row["name"].strip()
        assert isinstance(row["symbol"], str) and row["symbol"].strip()
        assert row["symbol"] == row["symbol"].strip().upper()
        assert row["entity_type"] in presets.entity_types
        assert row["tier"] in presets.tiers
        assert row["region"] in presets.regions
        assert row["asset_class"] in presets.asset_classes
        assert isinstance(row["aliases"], list)
        assert isinstance(row["enabled"], bool)

    assert len({row["symbol"] for row in rows}) == len(rows)
    # Starter data need not exercise every preset region / asset_class (e.g. the
    # "other" and "global_macro" catch-alls, or thinly-covered ones); only
    # require that the values it does use are valid presets. Per-row validity is
    # asserted above.
    assert {row["region"] for row in rows} <= set(presets.regions)
    assert {row["asset_class"] for row in rows} <= set(presets.asset_classes)

    enabled_symbols = {row["symbol"] for row in rows if row["enabled"]}
    assert enabled_symbols >= {
        "SPX",
        "NDX",
        "NVDA",
        "AAPL",
        "MSFT",
        "TSLA",
        "META",
        "GOOGL",
        "AMZN",
        "BTC",
        "ETH",
        "SOL",
        "GOLD",
        "SILVER",
        "WTI",
        "BRENT",
        "VIC",
        "VHM",
        "VNM",
        "FPT",
        "HPG",
        "VCB",
        "BID",
        "CTG",
        "MSN",
        "MWG",
        "SSI",
        "GAS",
    }
    assert {"SP500", "XAU", "XAG", "CL", "XRP", "ADA", "DOGE"}.isdisjoint(enabled_symbols)
    assert {"XRP", "ADA", "DOGE"}.isdisjoint({row["symbol"] for row in rows})

    spx = next(row for row in rows if row["symbol"] == "SPX")
    gold = next(row for row in rows if row["symbol"] == "GOLD")
    silver = next(row for row in rows if row["symbol"] == "SILVER")
    wti = next(row for row in rows if row["symbol"] == "WTI")
    assert "SP500" in spx["aliases"]
    assert "XAU" in gold["aliases"]
    assert "XAG" in silver["aliases"]
    assert "CL" in wti["aliases"]


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


async def test_seed_starter_sources_defaults_missing_optional_fields(
    monkeypatch, tmp_path
) -> None:
    starter = tmp_path / "starter-sources.yml"
    starter.write_text(
        """
sources:
  - name: Regular Starter Feed
    url: https://example.com/feed.xml
    region: global
    category: global_macro
    type: rss
    score: 75
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
    assert added[0].language == "en"
    assert added[0].polling_interval_seconds == 900
