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


class AlertConfig(BaseModel):
    immediate_threshold: int = 80
    watchlist_threshold: int = 55
    digest_threshold: int = 30
    default_channel: str = "log"


class RetentionConfig(BaseModel):
    fetch_logs_days: int = 14
    raw_news_items_days: int = 60
    normalized_news_items_days: int = 180
    event_clusters_days: int = 1095
    alert_decisions_days: int = 365


class Settings(BaseModel):
    database_url: str = DEFAULT_DATABASE_URL
    openrouter_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    api_base_url: str = "http://localhost:8000"
    redis_url: str | None = None
    app: AppConfig = Field(default_factory=AppConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)


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
        name="Investing.com News",
        url="https://www.investing.com/rss/news.rss",
        region="global",
        category="global_macro",
        source_type="rss",
        language="en",
        source_score=70,
        polling_interval_seconds=600,
    ),
    StarterSource(
        name="Vietstock",
        url="https://vietstock.vn/rss.htm",
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
