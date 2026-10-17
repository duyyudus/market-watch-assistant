from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import DiscussionChatRequest
from common import discussion
from common.config import Settings


def discussion_settings(settings: Settings) -> dict[str, int]:
    return {
        "max_window_days": discussion.max_window_days(settings),
        "event_limit": settings.discussion.event_limit,
        "articles_per_event": settings.discussion.articles_per_event,
        "article_text_chars": settings.discussion.article_text_chars,
    }


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
        previous_window_start=payload.previous_window_start,
        previous_window_end=payload.previous_window_end,
        flag_timeframe_conflicts=True,
    )
