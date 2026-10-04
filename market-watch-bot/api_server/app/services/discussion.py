from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import DiscussionChatRequest
from common import discussion
from common.config import Settings


async def chat(
    session: AsyncSession,
    *,
    payload: DiscussionChatRequest,
    settings: Settings,
) -> dict[str, object]:
    return await discussion.chat(
        session,
        timeframe=payload.timeframe,
        messages=[message.model_dump() for message in payload.messages],
        settings=settings,
    )
