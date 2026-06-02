from __future__ import annotations

from sqlalchemy.engine import make_url

from tests.test_real_database import quote_identifier, server_database_url


def test_server_database_url_targets_postgres_maintenance_database() -> None:
    url = server_database_url(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/market_watch_assistant"
    )

    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.database == "postgres"
    assert parsed.username == "postgres"


def test_server_database_url_normalizes_bare_postgresql_driver() -> None:
    url = server_database_url("postgresql://postgres:postgres@localhost:5432/test_db")

    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.database == "postgres"


def test_quote_identifier_escapes_database_names() -> None:
    assert quote_identifier('test"db') == '"test""db"'
