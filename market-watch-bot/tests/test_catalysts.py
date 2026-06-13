from datetime import UTC, datetime, timedelta

from bot_worker.catalysts import (
    best_market_move_score_for_event,
    catalyst_review_needed,
    event_matches_market_move,
)
from bot_worker.market_data import MarketMoveDraft


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
