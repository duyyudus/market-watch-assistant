from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import BotCommandCreate, JobRunRead
from common.db.models import AppSetting, BotCommand, JobRun

WORKER_HEARTBEAT_KEY = "worker.heartbeat"
WORKER_HEARTBEAT_STALE_AFTER = timedelta(seconds=60)


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


def _parse_heartbeat_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def worker_heartbeat_status(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[str, object]:
    if not hasattr(session, "get"):
        return {
            "worker_heartbeat_available": False,
            "worker_running": None,
            "worker_last_seen_at": None,
        }
    try:
        setting = await session.get(AppSetting, WORKER_HEARTBEAT_KEY)
    except SQLAlchemyError:
        await session.rollback()
        return {
            "worker_heartbeat_available": False,
            "worker_running": None,
            "worker_last_seen_at": None,
        }
    if setting is None or not isinstance(setting.value, dict):
        return {
            "worker_heartbeat_available": True,
            "worker_running": False,
            "worker_last_seen_at": None,
        }
    raw_last_seen = setting.value.get("last_seen_at")
    last_seen_at = _parse_heartbeat_timestamp(raw_last_seen)
    if last_seen_at is None:
        return {
            "worker_heartbeat_available": True,
            "worker_running": False,
            "worker_last_seen_at": raw_last_seen if isinstance(raw_last_seen, str) else None,
        }
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        "worker_heartbeat_available": True,
        "worker_running": current - last_seen_at <= WORKER_HEARTBEAT_STALE_AFTER,
        "worker_last_seen_at": raw_last_seen,
    }


async def get_bot_status(session: AsyncSession) -> dict[str, object]:
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
        **await worker_heartbeat_status(session),
    }


async def create_bot_command(session: AsyncSession, payload: BotCommandCreate) -> BotCommand:
    command = BotCommand(
        command_type=payload.command_type,
        payload=payload.payload,
        requested_by=payload.requested_by,
    )
    session.add(command)
    await session.flush()
    await session.refresh(command)
    return command


async def list_bot_commands(session: AsyncSession, *, limit: int) -> tuple[list[BotCommand], bool]:
    try:
        rows = list(
            (
                await session.scalars(
                    select(BotCommand).order_by(BotCommand.created_at.desc()).limit(limit)
                )
            ).all()
        )
    except SQLAlchemyError:
        await session.rollback()
        return [], False
    return rows, True


async def get_bot_command(session: AsyncSession, command_id: str) -> BotCommand | None:
    return await session.get(BotCommand, command_id)


async def cancel_bot_command(session: AsyncSession, command: BotCommand) -> BotCommand:
    command.status = "cancelled"
    command.completed_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(command)
    return command
