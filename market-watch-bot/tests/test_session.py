from __future__ import annotations

from bot_worker.config import Settings
from bot_worker.db.session import make_engine, make_session_factory, pool_metrics


def test_make_engine_reuses_cached_engine_for_same_database_url() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    first = make_engine(settings)
    second = make_engine(settings)

    assert first is second


def test_make_session_factory_reuses_cached_factory_for_same_database_url() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    first = make_session_factory(settings)
    second = make_session_factory(settings)

    assert first is second


def test_pool_metrics_returns_stable_keys() -> None:
    engine = make_engine(Settings(database_url="sqlite+aiosqlite:///:memory:"))

    metrics = pool_metrics(engine)

    assert set(metrics) == {"pool_size", "checked_out", "overflow"}
