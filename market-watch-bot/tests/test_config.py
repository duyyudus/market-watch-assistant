from pathlib import Path

from bot_worker.config import STARTER_SOURCES, load_settings


def test_load_settings_merges_env_and_yaml(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    settings_file = tmp_path / "settings.yml"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/app",
                "OPENROUTER_API_KEY=secret-key",
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
    assert settings.openrouter_api_key == "secret-key"
    assert settings.app.name == "custom-watch"
    assert settings.app.environment == "test"
    assert settings.bot.polling_interval_seconds == 42
    assert settings.alerts.immediate_threshold == 77


def test_load_settings_uses_documented_defaults(tmp_path: Path) -> None:
    settings = load_settings(
        env_file=tmp_path / "missing.env", settings_file=tmp_path / "missing.yml"
    )

    assert (
        settings.database_url
        == "postgresql+asyncpg://postgres:postgres@192.168.100.39:5432/market_watch_assistant"
    )
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
    assert settings.market_data.global_provider == "yahoo"
    assert settings.market_data.symbol_map["SPY"] == "SPY"


def test_vietnam_starter_source_points_to_real_rss_feed() -> None:
    vietstock = next(source for source in STARTER_SOURCES if source.name == "Vietstock")

    assert vietstock.url == "https://vietstock.vn/830/chung-khoan/co-phieu.rss"


def test_market_starter_source_uses_reachable_rss_feed() -> None:
    marketwatch = next(
        source for source in STARTER_SOURCES if source.name == "MarketWatch Top Stories"
    )

    assert marketwatch.url == "https://feeds.marketwatch.com/marketwatch/topstories/"
