from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field

DEFAULT_DATABASE_URL = ""
SUPPORTED_SOURCE_TYPES = ("rss", "google-rss", "crawler")
DEFAULT_API_CORS_ORIGIN_REGEX = (
    r"^https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}):(5173|3040)$"
)


def validate_source_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_SOURCE_TYPES:
        supported = ", ".join(SUPPORTED_SOURCE_TYPES)
        raise ValueError(f"Unsupported source_type: {value}. Supported source types: {supported}")
    return normalized


class AppConfig(BaseModel):
    name: str = "market-watch-assistant"
    environment: str = "development"


class BotConfig(BaseModel):
    polling_interval_seconds: int = 300
    default_retention_days: int = 60
    timezone: str = "Asia/Ho_Chi_Minh"
    command_poll_interval_seconds: int = 2
    command_drain_limit: int = 25
    stale_command_timeout_seconds: int = 600


class IngestionConfig(BaseModel):
    rss_freshness_hours: int = 72
    tracking_params: list[str] = Field(
        default_factory=lambda: [
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
            "fbclid",
            "gclid",
            "ref",
        ]
    )
    # Title substrings that mark routine regulatory/fund disclosures to drop from
    # clustering (see settings.ingestion.disclosure_noise_patterns). None or [] disables
    # the filter; the operator-facing default list lives in settings.yml.
    disclosure_noise_patterns: list[str] | None = None


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
    service_tier: Literal["flex", "priority"] | None = None
    api_key_env: str = "OPENROUTER_API_KEY"
    prompt_version: str = "event-v2"
    temperature: float = 0.1
    max_tokens: int = 1200
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
    auto_rumor_score_threshold: int = 70
    min_modifier: int = -10
    max_modifier: int = 10
    official_domains: list[str] = Field(
        default_factory=lambda: [
            "sec.gov",
            "federalreserve.gov",
            "treasury.gov",
            "sbv.gov.vn",
            "ssc.gov.vn",
            "hsx.vn",
            "hnx.vn",
        ]
    )
    high_quality_domains: list[str] = Field(
        default_factory=lambda: [
            "reuters.com",
            "bloomberg.com",
            "ft.com",
            "wsj.com",
            "coindesk.com",
            "cointelegraph.com",
        ]
    )


class MarketDataConfig(BaseModel):
    vn_base_url: str = "http://192.168.100.39:8020"
    crypto_provider: str = "binance"
    crypto_fallback_provider: str = "coingecko"
    global_provider: str = "hyperliquid"
    hyperliquid_base_url: str = "https://api.hyperliquid.xyz"
    hyperliquid_dex: str = "xyz"
    hyperliquid_min_day_notional_volume: float = 100000
    symbol_map: dict[str, str] = Field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "XRP": "ripple",
            "ADA": "cardano",
            "DOGE": "dogecoin",
            "SPX": "xyz:SP500",
            "SP500": "xyz:SP500",
            "NDX": "xyz:XYZ100",
            "XYZ100": "xyz:XYZ100",
            "GOLD": "xyz:GOLD",
            "XAU": "xyz:GOLD",
            "SILVER": "xyz:SILVER",
            "XAG": "xyz:SILVER",
            "WTI": "xyz:CL",
            "CL": "xyz:CL",
            "BRENT": "xyz:BRENTOIL",
            "NVDA": "xyz:NVDA",
            "AAPL": "xyz:AAPL",
            "MSFT": "xyz:MSFT",
            "TSLA": "xyz:TSLA",
            "META": "xyz:META",
            "GOOGL": "xyz:GOOGL",
            "AMZN": "xyz:AMZN",
        }
    )


class SourcePresetConfig(BaseModel):
    source_types: list[str] = Field(
        default_factory=lambda: list(SUPPORTED_SOURCE_TYPES)
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
    # Directory for per-component log files (api.log, worker-pipeline.log, ...).
    # Set to null/empty to disable file logging (console only).
    log_dir: str | None = ".log"
    console: bool = True
    max_lines: int = 10000
    backup_count: int = 5


class Settings(BaseModel):
    database_url: str = DEFAULT_DATABASE_URL
    api_auth_token: str | None = None
    openrouter_api_key: str | None = None
    brave_search_api_key: str | None = None
    coingecko_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    redis_url: str | None = None
    api_cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    api_cors_origin_regex: str | None = DEFAULT_API_CORS_ORIGIN_REGEX
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
            "COINGECKO_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "API_AUTH_TOKEN",
            "REDIS_URL",
            "API_CORS_ORIGINS",
            "API_CORS_ORIGIN_REGEX",
        }
    }
    return {**file_values, **process_values}


def load_settings(
    env_file: Path | str = ".env", settings_file: Path | str = "settings.yml"
) -> Settings:
    yaml_data = _read_yaml(Path(settings_file))
    env_data = _read_env(Path(env_file))
    origins = env_data.get("API_CORS_ORIGINS")
    origin_regex = env_data.get("API_CORS_ORIGIN_REGEX")
    database_url = env_data.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if not database_url:
        raise ValueError("DATABASE_URL must be set in the environment or .env")
    merged: dict[str, Any] = {
        **yaml_data,
        "database_url": database_url,
        "api_auth_token": env_data.get("API_AUTH_TOKEN"),
        "openrouter_api_key": env_data.get("OPENROUTER_API_KEY"),
        "brave_search_api_key": env_data.get("BRAVE_SEARCH_API_KEY"),
        "coingecko_api_key": env_data.get("COINGECKO_API_KEY"),
        "telegram_bot_token": env_data.get("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": env_data.get("TELEGRAM_CHAT_ID"),
        "redis_url": env_data.get("REDIS_URL"),
        "api_cors_origin_regex": origin_regex or DEFAULT_API_CORS_ORIGIN_REGEX,
    }
    if origins:
        merged["api_cors_origins"] = [
            origin.strip() for origin in origins.split(",") if origin.strip()
        ]
    return Settings.model_validate(merged)


def write_default_files(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    template_dir = Path(__file__).resolve().parent.parent
    for filename in (".env.example", "settings.yml", "starter-sources.yml"):
        target = project_dir / filename
        if not target.exists():
            shutil.copyfile(template_dir / filename, target)
    env_file = project_dir / ".env"
    if not env_file.exists():
        shutil.copyfile(project_dir / ".env.example", env_file)
