from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import AlertPolicy, ConfigurationPresets
from api_server.app.services import settings as settings_service

router = APIRouter()


@router.get("/settings/alert-policy", response_model=AlertPolicy)
async def get_alert_policy(session: SessionDep) -> AlertPolicy:
    return await settings_service.get_alert_policy(session)


@router.patch("/settings/alert-policy", response_model=AlertPolicy)
async def update_alert_policy(
    payload: AlertPolicy,
    session: SessionDep,
) -> AlertPolicy:
    return await settings_service.update_alert_policy(session, payload)


@router.get("/settings/presets", response_model=ConfigurationPresets)
async def get_configuration_presets(session: SessionDep) -> ConfigurationPresets:
    presets = await settings_service.get_configuration_presets(session)
    if presets is None:
        raise HTTPException(
            status_code=503,
            detail="Configuration presets are not initialized; run market-watch migrate",
        )
    return presets
