from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@192.168.100.39:5432/market_watch_assistant"
)


class AppConfig(BaseModel):
    name: str = "market-watch-assistant"
    environment: str = "development"


class BotConfig(BaseModel):
    polling_interval_seconds: int = 300
    default_retention_days: int = 60
    timezone: str = "Asia/Ho_Chi_Minh"


class IngestionConfig(BaseModel):
    rss_freshness_hours: int = 72


class AlertConfig(BaseModel):
    immediate_threshold: int = 80
    watchlist_threshold: int = 55
    digest_threshold: int = 30
    default_channel: str = "log"


class EmbeddingSettings(BaseModel):
    provider: str = "openrouter"
    api_base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/text-embedding-3-large"
    dimensions: int = 1536
    api_key_env: str = "OPENROUTER_API_KEY"
    version: str = "v1"
    cluster_attach_enabled: bool = True
    cluster_attach_lookback_days: int = 7
    cluster_attach_min_similarity: float = 0.88
    cluster_attach_candidate_limit: int = 20
    max_concurrency: int = Field(default=3, ge=1)


class LLMSettings(BaseModel):
    enabled: bool = False
    provider: str = "openrouter"
    api_base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-4.1-mini"
    api_key_env: str = "OPENROUTER_API_KEY"
    prompt_version: str = "event-v1"
    temperature: float = 0.1
    max_tokens: int = 700
    timeout_seconds: int = 45
    max_concurrency: int = Field(default=3, ge=1)
    high_score_threshold: int = 80
    single_source_score_threshold: int = 90
    market_move_score_threshold: int = 70
    relevance_score_threshold: int = 80
    min_modifier: int = -10
    max_modifier: int = 10
    cluster_decision_enabled: bool = True
    cluster_ambiguous_min_similarity: float = 0.78
    cluster_decision_min_confidence: int = 70
    cluster_decision_candidate_limit: int = 3


class InvestigationSettings(BaseModel):
    enabled: bool = False
    brave_search_api_key_env: str = "BRAVE_SEARCH_API_KEY"
    max_search_results: int = Field(default=10, ge=1)
    max_evidence_items: int = Field(default=12, ge=1)
    local_evidence_limit: int = Field(default=10, ge=0)
    local_evidence_lookback_days: int = Field(default=3, ge=1)
    timeout_seconds: int = 20
    max_concurrency: int = Field(default=2, ge=1)
    auto_event_score_threshold: int = 80
    auto_single_source_score_threshold: int = 90
    auto_market_move_score_threshold: int = 70
    min_modifier: int = -10
    max_modifier: int = 10


class MarketDataConfig(BaseModel):
    vn_base_url: str = "http://192.168.100.39:8020"
    crypto_provider: str = "binance"
    crypto_fallback_provider: str = "coingecko"
    global_provider: str = "yahoo"
    symbol_map: dict[str, str] = Field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "SPY": "SPY",
            "QQQ": "QQQ",
            "GLD": "GLD",
            "USO": "USO",
        }
    )


class SourcePresetConfig(BaseModel):
    source_types: list[str] = Field(
        default_factory=lambda: [
            "rss",
            "api",
            "crawler",
            "official",
            "newsletter",
            "social",
            "market_data",
        ]
    )
    regions: list[str] = Field(
        default_factory=lambda: ["global", "asia", "us", "vietnam", "china", "crypto", "other"]
    )
    categories: list[str] = Field(
        default_factory=lambda: [
            "global_macro",
            "us_equity",
            "vietnam_equity",
            "crypto",
            "commodity",
            "fx",
            "rates",
            "geopolitics",
            "company_disclosure",
            "exchange_announcement",
        ]
    )
    languages: list[str] = Field(default_factory=lambda: ["en", "vi", "zh", "ja", "multi"])


class WatchlistPresetConfig(BaseModel):
    entity_types: list[str] = Field(
        default_factory=lambda: [
            "equity",
            "etf",
            "crypto",
            "macro_theme",
            "commodity",
            "currency",
            "sector",
            "company",
            "index",
        ]
    )
    tiers: list[str] = Field(default_factory=lambda: ["S", "A", "B", "C", "D"])
    regions: list[str] = Field(
        default_factory=lambda: ["global", "asia", "us", "vietnam", "china", "crypto", "other"]
    )
    asset_classes: list[str] = Field(
        default_factory=lambda: [
            "equity",
            "crypto",
            "global_macro",
            "vietnam_equity",
            "us_equity",
            "commodity",
            "fx",
            "rates",
            "credit",
        ]
    )


