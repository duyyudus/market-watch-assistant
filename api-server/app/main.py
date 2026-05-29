from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_settings
from app.db import get_session
from app.models import (
    AgentInvestigation,
    AlertDecision,
    AlertDelivery,
    AppSetting,
    BotCommand,
    EventCluster,
    EventClusterItem,
    EventScoreHistory,
    JobRun,
    MarketMove,
    NewsEntity,
    NewsSource,
    NormalizedNewsItem,
    SourceFetchLog,
    WatchlistEntity,
)
from app.schemas import (
    ALLOWED_COMMAND_TYPES,
    AlertPolicy,
    AlertRead,
    BotCommandCreate,
    BotCommandRead,
    EntityRead,
    EventRead,
    JobRunRead,
    ListEnvelope,
    NewsRead,
    SourceCreate,
    SourceRead,
    SourceUpdate,
    WatchlistCreate,
    WatchlistRead,
    WatchlistUpdate,
)

settings = load_settings()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
app = FastAPI(title="Market Watch API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_origin_regex=(
        r"^https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}):5173$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def count_for(session: AsyncSession, stmt: Select) -> int:
    return int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


async def latest_job_for_status(session: AsyncSession) -> tuple[JobRun | None, bool]:
    try:
        latest_job = await session.scalar(
            select(JobRun).order_by(JobRun.started_at.desc()).limit(1)
        )
    except SQLAlchemyError:
        await session.rollback()
        return None, False
    return latest_job, True


async def bot_command_count(session: AsyncSession, command_status: str) -> tuple[int, bool]:
    try:
        count = await session.scalar(
            select(func.count()).select_from(BotCommand).where(BotCommand.status == command_status)
        )
    except SQLAlchemyError:
        await session.rollback()
        return 0, False
    return int(count or 0), True


def apply_pagination(stmt: Select, *, limit: int, offset: int) -> Select:
    return stmt.limit(limit).offset(offset)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": settings.app.name,
        "environment": settings.app.environment,
    }


@app.get("/bot/status")
async def bot_status(session: SessionDep) -> dict[str, object]:
    latest_job, latest_job_available = await latest_job_for_status(session)
    pending_commands, pending_available = await bot_command_count(session, "pending")
    running_commands, running_available = await bot_command_count(session, "running")
    return {
        "mode": "shared_database",
        "latest_job": JobRunRead.model_validate(latest_job).model_dump() if latest_job else None,
        "latest_job_available": latest_job_available,
        "pending_commands": pending_commands,
        "running_commands": running_commands,
        "command_queue_available": pending_available and running_available,
    }


@app.get("/jobs/runs", response_model=ListEnvelope[JobRunRead])
async def job_runs(
    session: SessionDep,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    name: str | None = None,
) -> ListEnvelope[JobRunRead]:
    stmt = select(JobRun).order_by(JobRun.started_at.desc())
    if name:
        stmt = stmt.where(JobRun.job_name == name)
    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return ListEnvelope(items=[JobRunRead.model_validate(row) for row in rows], total=total)


@app.get("/sources", response_model=ListEnvelope[SourceRead])
async def list_sources(
    session: SessionDep,
    enabled: bool | None = None,
) -> ListEnvelope[SourceRead]:
    stmt = select(NewsSource).order_by(NewsSource.name.asc())
    if enabled is not None:
        stmt = stmt.where(NewsSource.enabled.is_(enabled))
    rows = list((await session.scalars(stmt)).all())
    return ListEnvelope(items=[SourceRead.model_validate(row) for row in rows], total=len(rows))


