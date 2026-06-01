from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreInput:
    top_source_score: int
    source_count: int
    watchlist_tier: str | None
    is_duplicate: bool
    is_stale: bool
    unique_high_quality_source_count: int = 0
    status: str = "reported"
    market_move_score: int | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    source_score: int
    impact_score: int
    relevance_score: int
    novelty_score: int
    urgency_score: int
    market_move_score: int
    confidence_score: int
    duplicate_penalty: int
    noise_penalty: int
    stale_penalty: int
    final_score: int


@dataclass(frozen=True)
class AlertThresholds:
    immediate: int = 80
    watchlist: int = 55
    digest: int = 30


@dataclass(frozen=True)
class AlertDecision:
    decision: str
    reason: str


def score_event(input_data: ScoreInput) -> ScoreBreakdown:
    relevance_by_tier = {"S": 100, "A": 95, "B": 75, "C": 55, "D": 35}
    source_score = min(100, max(0, input_data.top_source_score))
    confidence = min(95, 45 + (input_data.source_count * 15))
    if input_data.unique_high_quality_source_count >= 2:
        confidence = min(100, max(confidence, 80 + input_data.unique_high_quality_source_count * 5))
    if input_data.status in {"confirmed", "official"}:
        confidence = max(confidence, 90)
    impact = 75 if source_score >= 75 else 55
    relevance = relevance_by_tier.get((input_data.watchlist_tier or "D").upper(), 35)
    novelty = 85 if not input_data.is_duplicate else 20
    urgency = 80 if relevance >= 75 and source_score >= 75 else 45
    market_move = min(100, max(0, input_data.market_move_score or 0))
    duplicate_penalty = 30 if input_data.is_duplicate else 0
    stale_penalty = 25 if input_data.is_stale else 0
    noise_penalty = 10 if source_score < 50 else 0
    raw = round(
        source_score * 0.25
        + impact * 0.20
        + relevance * 0.25
        + novelty * 0.10
        + urgency * 0.10
        + market_move * 0.10
        + confidence * 0.10
        - duplicate_penalty
        - stale_penalty
        - noise_penalty
    )
    if source_score >= 65 and market_move >= 70:
        raw = max(raw, 80)
    return ScoreBreakdown(
        source_score=source_score,
        impact_score=impact,
        relevance_score=relevance,
        novelty_score=novelty,
        urgency_score=urgency,
        market_move_score=market_move,
        confidence_score=confidence,
        duplicate_penalty=duplicate_penalty,
        noise_penalty=noise_penalty,
        stale_penalty=stale_penalty,
        final_score=min(100, max(0, raw)),
    )


def decide_alert(
    final_score: int, thresholds: AlertThresholds, suppression_reason: str | None = None
) -> AlertDecision:
    if suppression_reason:
        return AlertDecision(decision="suppressed", reason=suppression_reason)
    if final_score >= thresholds.immediate:
        return AlertDecision(decision="immediate_alert", reason="score_above_immediate_threshold")
    if final_score >= thresholds.watchlist:
        return AlertDecision(decision="watchlist_batch", reason="score_above_watchlist_threshold")
    if final_score >= thresholds.digest:
        return AlertDecision(decision="daily_digest", reason="score_above_digest_threshold")
    return AlertDecision(decision="archive_only", reason="score_below_digest_threshold")
