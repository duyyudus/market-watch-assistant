from __future__ import annotations

from datetime import datetime, timedelta

from bot_worker.market_data import MarketMoveDraft, score_market_move

MARKET_MOVE_PRE_EVENT_WINDOW = timedelta(hours=24)
MARKET_MOVE_POST_EVENT_WINDOW = timedelta(hours=4)


def event_matches_market_move(
    *,
    affected_tickers: list[str],
    affected_entities: list[str],
    event_time: datetime,
    move: MarketMoveDraft,
    pre_event_window: timedelta = MARKET_MOVE_PRE_EVENT_WINDOW,
    post_event_window: timedelta = MARKET_MOVE_POST_EVENT_WINDOW,
) -> bool:
    symbols = {value.casefold() for value in [*affected_tickers, *affected_entities]}
    if move.asset_symbol.casefold() not in symbols:
        return False
    return event_time - pre_event_window <= move.timestamp <= event_time + post_event_window


def catalyst_review_needed(*, price_move_score: int, has_matching_event: bool) -> bool:
    return price_move_score >= 70 and not has_matching_event


def best_market_move_score_for_event(
    *,
    affected_tickers: list[str],
    affected_entities: list[str],
    event_time: datetime,
    moves: list[MarketMoveDraft],
    pre_event_window: timedelta = MARKET_MOVE_PRE_EVENT_WINDOW,
    post_event_window: timedelta = MARKET_MOVE_POST_EVENT_WINDOW,
) -> int:
    best = 0
    for move in moves:
        if not event_matches_market_move(
            affected_tickers=affected_tickers,
            affected_entities=affected_entities,
            event_time=event_time,
            move=move,
            pre_event_window=pre_event_window,
            post_event_window=post_event_window,
        ):
            continue
        best = max(
            best,
            score_market_move(
                price_change_pct=move.price_change_pct,
                volume_change_pct=move.volume_change_pct,
                z_score=move.z_score,
            ),
        )
    return best
