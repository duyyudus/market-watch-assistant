from __future__ import annotations

from datetime import datetime, timedelta

from bot_worker.market_data import MarketMoveDraft, score_market_move


def event_matches_market_move(
    *,
    affected_tickers: list[str],
    affected_entities: list[str],
    event_time: datetime,
    move: MarketMoveDraft,
    tolerance: timedelta,
) -> bool:
    symbols = {value.casefold() for value in [*affected_tickers, *affected_entities]}
    if move.asset_symbol.casefold() not in symbols:
        return False
    return abs(move.timestamp - event_time) <= tolerance


def catalyst_review_needed(*, price_move_score: int, has_matching_event: bool) -> bool:
    return price_move_score >= 70 and not has_matching_event


def best_market_move_score_for_event(
    *,
    affected_tickers: list[str],
    affected_entities: list[str],
    event_time: datetime,
    moves: list[MarketMoveDraft],
    tolerance: timedelta,
) -> int:
    best = 0
    for move in moves:
        if not event_matches_market_move(
            affected_tickers=affected_tickers,
            affected_entities=affected_entities,
            event_time=event_time,
            move=move,
            tolerance=tolerance,
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
