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
    """Scoring output, including diagnostic fields persisted for API/UI compatibility."""

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


def _noise_multiplier(source_score: int) -> float:
    if source_score <= 40:
        return 0.85
    if source_score >= 55:
        return 1.0
    return 0.85 + ((source_score - 40) / 15) * 0.15


def score_event(input_data: ScoreInput) -> ScoreBreakdown:
    relevance_by_tier = {"S": 100, "A": 90, "B": 75, "C": 55, "D": 35}
    source_score = min(100, max(0, input_data.top_source_score))
    source_count = max(0, input_data.source_count)
    high_quality_source_count = max(0, input_data.unique_high_quality_source_count)
    confidence = min(80, 40 + (source_count * 10))
    if high_quality_source_count >= 1:
        confidence = min(100, confidence + min(15, high_quality_source_count * 5))
    if high_quality_source_count >= 2:
        confidence = max(confidence, 85)
    if input_data.status in {"confirmed", "official"}:
        confidence = max(confidence, 95)
    normalized_tier = (input_data.watchlist_tier or "").strip().upper()
    relevance = relevance_by_tier.get(normalized_tier, relevance_by_tier["D"])
    has_market_move = input_data.market_move_score is not None
    market_move = min(100, max(0, input_data.market_move_score or 0))
    # Diagnostic compatibility fields; final_score is driven by base_score below.
    novelty = 20 if input_data.is_duplicate else 100
    impact = market_move
    if has_market_move:
        urgency = round(relevance * 0.45 + market_move * 0.35 + confidence * 0.20)
        weighted_components = (
            (source_score, 0.25),
            (relevance, 0.35),
            (confidence, 0.25),
            (market_move, 0.15),
        )
    else:
        urgency = round(relevance * 0.65 + confidence * 0.35)
        weighted_components = (
            (source_score, 0.25),
            (relevance, 0.35),
            (confidence, 0.25),
        )
    total_weight = sum(weight for _value, weight in weighted_components)
    base_score = sum(value * weight for value, weight in weighted_components) / total_weight
    adjusted = base_score
    duplicate_penalty = 0
    if input_data.is_duplicate:
        next_score = adjusted * 0.70
        duplicate_penalty = round(adjusted - next_score)
        adjusted = next_score
    stale_penalty = 0
    if input_data.is_stale:
        next_score = adjusted * 0.70
        stale_penalty = round(adjusted - next_score)
        adjusted = next_score
    noise_multiplier = _noise_multiplier(source_score)
    noise_penalty = 0
    if noise_multiplier < 1.0:
        next_score = adjusted * noise_multiplier
        noise_penalty = round(adjusted - next_score)
        adjusted = next_score
    raw = round(adjusted)
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


def market_impact_score(score: ScoreBreakdown) -> int:
    """Return the market move display score kept for persisted/API compatibility."""
    return score.market_move_score


def decide_alert(final_score: int, thresholds: AlertThresholds) -> AlertDecision:
    if final_score >= thresholds.immediate:
        return AlertDecision(decision="immediate_alert", reason="score_above_immediate_threshold")
    if final_score >= thresholds.watchlist:
        return AlertDecision(decision="watchlist_batch", reason="score_above_watchlist_threshold")
    if final_score >= thresholds.digest:
        return AlertDecision(decision="daily_digest", reason="score_above_digest_threshold")
    return AlertDecision(decision="archive_only", reason="score_below_digest_threshold")
