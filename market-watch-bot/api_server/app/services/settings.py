from __future__ import annotations

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


async def get_configuration_presets(session: AsyncSession) -> ConfigurationPresets | None:
    setting = await session.get(AppSetting, "configuration_presets")
    if setting is None:
        return None
    return ConfigurationPresets.model_validate(setting.value)
