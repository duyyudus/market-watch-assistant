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
    domain: str | None = None,
    source_id: str | None = None,
    region: str | None = None,
    q: str | None = None,
) -> ListEnvelope[NewsRead]:
    rows, total = await news_service.list_news(
        session,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
        domain=domain,
        source_id=source_id,
        region=region,
        q=q,
    )
    return ListEnvelope(items=[NewsRead.model_validate(row) for row in rows], total=total)


@router.get("/news/domains", response_model=ListEnvelope[str])
async def list_news_domains(session: SessionDep) -> ListEnvelope[str]:
    domains = await news_service.list_news_domains(session)
    return ListEnvelope(items=domains, total=len(domains))


@router.get("/news/filter-options")
async def list_news_filter_options(session: SessionDep) -> dict[str, list[str]]:
    return await news_service.list_news_filter_options(session)


@router.get("/news/{news_id}")
async def get_news(
    news_id: str,
    session: SessionDep,
) -> dict[str, object]:
    item = await session.get(NormalizedNewsItem, news_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    return await news_service.get_news_detail(session, item)
