from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import AlertPolicy, ConfigurationPresets
from api_server.app.services import settings as settings_service
from common.watched_topics import WatchedTopics, get_watched_topics, save_watched_topics

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


@router.get("/settings/watched-topics", response_model=WatchedTopics)
async def read_watched_topics(session: SessionDep) -> WatchedTopics:
    return await get_watched_topics(session)


@router.put("/settings/watched-topics", response_model=WatchedTopics)
async def update_watched_topics(payload: WatchedTopics, session: SessionDep) -> WatchedTopics:
    return await save_watched_topics(session, payload)
