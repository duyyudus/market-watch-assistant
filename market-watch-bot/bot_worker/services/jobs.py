from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    JobRun,
)


async def record_job_run(session: AsyncSession, job_name: str, result: dict[str, object]) -> JobRun:
    run = JobRun(
        job_name=job_name,
        status="success",
        completed_at=datetime.now(UTC),
        result=result,
    )
    session.add(run)
    await session.flush()
    return run
