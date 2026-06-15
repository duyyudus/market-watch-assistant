from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import (
    AlertChannelCreate,
    AlertChannelRead,
    AlertChannelTestPayload,
    AlertChannelUpdate,
    AlertRead,
    AlertSuppressionRuleCreate,
    AlertSuppressionRuleRead,
    AlertSuppressionRuleUpdate,
    BotCommandRead,
    ListEnvelope,
)
from api_server.app.services import alerts as alert_service

router = APIRouter()


@router.get("/alerts", response_model=ListEnvelope[AlertRead])
async def list_alerts(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    max_items: int | None = Query(None, ge=1),
    decision: str | None = None,
    level: str | None = None,
) -> ListEnvelope[AlertRead]:
    rows, total = await alert_service.list_alerts(
        session,
        limit=limit,
        offset=offset,
        max_items=max_items,
        decision=decision or level,
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


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_alert(alert_id: str, session: SessionDep) -> AlertRead:
    alert = await alert_service.acknowledge_alert(session, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.post("/alerts/{alert_id}/dismiss", response_model=AlertRead)
async def dismiss_alert(alert_id: str, session: SessionDep) -> AlertRead:
    alert = await alert_service.dismiss_alert(session, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("/alert-channels", response_model=ListEnvelope[AlertChannelRead])
async def list_alert_channels(session: SessionDep) -> ListEnvelope[AlertChannelRead]:
    rows, total = await alert_service.list_channels(session)
    return ListEnvelope(items=rows, total=total)


@router.post(
    "/alert-channels",
    response_model=AlertChannelRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert_channel(
    payload: AlertChannelCreate,
    session: SessionDep,
) -> AlertChannelRead:
    try:
        return await alert_service.create_channel(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/alert-channels/{channel_id}", response_model=AlertChannelRead)
async def update_alert_channel(
    channel_id: str,
    payload: AlertChannelUpdate,
    session: SessionDep,
) -> AlertChannelRead:
    try:
        channel = await alert_service.update_channel(session, channel_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if channel is None:
        raise HTTPException(status_code=404, detail="Alert channel not found")
    return channel


@router.delete("/alert-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_channel(channel_id: str, session: SessionDep) -> Response:
    deleted = await alert_service.delete_channel(session, channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert channel not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/alert-channels/{channel_id}/test",
    response_model=BotCommandRead,
    status_code=status.HTTP_201_CREATED,
)
async def test_alert_channel(
    channel_id: str,
    payload: AlertChannelTestPayload,
    session: SessionDep,
) -> BotCommandRead:
    command = await alert_service.queue_channel_test(session, channel_id, payload.message)
    if command is None:
        raise HTTPException(status_code=404, detail="Alert channel not found")
    return command


@router.get("/alert-suppression-rules", response_model=ListEnvelope[AlertSuppressionRuleRead])
async def list_alert_suppression_rules(
    session: SessionDep,
) -> ListEnvelope[AlertSuppressionRuleRead]:
    rows, total = await alert_service.list_suppression_rules(session)
    return ListEnvelope(items=rows, total=total)


@router.post(
    "/alert-suppression-rules",
    response_model=AlertSuppressionRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert_suppression_rule(
    payload: AlertSuppressionRuleCreate,
    session: SessionDep,
) -> AlertSuppressionRuleRead:
    try:
        return await alert_service.create_suppression_rule(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/alert-suppression-rules/{rule_id}", response_model=AlertSuppressionRuleRead)
async def update_alert_suppression_rule(
    rule_id: str,
    payload: AlertSuppressionRuleUpdate,
    session: SessionDep,
) -> AlertSuppressionRuleRead:
    try:
        rule = await alert_service.update_suppression_rule(session, rule_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rule is None:
        raise HTTPException(status_code=404, detail="Suppression rule not found")
    return rule


@router.delete("/alert-suppression-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_suppression_rule(rule_id: str, session: SessionDep) -> Response:
    deleted = await alert_service.delete_suppression_rule(session, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Suppression rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
