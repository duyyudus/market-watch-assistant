from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot_worker.catalysts import (
    best_market_move_score_for_event,
    catalyst_review_needed,
    event_matches_market_move,
)
from bot_worker.db.models import Base, MissedCatalystReview
from bot_worker.market_data import MarketMoveDraft
from bot_worker.services.market import expire_stale_missed_catalyst_reviews


def test_event_matches_market_move_by_ticker_and_window() -> None:
    move = MarketMoveDraft(
        asset_symbol="BTC",
        asset_class="crypto",
        exchange=None,
        timestamp=datetime(2026, 5, 25, 10, tzinfo=UTC),
        window="1d",
        price_change_pct=7.0,
    )

    assert event_matches_market_move(
        affected_tickers=["BTC"],
        affected_entities=[],
        event_time=datetime(2026, 5, 25, 8, tzinfo=UTC),
        move=move,
        post_event_window=timedelta(hours=12),
    )
    assert not event_matches_market_move(
        affected_tickers=["ETH"],
        affected_entities=[],
        event_time=datetime(2026, 5, 23, 8, tzinfo=UTC),
        move=move,
        post_event_window=timedelta(hours=12),
    )


def test_event_matches_market_move_rejects_pre_event_moves() -> None:
    move = MarketMoveDraft(
        asset_symbol="BTC",
        asset_class="crypto",
        exchange=None,
        timestamp=datetime(2026, 5, 25, 7, 59, tzinfo=UTC),
        window="1d",
        price_change_pct=7.0,
    )

    assert event_matches_market_move(
        affected_tickers=["BTC"],
        affected_entities=[],
        event_time=datetime(2026, 5, 25, 8, tzinfo=UTC),
        move=move,
        pre_event_window=timedelta(hours=1),
        post_event_window=timedelta(hours=4),
    )


def test_event_matches_market_move_rejects_moves_before_pre_event_window() -> None:
    move = MarketMoveDraft(
        asset_symbol="BTC",
        asset_class="crypto",
        exchange=None,
        timestamp=datetime(2026, 5, 25, 6, 59, tzinfo=UTC),
        window="1d",
        price_change_pct=7.0,
    )

    assert not event_matches_market_move(
        affected_tickers=["BTC"],
        affected_entities=[],
        event_time=datetime(2026, 5, 25, 8, tzinfo=UTC),
        move=move,
        pre_event_window=timedelta(hours=1),
        post_event_window=timedelta(hours=4),
    )


def test_catalyst_review_needed_requires_material_unmatched_move() -> None:
    assert catalyst_review_needed(price_move_score=72, has_matching_event=False)
    assert not catalyst_review_needed(price_move_score=72, has_matching_event=True)
    assert not catalyst_review_needed(price_move_score=69, has_matching_event=False)


def test_best_market_move_score_for_event_uses_matching_symbol_only() -> None:
    event_time = datetime(2026, 5, 25, 10, tzinfo=UTC)
    moves = [
        MarketMoveDraft(
            asset_symbol="ETH",
            asset_class="crypto",
            exchange=None,
            timestamp=event_time,
            window="1d",
            price_change_pct=10.0,
        ),
        MarketMoveDraft(
            asset_symbol="BTC",
            asset_class="crypto",
            exchange=None,
            timestamp=event_time,
            window="1d",
            price_change_pct=5.0,
        ),
    ]

    assert (
        best_market_move_score_for_event(
            affected_tickers=["BTC"],
            affected_entities=[],
            event_time=event_time,
            moves=moves,
            pre_event_window=timedelta(hours=1),
            post_event_window=timedelta(hours=1),
        )
        >= 70
    )


@pytest.mark.asyncio
async def test_expire_stale_missed_catalyst_reviews_only_expires_old_unresolved_actions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 5, 30, 12, tzinfo=UTC)
    old = now - timedelta(hours=24, minutes=1)
    recent = now - timedelta(hours=23, minutes=59)

    async with factory() as session:
        session.add_all(
            [
                MissedCatalystReview(
                    id="review_old_pending",
                    asset_symbol="AAPL",
                    asset_class="equity",
                    move_window="1d",
                    price_change_pct=-5.2,
                    status="pending",
                    created_at=old,
                ),
                MissedCatalystReview(
                    id="review_old_investigating",
                    asset_symbol="MSFT",
                    asset_class="equity",
                    move_window="1d",
                    price_change_pct=-5.4,
                    status="investigating",
                    created_at=old,
                ),
                MissedCatalystReview(
                    id="review_recent_pending",
                    asset_symbol="NVDA",
                    asset_class="equity",
                    move_window="1d",
                    price_change_pct=-5.0,
                    status="pending",
                    created_at=recent,
                ),
                MissedCatalystReview(
                    id="review_matched_pending",
                    asset_symbol="BTC",
                    asset_class="crypto",
                    move_window="1d",
                    price_change_pct=6.0,
                    detected_event_cluster_id="evt_1",
                    status="pending",
                    created_at=old,
                ),
                MissedCatalystReview(
                    id="review_resolved",
                    asset_symbol="SOL",
                    asset_class="crypto",
                    move_window="1d",
                    price_change_pct=7.0,
                    status="resolved",
                    created_at=old,
                ),
                MissedCatalystReview(
                    id="review_false_signal",
                    asset_symbol="ETH",
                    asset_class="crypto",
                    move_window="1d",
                    price_change_pct=7.0,
                    status="false_signal",
                    created_at=old,
                ),
                MissedCatalystReview(
                    id="review_ignored",
                    asset_symbol="TSLA",
                    asset_class="equity",
                    move_window="1d",
                    price_change_pct=-5.1,
                    status="ignored",
                    created_at=old,
                ),
                MissedCatalystReview(
                    id="review_no_clear_catalyst",
                    asset_symbol="GOOGL",
                    asset_class="equity",
                    move_window="1d",
                    price_change_pct=-5.1,
                    status="no_clear_catalyst",
                    created_at=old,
                ),
            ]
        )
        await session.commit()

        count = await expire_stale_missed_catalyst_reviews(session, now=now)
        await session.commit()

        statuses = {
            review_id: (await session.get(MissedCatalystReview, review_id)).status
            for review_id in [
                "review_old_pending",
                "review_old_investigating",
                "review_recent_pending",
                "review_matched_pending",
                "review_resolved",
                "review_false_signal",
                "review_ignored",
                "review_no_clear_catalyst",
            ]
        }

    await engine.dispose()

    assert count == 2
    assert statuses == {
        "review_old_pending": "expired",
        "review_old_investigating": "expired",
        "review_recent_pending": "pending",
        "review_matched_pending": "pending",
        "review_resolved": "resolved",
        "review_false_signal": "false_signal",
        "review_ignored": "ignored",
        "review_no_clear_catalyst": "no_clear_catalyst",
    }
