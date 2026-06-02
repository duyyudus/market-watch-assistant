from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from bot_worker.services.bot_commands import claim_pending_bot_command
from common.db.models import AppSetting, BotCommand

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_DB_TESTS") != "1",
    reason="set RUN_REAL_DB_TESTS=1 to run real PostgreSQL integration tests",
)


def real_database_url() -> str:
    env_file = Path(__file__).parents[1] / ".env.test"
    values = dotenv_values(env_file) if env_file.exists() else {}
    url = os.environ.get("DATABASE_URL") or values.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required in environment or market-watch-bot/.env.test")
    if not url.startswith(("postgresql+asyncpg://", "postgresql://")):
        pytest.skip("real database tests require a PostgreSQL DATABASE_URL")
    return normalize_asyncpg_url(url)


def normalize_asyncpg_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+asyncpg")
    return parsed.render_as_string(hide_password=False)


def target_database_name(url: str) -> str:
    database = make_url(url).database
    if not database:
        pytest.skip("real database tests require DATABASE_URL to include a database name")
    return database


def server_database_url(url: str) -> str:
    parsed = make_url(normalize_asyncpg_url(url))
    return parsed.set(database="postgres").render_as_string(hide_password=False)


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def ensure_database_exists(url: str) -> None:
    database = target_database_name(url)
    engine = create_async_engine(
        server_database_url(url),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": database},
            )
            if exists:
                return
            await connection.execute(text(f"CREATE DATABASE {quote_identifier(database)}"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    url = real_database_url()
    asyncio.run(ensure_database_exists(url))
    os.environ["DATABASE_URL"] = url
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    return url


@pytest.fixture()
async def real_session_factory(migrated_database_url: str):
    engine = create_async_engine(migrated_database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM bot_commands WHERE requested_by = 'real-db-test'"))
            await conn.execute(text("DELETE FROM app_settings WHERE key LIKE 'real_db_test_%'"))
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM bot_commands WHERE requested_by = 'real-db-test'"))
            await conn.execute(text("DELETE FROM app_settings WHERE key LIKE 'real_db_test_%'"))
        await engine.dispose()


def test_alembic_upgrade_head_runs_against_real_database(migrated_database_url: str) -> None:
    assert migrated_database_url.startswith(("postgresql+asyncpg://", "postgresql://"))


@pytest.mark.asyncio
async def test_pgvector_extension_supports_vector_distance(real_session_factory) -> None:
    async with real_session_factory() as session:
        distance = await session.scalar(
            text("SELECT '[1,0,0]'::vector <=> '[1,0,0]'::vector")
        )

    assert float(distance or 0) == 0.0


@pytest.mark.asyncio
async def test_bot_command_claim_uses_skip_locked(real_session_factory) -> None:
    async with real_session_factory() as session:
        session.add_all(
            [
                BotCommand(
                    id="cmd_real_db_1",
                    command_type="pipeline.run",
                    payload={"dry_run": True},
                    requested_by="real-db-test",
                ),
                BotCommand(
                    id="cmd_real_db_2",
                    command_type="pipeline.run",
                    payload={"dry_run": True},
                    requested_by="real-db-test",
                ),
            ]
        )
        await session.commit()

    async with (
        real_session_factory() as session_one,
        real_session_factory() as session_two,
        session_one.begin(),
        session_two.begin(),
    ):
        first = await claim_pending_bot_command(session_one)
        second = await claim_pending_bot_command(session_two)

        assert first is not None
        assert second is not None
        assert first.id != second.id


@pytest.mark.asyncio
async def test_jsonb_boolean_path_queries_match_postgresql_behavior(real_session_factory) -> None:
    async with real_session_factory() as session:
        session.add(
            AppSetting(
                key="real_db_test_jsonb",
                value={"nested": {"enabled": True}, "labels": ["pg", "jsonb"]},
            )
        )
        await session.commit()

    async with real_session_factory() as session:
        found = await session.scalar(
            select(AppSetting).where(AppSetting.value["nested"]["enabled"].as_boolean().is_(True))
        )

    assert found is not None
    assert found.key == "real_db_test_jsonb"
