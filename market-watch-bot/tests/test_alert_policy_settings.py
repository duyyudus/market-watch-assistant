from __future__ import annotations

import pytest

from bot_worker.db.models import AppSetting
from bot_worker.services.alerts import alert_thresholds_from_settings


class SettingsResult:
    def __init__(self, setting: AppSetting | None) -> None:
        self.setting = setting

    def scalar_one_or_none(self) -> AppSetting | None:
        return self.setting


class SettingsSession:
    def __init__(self, setting: AppSetting | None) -> None:
        self.setting = setting

    async def execute(self, _stmt):
        return SettingsResult(self.setting)


@pytest.mark.asyncio
async def test_alert_thresholds_from_settings_uses_database_override() -> None:
    session = SettingsSession(
        AppSetting(
            key="alert_policy",
            value={
                "immediate_threshold": 81,
                "watchlist_threshold": 56,
                "digest_threshold": 31,
                "default_channel": "telegram",
            },
        )
    )

    thresholds, channel = await alert_thresholds_from_settings(session)

    assert thresholds.immediate == 81
    assert thresholds.watchlist == 56
    assert thresholds.digest == 31
    assert channel == "telegram"


@pytest.mark.asyncio
async def test_alert_thresholds_from_settings_falls_back_to_defaults() -> None:
    thresholds, channel = await alert_thresholds_from_settings(SettingsSession(None))

    assert thresholds.immediate == 80
    assert thresholds.watchlist == 55
    assert thresholds.digest == 30
    assert channel == "log"


@pytest.mark.asyncio
async def test_alert_thresholds_from_settings_ignores_malformed_values() -> None:
    session = SettingsSession(
        AppSetting(
            key="alert_policy",
            value={
                "immediate_threshold": "not-an-int",
                "watchlist_threshold": None,
                "digest_threshold": 31,
                "default_channel": "",
            },
        )
    )

    thresholds, channel = await alert_thresholds_from_settings(session)

    assert thresholds.immediate == 80
    assert thresholds.watchlist == 55
    assert thresholds.digest == 31
    assert channel == "log"


@pytest.mark.asyncio
async def test_alert_thresholds_from_settings_handles_non_mapping_policy() -> None:
    session = SettingsSession(AppSetting(key="alert_policy", value="broken"))

    thresholds, channel = await alert_thresholds_from_settings(session)

    assert thresholds.immediate == 80
    assert thresholds.watchlist == 55
    assert thresholds.digest == 30
    assert channel == "log"
