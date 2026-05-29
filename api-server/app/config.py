from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@192.168.100.39:5432/market_watch_assistant"
)


class AppConfig(BaseModel):
    name: str = "market-watch-api"
    environment: str = "development"


class Settings(BaseModel):
    database_url: str = DEFAULT_DATABASE_URL
    api_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    app: AppConfig = Field(default_factory=AppConfig)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _read_env(path: Path) -> dict[str, str]:
    file_values = (
        {key: value for key, value in dotenv_values(path).items() if value is not None}
        if path.exists()
        else {}
    )
    process_values = {
        key: value
        for key, value in os.environ.items()
        if key in {"DATABASE_URL", "API_CORS_ORIGINS"}
    }
    return {**file_values, **process_values}


def load_settings(
    env_file: Path | str = ".env", settings_file: Path | str = "settings.yml"
) -> Settings:
    yaml_data = _read_yaml(Path(settings_file))
    env_data = _read_env(Path(env_file))
    origins = env_data.get("API_CORS_ORIGINS")
    return Settings.model_validate(
        {
            **yaml_data,
            "database_url": env_data.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            "api_cors_origins": (
                [origin.strip() for origin in origins.split(",") if origin.strip()]
                if origins
                else ["http://localhost:5173"]
            ),
        }
    )