class ConfigurationPresetConfig(BaseModel):
    sources: SourcePresetConfig = Field(default_factory=SourcePresetConfig)
    watchlist: WatchlistPresetConfig = Field(default_factory=WatchlistPresetConfig)


class RetentionConfig(BaseModel):
    fetch_logs_days: int = 14
    raw_news_items_days: int = 60
    normalized_news_items_days: int = 180
    event_clusters_days: int = 1095
    alert_decisions_days: int = 365


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_file: str | None = ".log/market-watch-bot.log"
    console: bool = True
    max_lines: int = 10000
    backup_count: int = 5


class Settings(BaseModel):
    database_url: str = DEFAULT_DATABASE_URL
    openrouter_api_key: str | None = None
    brave_search_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    api_base_url: str = "http://localhost:8000"
    redis_url: str | None = None
    app: AppConfig = Field(default_factory=AppConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    embeddings: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    investigation: InvestigationSettings = Field(default_factory=InvestigationSettings)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    configuration_presets: ConfigurationPresetConfig = Field(
        default_factory=ConfigurationPresetConfig
    )
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)



@dataclass(frozen=True)
class StarterSource:
    name: str
    url: str
    region: str
    category: str
    source_type: str
    language: str
    source_score: int
    polling_interval_seconds: int


STARTER_SOURCES = [
    StarterSource(
        name="Federal Reserve Press Releases",
        url="https://www.federalreserve.gov/feeds/press_all.xml",
        region="us",
        category="global_macro",
        source_type="official",
        language="en",
        source_score=100,
        polling_interval_seconds=900,
    ),
    StarterSource(
        name="MarketWatch Top Stories",
        url="https://feeds.marketwatch.com/marketwatch/topstories/",
        region="global",
        category="global_macro",
        source_type="rss",
        language="en",
        source_score=70,
        polling_interval_seconds=600,
    ),
    StarterSource(
        name="Vietstock",
        url="https://vietstock.vn/830/chung-khoan/co-phieu.rss",
        region="vietnam",
        category="vietnam_equity",
        source_type="rss",
        language="vi",
        source_score=70,
        polling_interval_seconds=900,
    ),
    StarterSource(
        name="CoinDesk",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        region="crypto",
        category="crypto",
        source_type="rss",
        language="en",
        source_score=75,
        polling_interval_seconds=600,
    ),
]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _read_env(path: Path) -> dict[str, str]:
    file_values = (
        {k: v for k, v in dotenv_values(path).items() if v is not None} if path.exists() else {}
    )
    process_values = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "DATABASE_URL",
            "OPENROUTER_API_KEY",
            "BRAVE_SEARCH_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "API_BASE_URL",
            "REDIS_URL",
        }
    }
    return {**file_values, **process_values}


def load_settings(
    env_file: Path | str = ".env", settings_file: Path | str = "settings.yml"
) -> Settings:
    yaml_data = _read_yaml(Path(settings_file))
    env_data = _read_env(Path(env_file))
    merged: dict[str, Any] = {
        **yaml_data,
        "database_url": env_data.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        "openrouter_api_key": env_data.get("OPENROUTER_API_KEY"),
        "brave_search_api_key": env_data.get("BRAVE_SEARCH_API_KEY"),
        "telegram_bot_token": env_data.get("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": env_data.get("TELEGRAM_CHAT_ID"),
        "api_base_url": env_data.get("API_BASE_URL", "http://localhost:8000"),
        "redis_url": env_data.get("REDIS_URL"),
    }
    return Settings.model_validate(merged)


def write_default_files(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    template_dir = Path(__file__).resolve().parent.parent
    for filename in (".env.example", "settings.yml"):
        target = project_dir / filename
        if not target.exists():
            shutil.copyfile(template_dir / filename, target)
    env_file = project_dir / ".env"
    if not env_file.exists():
        shutil.copyfile(project_dir / ".env.example", env_file)


def starter_sources_yaml() -> str:
    data = [
        {
            "name": source.name,
            "url": source.url,
            "region": source.region,
            "category": source.category,
            "type": source.source_type,
            "language": source.language,
            "score": source.source_score,
            "interval": source.polling_interval_seconds,
        }
        for source in STARTER_SOURCES
    ]
    return yaml.safe_dump({"sources": data}, sort_keys=False)
