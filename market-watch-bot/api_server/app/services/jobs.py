from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.services.query import apply_pagination, count_for
from common.db.models import JobRun


async def list_job_runs(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    name: str | None,
) -> tuple[list[JobRun], int]:
    stmt = select(JobRun).order_by(JobRun.started_at.desc())
    if name:
        stmt = stmt.where(JobRun.job_name == name)
    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total
