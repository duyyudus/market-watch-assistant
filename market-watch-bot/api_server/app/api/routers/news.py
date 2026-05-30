from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import ListEnvelope, NewsRead
from api_server.app.services import news as news_service
from common.db.models import NormalizedNewsItem

router = APIRouter()


@router.get("/news", response_model=ListEnvelope[NewsRead])
async def list_news(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = None,
) -> ListEnvelope[NewsRead]:
    rows, total = await news_service.list_news(
        session, limit=limit, offset=offset, status_filter=status_filter, q=q
    )
    return ListEnvelope(items=[NewsRead.model_validate(row) for row in rows], total=total)


@router.get("/news/{news_id}")
async def get_news(
    news_id: str,
    session: SessionDep,
) -> dict[str, object]:
    item = await session.get(NormalizedNewsItem, news_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    return await news_service.get_news_detail(session, item)
