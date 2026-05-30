from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import SessionDep
from app.schemas import BotCommandCreate, BotCommandRead, ListEnvelope
from app.services import bot as bot_service

router = APIRouter()


@router.get("/bot/status")
async def bot_status(session: SessionDep) -> dict[str, object]:
    return await bot_service.get_bot_status(session)


@router.post("/bot/commands", response_model=BotCommandRead, status_code=status.HTTP_201_CREATED)
async def create_bot_command(
    payload: BotCommandCreate,
    session: SessionDep,
) -> BotCommandRead:
    try:
        command = await bot_service.create_bot_command(session, payload)
    except SQLAlchemyError as err:
        await session.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                "Command queue unavailable. "
                "Run: cd market-watch-bot && uv run market-watch migrate"
            ),
        ) from err
    return BotCommandRead.model_validate(command)


@router.get("/bot/commands", response_model=ListEnvelope[BotCommandRead])
async def list_bot_commands(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> ListEnvelope[BotCommandRead]:
    rows, available = await bot_service.list_bot_commands(session, limit=limit)
    if not available:
        return ListEnvelope(items=[], total=0)
    return ListEnvelope(items=[BotCommandRead.model_validate(row) for row in rows], total=len(rows))


@router.get("/bot/commands/{command_id}", response_model=BotCommandRead)
async def get_bot_command(
    command_id: str,
    session: SessionDep,
) -> BotCommandRead:
    command = await bot_service.get_bot_command(session, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Bot command not found")
    return BotCommandRead.model_validate(command)


@router.post("/bot/commands/{command_id}/cancel", response_model=BotCommandRead)
async def cancel_bot_command(
    command_id: str,
    session: SessionDep,
) -> BotCommandRead:
    command = await bot_service.get_bot_command(session, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Bot command not found")
    if command.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending commands can be cancelled")
    command = await bot_service.cancel_bot_command(session, command)
    return BotCommandRead.model_validate(command)
