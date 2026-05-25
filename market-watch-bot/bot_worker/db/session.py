from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot_worker.config import Settings


def make_engine(settings: Settings):
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def make_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(make_engine(settings), expire_on_commit=False)


async def session_scope(settings: Settings) -> AsyncIterator[AsyncSession]:
    factory = make_session_factory(settings)
    async with factory() as session, session.begin():
        yield session
