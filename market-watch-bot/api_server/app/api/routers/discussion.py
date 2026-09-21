from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api_server.app.api.dependencies import SessionDep, SettingsDep
from api_server.app.schemas import DiscussionChatRequest, DiscussionChatResponse
from api_server.app.services import discussion as discussion_service

router = APIRouter()


@router.post("/discussion/chat", response_model=DiscussionChatResponse)
async def discussion_chat(
    payload: DiscussionChatRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> DiscussionChatResponse:
    try:
        result = await discussion_service.chat(session, payload=payload, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DiscussionChatResponse.model_validate(result)
