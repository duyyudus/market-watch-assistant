from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import SessionDep
from app.schemas import AlertRead, ListEnvelope
from app.services import alerts as alert_service

router = APIRouter()


@router.get("/alerts", response_model=ListEnvelope[AlertRead])
async def list_alerts(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    level: str | None = None,
) -> ListEnvelope[AlertRead]:
    rows, total = await alert_service.list_alerts(
        session, limit=limit, offset=offset, level=level
    )
    return ListEnvelope(items=rows, total=total)


@router.get("/alerts/{alert_id}", response_model=AlertRead)
async def get_alert(
    alert_id: str,
    session: SessionDep,
) -> AlertRead:
    alert = await alert_service.get_alert_detail(session, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert
