from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.config import Settings, load_settings
from common.db.session import make_engine, make_session_factory


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = load_settings()
        request.app.state.settings = settings
    return settings


def get_engine(request: Request):
    return make_engine(get_settings(request))


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "session_factory", None)
    settings = get_settings(request)
    if factory is None:
        factory = make_session_factory(settings)
        request.app.state.session_factory = factory
    return factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_session_factory(request)() as session:
        yield session
