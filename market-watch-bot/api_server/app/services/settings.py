from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import AlertPolicy, ConfigurationPresets
from common.db.models import AppSetting


async def get_alert_policy(session: AsyncSession) -> AlertPolicy:
    setting = await session.get(AppSetting, "alert_policy")
    if setting is None:
        return AlertPolicy()
    return AlertPolicy.model_validate(setting.value)


async def update_alert_policy(session: AsyncSession, payload: AlertPolicy) -> AlertPolicy:
    setting = await session.get(AppSetting, "alert_policy")
    if setting is None:
        setting = AppSetting(key="alert_policy", value=payload.model_dump())
        session.add(setting)
    else:
        setting.value = payload.model_dump()
    await session.commit()
    return payload


def get_alert_presets() -> dict[str, Any]:
    return {
        "channels": [
            {
                "type": "log",
                "placeholder": "e.g. Local Dev Log",
                "template": {},
                "description": (
                    "Prints alerts directly to the server logs. "
                    "No configuration payload is required."
                ),
                "parameters": {},
            },
            {
                "type": "telegram",
                "placeholder": "e.g. Core Telegram Channel",
                "template": {"chat_id": "123456789"},
                "description": "Dispatches alerts to a target Telegram chat or group.",
                "parameters": {
                    "chat_id": "required: The unique chat, user, or group ID."
                },
            },
            {
                "type": "webhook",
                "placeholder": "e.g. Discord Webhook Alerts",
                "template": {
                    "url": "https://hooks.example.com/alerts",
                    "headers": {"Authorization": "Bearer <token>"},
                },
                "description": "Submits high-fidelity JSON payloads via HTTP POST.",
                "parameters": {
                    "url": "required: Destination HTTP/HTTPS endpoint.",
                    "headers": "optional: Custom HTTP headers dictionary."
                },
            },
        ],
        "rules": [
            {
                "type": "cooldown",
                "placeholder": "e.g. 6-Hour Cooldown",
                "template": {"hours": 6},
                "description": "Dampens frequent repetitions of the same event.",
                "parameters": {
                    "hours": (
                        "required: Quiet interval duration before the same event "
                        "triggers again."
                    )
                },
            },
            {
                "type": "quiet_hours",
                "placeholder": "e.g. Night Quiet Hours",
                "template": {
                    "start_hour": 23,
                    "end_hour": 7,
                    "timezone": "Asia/Ho_Chi_Minh",
                },
                "description": "Suspends notifications during user resting windows.",
                "parameters": {
                    "start_hour": "required: Start hour (24-hour scale, e.g. 23).",
                    "end_hour": "required: End hour (24-hour scale, e.g. 7).",
                    "timezone": "optional: Timezone descriptor (defaults to Asia/Ho_Chi_Minh)."
                },
            },
            {
                "type": "region_filter",
                "placeholder": "e.g. Focus US/VN Macro",
                "template": {
                    "regions": ["us", "vietnam"],
                    "asset_classes": ["global_macro", "crypto"],
                    "weekend_only": False,
                },
                "description": "Silences markets depending on region, category, or time.",
                "parameters": {
                    "regions": "optional: Array of geographic scopes to mute.",
                    "asset_classes": "optional: Array of asset categories to mute.",
                    "weekend_only": "optional: Set to true to mute solely outside the weekend."
                },
            },
            {
                "type": "entity_mute",
                "placeholder": "e.g. Mute Bitcoin Alerts",
                "template": {"entities": ["BTC", "ETH"], "until": "2026-12-31T23:59:59"},
                "description": "Specific ticker or project silencing.",
                "parameters": {
                    "entities": "required: Array of tickers/names (e.g. ['BTC', 'ETH']).",
                    "until": (
                        "optional: ISO-8601 UTC timestamp after which muting "
                        "automatically ends."
                    )
                },
            },
        ],
    }


async def get_configuration_presets(session: AsyncSession) -> ConfigurationPresets | None:
    setting = await session.get(AppSetting, "configuration_presets")
    if setting is None:
        return None
    data = dict(setting.value) if isinstance(setting.value, dict) else {}
    data["alerts"] = get_alert_presets()
    return ConfigurationPresets.model_validate(data)