@app.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate,
    session: SessionDep,
) -> SourceRead:
    source = NewsSource(
        name=payload.name,
        url=str(payload.url),
        region=payload.region,
        category=payload.category,
        source_type=payload.source_type,
        language=payload.language,
        source_score=payload.source_score,
        polling_interval_seconds=payload.polling_interval_seconds,
        asset_classes=[payload.category],
        enabled=payload.enabled,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return SourceRead.model_validate(source)


@app.patch("/sources/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: str,
    payload: SourceUpdate,
    session: SessionDep,
) -> SourceRead:
    source = await session.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(source, key, str(value) if key == "url" else value)
    if "category" in updates:
        source.asset_classes = [source.category]
    await session.commit()
    await session.refresh(source)
    return SourceRead.model_validate(source)


@app.post("/sources/{source_id}/enable", response_model=SourceRead)
async def enable_source(
    source_id: str, session: SessionDep
) -> SourceRead:
    return await set_source_enabled(source_id, True, session)


@app.post("/sources/{source_id}/disable", response_model=SourceRead)
async def disable_source(
    source_id: str, session: SessionDep
) -> SourceRead:
    return await set_source_enabled(source_id, False, session)


async def set_source_enabled(
    source_id: str,
    enabled: bool,
    session: AsyncSession,
) -> SourceRead:
    source = await session.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.enabled = enabled
    await session.commit()
    await session.refresh(source)
    return SourceRead.model_validate(source)


@app.get("/events", response_model=ListEnvelope[EventRead])
async def list_events(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = None,
) -> ListEnvelope[EventRead]:
    stmt = select(EventCluster).order_by(
        EventCluster.final_score.desc(), EventCluster.created_at.desc()
    )
    if status_filter:
        stmt = stmt.where(EventCluster.status == status_filter)
    if q:
        stmt = stmt.where(EventCluster.canonical_headline.ilike(f"%{q}%"))
    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return ListEnvelope(items=[EventRead.model_validate(row) for row in rows], total=total)


@app.get("/events/{event_id}")
async def get_event(
    event_id: str,
    session: SessionDep,
) -> dict[str, object]:
    event = await session.get(EventCluster, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    latest_alert = await session.scalar(
        select(AlertDecision)
        .where(AlertDecision.event_cluster_id == event.id)
        .order_by(AlertDecision.created_at.desc())
        .limit(1)
    )
    latest_investigation = await session.scalar(
        select(AgentInvestigation)
        .where(AgentInvestigation.target_type == "event_cluster")
        .where(AgentInvestigation.target_id == event.id)
        .order_by(AgentInvestigation.created_at.desc())
        .limit(1)
    )
    score_history = list(
        (
            await session.scalars(
                select(EventScoreHistory)
                .where(EventScoreHistory.event_cluster_id == event.id)
                .order_by(EventScoreHistory.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    return {
        **EventRead.model_validate(event).model_dump(),
        "latest_alert": (
            AlertRead(
                **latest_alert.__dict__,
                event={"id": event.id, "headline": event.canonical_headline},
            ).model_dump()
            if latest_alert
            else None
        ),
        "latest_investigation": (
            {
                "id": latest_investigation.id,
                "status": latest_investigation.status,
                "trigger_reason": latest_investigation.trigger_reason,
                "result": latest_investigation.result,
                "error_message": latest_investigation.error_message,
                "created_at": latest_investigation.created_at,
            }
            if latest_investigation
            else None
        ),
        "score_history": [
            {
                "id": row.id,
                "final_score": row.final_score,
                "score_breakdown": row.score_breakdown,
                "created_at": row.created_at,
            }
            for row in score_history
        ],
    }


@app.get("/news", response_model=ListEnvelope[NewsRead])
async def list_news(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = None,
) -> ListEnvelope[NewsRead]:
    stmt = select(NormalizedNewsItem).order_by(NormalizedNewsItem.created_at.desc())
    if status_filter:
        stmt = stmt.where(NormalizedNewsItem.processing_status == status_filter)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                NormalizedNewsItem.title.ilike(pattern),
                NormalizedNewsItem.snippet.ilike(pattern),
                NormalizedNewsItem.url.ilike(pattern),
            )
        )
    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return ListEnvelope(items=[NewsRead.model_validate(row) for row in rows], total=total)


@app.get("/news/{news_id}")
async def get_news(
    news_id: str,
    session: SessionDep,
) -> dict[str, object]:
    item = await session.get(NormalizedNewsItem, news_id)
    if item is None:
        raise HTTPException(status_code=404, detail="News item not found")
    entities = list(
        (
            await session.scalars(
                select(NewsEntity)
                .where(NewsEntity.news_item_id == item.id)
                .order_by(NewsEntity.confidence.desc())
            )
        ).all()
    )
    clusters = list(
        (
            await session.scalars(
                select(EventClusterItem).where(EventClusterItem.news_item_id == item.id)
            )
        ).all()
    )
    return {
        **NewsRead.model_validate(item).model_dump(),
        "entities": [EntityRead.model_validate(entity).model_dump() for entity in entities],
        "clusters": [
            {
                "event_cluster_id": row.event_cluster_id,
                "relation_type": row.relation_type,
                "similarity_score": row.similarity_score,
                "added_at": row.added_at,
            }
            for row in clusters
        ],
    }


@app.get("/alerts", response_model=ListEnvelope[AlertRead])
async def list_alerts(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    level: str | None = None,
) -> ListEnvelope[AlertRead]:
    stmt = (
        select(AlertDecision, EventCluster)
        .join(EventCluster, EventCluster.id == AlertDecision.event_cluster_id)
        .order_by(AlertDecision.created_at.desc())
    )
    if level:
        stmt = stmt.where(AlertDecision.decision == level)
    total = await count_for(session, stmt)
    rows = list((await session.execute(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return ListEnvelope(
        items=[
            AlertRead(
                **alert.__dict__,
                event={
                    "id": event.id,
                    "headline": event.canonical_headline,
                    "final_score": event.final_score,
                    "status": event.status,
                },
            )
            for alert, event in rows
        ],
        total=total,
    )


@app.get("/alerts/{alert_id}", response_model=AlertRead)
async def get_alert(
    alert_id: str,
    session: SessionDep,
) -> AlertRead:
    row = (
        await session.execute(
            select(AlertDecision, EventCluster)
            .join(EventCluster, EventCluster.id == AlertDecision.event_cluster_id)
            .where(AlertDecision.id == alert_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert, event = row
    delivery = await session.scalar(
        select(AlertDelivery)
        .where(AlertDelivery.alert_decision_id == alert.id)
        .order_by(AlertDelivery.created_at.desc())
        .limit(1)
    )
    return AlertRead(
        **alert.__dict__,
        event={
            "id": event.id,
            "headline": event.canonical_headline,
            "final_score": event.final_score,
        },
        latest_delivery_status=delivery.status if delivery else None,
        latest_delivery_error=delivery.error_message if delivery else None,
    )


@app.get("/digests/preview", response_model=ListEnvelope[EventRead])
async def digest_preview(
    session: SessionDep,
    limit: int = Query(20, ge=1, le=100),
) -> ListEnvelope[EventRead]:
    stmt = (
        select(EventCluster)
        .where(EventCluster.final_score >= 30)
        .where(EventCluster.status.notin_(["stale", "false_signal", "merged"]))
        .order_by(EventCluster.final_score.desc(), EventCluster.last_updated_at.desc())
        .limit(limit)
    )
    rows = list((await session.scalars(stmt)).all())
    return ListEnvelope(items=[EventRead.model_validate(row) for row in rows], total=len(rows))


@app.get("/market/moves")
async def market_moves(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, object]:
    rows = list(
        (
            await session.scalars(
                select(MarketMove).order_by(MarketMove.timestamp.desc()).limit(limit)
            )
        ).all()
    )
    return {"items": [row.__dict__ for row in rows], "total": len(rows)}


@app.get("/investigations")
async def investigations(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, object]:
    rows = list(
        (
            await session.scalars(
                select(AgentInvestigation).order_by(AgentInvestigation.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return {"items": [row.__dict__ for row in rows], "total": len(rows)}


@app.get("/watchlist", response_model=ListEnvelope[WatchlistRead])
async def list_watchlist(
    session: SessionDep,
) -> ListEnvelope[WatchlistRead]:
    rows = list(
        (await session.scalars(select(WatchlistEntity).order_by(WatchlistEntity.name.asc()))).all()
    )
    return ListEnvelope(items=[WatchlistRead.model_validate(row) for row in rows], total=len(rows))


@app.post("/watchlist", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    payload: WatchlistCreate,
    session: SessionDep,
) -> WatchlistRead:
    entry = WatchlistEntity(**payload.model_dump())
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return WatchlistRead.model_validate(entry)


@app.patch("/watchlist/{entry_id}", response_model=WatchlistRead)
async def update_watchlist(
    entry_id: str,
    payload: WatchlistUpdate,
    session: SessionDep,
) -> WatchlistRead:
    entry = await session.get(WatchlistEntity, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    await session.commit()
    await session.refresh(entry)
    return WatchlistRead.model_validate(entry)


@app.delete("/watchlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    entry_id: str,
    session: SessionDep,
) -> None:
    entry = await session.get(WatchlistEntity, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    await session.delete(entry)
    await session.commit()


@app.get("/settings/alert-policy", response_model=AlertPolicy)
async def get_alert_policy(session: SessionDep) -> AlertPolicy:
    setting = await session.get(AppSetting, "alert_policy")
    if setting is None:
        return AlertPolicy()
    return AlertPolicy.model_validate(setting.value)


@app.patch("/settings/alert-policy", response_model=AlertPolicy)
async def update_alert_policy(
    payload: AlertPolicy,
    session: SessionDep,
) -> AlertPolicy:
    setting = await session.get(AppSetting, "alert_policy")
    if setting is None:
        setting = AppSetting(key="alert_policy", value=payload.model_dump())
        session.add(setting)
    else:
        setting.value = payload.model_dump()
    await session.commit()
    return payload


@app.post("/bot/commands", response_model=BotCommandRead, status_code=status.HTTP_201_CREATED)
async def create_bot_command(
    payload: BotCommandCreate,
    session: SessionDep,
) -> BotCommandRead:
    if payload.command_type not in ALLOWED_COMMAND_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported bot command")
    command = BotCommand(
        command_type=payload.command_type,
        payload=payload.payload,
        requested_by=payload.requested_by,
    )
    session.add(command)
    await session.commit()
    await session.refresh(command)
    return BotCommandRead.model_validate(command)


@app.get("/bot/commands", response_model=ListEnvelope[BotCommandRead])
async def list_bot_commands(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> ListEnvelope[BotCommandRead]:
    try:
        rows = list(
            (
                await session.scalars(
                    select(BotCommand).order_by(BotCommand.created_at.desc()).limit(limit)
                )
            ).all()
        )
    except SQLAlchemyError:
        return ListEnvelope(items=[], total=0)
    return ListEnvelope(items=[BotCommandRead.model_validate(row) for row in rows], total=len(rows))


@app.get("/bot/commands/{command_id}", response_model=BotCommandRead)
async def get_bot_command(
    command_id: str,
    session: SessionDep,
) -> BotCommandRead:
    command = await session.get(BotCommand, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Bot command not found")
    return BotCommandRead.model_validate(command)


@app.post("/bot/commands/{command_id}/cancel", response_model=BotCommandRead)
async def cancel_bot_command(
    command_id: str,
    session: SessionDep,
) -> BotCommandRead:
    command = await session.get(BotCommand, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Bot command not found")
    if command.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending commands can be cancelled")
    command.status = "cancelled"
    command.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(command)
    return BotCommandRead.model_validate(command)


@app.get("/source-fetch-logs")
async def source_fetch_logs(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, object]:
    rows = list(
        (
            await session.scalars(
                select(SourceFetchLog).order_by(SourceFetchLog.fetched_at.desc()).limit(limit)
            )
        ).all()
    )
    return {"items": [row.__dict__ for row in rows], "total": len(rows)}


@app.get("/score-history/{event_id}")
async def score_history(
    event_id: str,
    session: SessionDep,
) -> dict[str, object]:
    rows = list(
        (
            await session.scalars(
                select(EventScoreHistory)
                .where(EventScoreHistory.event_cluster_id == event_id)
                .order_by(EventScoreHistory.created_at.desc())
            )
        ).all()
    )
    return {"items": [row.__dict__ for row in rows], "total": len(rows)}
