from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from common.config import Settings

_ENGINES: dict[str, AsyncEngine] = {}
_SESSION_FACTORIES: dict[str, async_sessionmaker[AsyncSession]] = {}


def make_engine(settings: Settings) -> AsyncEngine:
    engine = _ENGINES.get(settings.database_url)
    if engine is None:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _ENGINES[settings.database_url] = engine
    return engine


def make_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    factory = _SESSION_FACTORIES.get(settings.database_url)
    if factory is None:
        factory = async_sessionmaker(make_engine(settings), expire_on_commit=False)
        _SESSION_FACTORIES[settings.database_url] = factory
    return factory


def pool_metrics(engine: AsyncEngine) -> dict[str, int | None]:
    pool = engine.sync_engine.pool
    return {
        "pool_size": _pool_value(pool, "size"),
        "checked_out": _pool_value(pool, "checkedout"),
        "overflow": _pool_value(pool, "overflow"),
    }


def _pool_value(pool: object, name: str) -> int | None:
    value = getattr(pool, name, None)
    if value is None:
        return None
    if callable(value):
        try:
            return int(value())
        except (NotImplementedError, TypeError):
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def session_scope(settings: Settings) -> AsyncIterator[AsyncSession]:
    factory = make_session_factory(settings)
    async with factory() as session, session.begin():
        yield session
