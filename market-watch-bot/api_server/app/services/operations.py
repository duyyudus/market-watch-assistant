from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import AgentInvestigation, MarketMove


async def list_market_moves(session: AsyncSession, *, limit: int) -> tuple[list[MarketMove], int]:
    rows = list(
        (
            await session.scalars(
                select(MarketMove).order_by(MarketMove.timestamp.desc()).limit(limit)
            )
        ).all()
    )
    return rows, len(rows)


async def list_investigations(
    session: AsyncSession, *, limit: int
) -> tuple[list[AgentInvestigation], int]:
    rows = list(
        (
            await session.scalars(
                select(AgentInvestigation).order_by(AgentInvestigation.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return rows, len(rows)
