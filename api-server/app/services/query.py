from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def count_for(session: AsyncSession, stmt: Select) -> int:
    return int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def apply_pagination(stmt: Select, *, limit: int, offset: int) -> Select:
    return stmt.limit(limit).offset(offset)
