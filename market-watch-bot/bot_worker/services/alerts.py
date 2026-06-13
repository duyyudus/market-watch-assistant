from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.catalysts import (
    MARKET_MOVE_POST_EVENT_WINDOW,
    MARKET_MOVE_PRE_EVENT_WINDOW,
    best_market_move_score_for_event,
)
from bot_worker.db.models import (
    AgentInvestigation,
    AlertDecisionRecord,
    AppSetting,
    EventCluster,
    LLMAnalysisRun,
    MarketMove,
)
from bot_worker.llm import PROMPT_VERSION
from bot_worker.market_data import market_move_draft_from_row
from bot_worker.scoring import (
    AlertThresholds,
    ScoreInput,
    decide_alert,
    market_impact_score,
    score_event,
)
from bot_worker.services.watchlists import tier_for_entities, watchlist_entries


async def alert_thresholds_from_settings(
    session: AsyncSession,
) -> tuple[AlertThresholds, str]:
    result = await session.execute(select(AppSetting).where(AppSetting.key == "alert_policy"))
    setting = result.scalar_one_or_none()
    if setting is None:
        return AlertThresholds(), "log"
    value = setting.value
    if not isinstance(value, Mapping):
        return AlertThresholds(), "log"
    return (
        AlertThresholds(
            immediate=_int_setting(value, "immediate_threshold", 80),
            watchlist=_int_setting(value, "watchlist_threshold", 55),
            digest=_int_setting(value, "digest_threshold", 30),
        ),
        _channel_setting(value),
    )


def _int_setting(value: Mapping[str, object], key: str, default: int) -> int:
    try:
        return int(value.get(key, default))
    except (TypeError, ValueError):
        return default


def _channel_setting(value: Mapping[str, object]) -> str:
    channel = str(value.get("default_channel") or "").strip()
    return channel or "log"


DECISION_RANK = {
    "archive_only": 0,
    "daily_digest": 1,
    "watchlist_batch": 2,
    "immediate_alert": 3,
}
MODEL_MODIFIER_LIMIT = 10
INVESTIGATION_MODIFIER_MIN_CONFIDENCE = 70
ALERT_REEVALUATION_LOOKBACK = timedelta(days=7)


def _clamp(value: int, *, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))


def _result_records(result: Any) -> list[Any]:
    if hasattr(result, "scalars"):
        return list(result.scalars().all())
    rows = result.all()
    records: list[Any] = []
    for row in rows:
        if isinstance(row, tuple):
            records.append(row[0])
        elif hasattr(row, "_mapping") and row._mapping:
            records.append(next(iter(row._mapping.values())))
        else:
            records.append(row)
    return records


async def _latest_alerts_by_cluster(
    session: AsyncSession,
    cluster_ids: list[str],
) -> dict[str, AlertDecisionRecord]:
    if not cluster_ids:
        return {}
    result = await session.execute(
        select(AlertDecisionRecord)
        .where(AlertDecisionRecord.event_cluster_id.in_(cluster_ids))
        .order_by(AlertDecisionRecord.event_cluster_id.asc(), AlertDecisionRecord.created_at.desc())
    )
    latest: dict[str, AlertDecisionRecord] = {}
    for record in _result_records(result):
        if not isinstance(record, AlertDecisionRecord):
            continue
        latest.setdefault(record.event_cluster_id, record)
    return latest


def _candidate_clusters_stmt(now: datetime):
    cutoff = now - ALERT_REEVALUATION_LOOKBACK
    return (
        select(EventCluster)
        .outerjoin(AlertDecisionRecord, AlertDecisionRecord.event_cluster_id == EventCluster.id)
        .where(
            EventCluster.status.not_in(["stale", "merged"]),
            EventCluster.compacted_at.is_(None),
            or_(AlertDecisionRecord.id.is_(None), EventCluster.last_updated_at >= cutoff),
        )
        .distinct()
    )


async def _latest_llm_runs_by_cluster(
    session: AsyncSession,
    cluster_ids: list[str],
) -> dict[str, LLMAnalysisRun]:
    if not cluster_ids:
        return {}
    result = await session.execute(
        select(LLMAnalysisRun)
        .where(
            LLMAnalysisRun.target_type == "event_cluster",
            LLMAnalysisRun.target_id.in_(cluster_ids),
            LLMAnalysisRun.status == "succeeded",
            LLMAnalysisRun.prompt_version == PROMPT_VERSION,
        )
        .order_by(LLMAnalysisRun.target_id.asc(), LLMAnalysisRun.created_at.desc())
    )
    latest: dict[str, LLMAnalysisRun] = {}
    for run in _result_records(result):
        if not isinstance(run, LLMAnalysisRun):
            continue
        latest.setdefault(run.target_id, run)
    return latest


async def _latest_investigations_by_cluster(
    session: AsyncSession,
    cluster_ids: list[str],
) -> dict[str, AgentInvestigation]:
    if not cluster_ids:
        return {}
    result = await session.execute(
        select(AgentInvestigation)
        .where(
            AgentInvestigation.target_type == "event_cluster",
            AgentInvestigation.target_id.in_(cluster_ids),
            AgentInvestigation.status == "succeeded",
        )
        .order_by(AgentInvestigation.target_id.asc(), AgentInvestigation.created_at.desc())
    )
    latest: dict[str, AgentInvestigation] = {}
    for investigation in _result_records(result):
        if not isinstance(investigation, AgentInvestigation):
            continue
        latest.setdefault(investigation.target_id, investigation)
    return latest


async def _market_move_scores_by_cluster(
    session: AsyncSession,
    clusters: list[EventCluster],
) -> dict[str, int | None]:
    cluster_symbols = {
        cluster.id: sorted(
            {
                value
                for value in [*(cluster.affected_tickers or []), *(cluster.affected_entities or [])]
                if value
            }
        )
        for cluster in clusters
    }
    symbols = sorted({symbol for values in cluster_symbols.values() for symbol in values})
    if not clusters or not symbols:
        return {cluster.id: None for cluster in clusters}
    start_at = min(cluster.created_at for cluster in clusters) - MARKET_MOVE_PRE_EVENT_WINDOW
    end_at = max(cluster.created_at for cluster in clusters) + MARKET_MOVE_POST_EVENT_WINDOW
    result = await session.execute(
        select(MarketMove).where(
            MarketMove.asset_symbol.in_(symbols),
            MarketMove.timestamp >= start_at,
            MarketMove.timestamp <= end_at,
        )
    )
    moves_by_symbol: dict[str, list[Any]] = {symbol: [] for symbol in symbols}
    for row in _result_records(result):
        if isinstance(row, MarketMove) and row.asset_symbol in moves_by_symbol:
            moves_by_symbol[row.asset_symbol].append(market_move_draft_from_row(row))
    scores: dict[str, int | None] = {}
    for cluster in clusters:
        cluster_moves = [
            move
            for symbol in cluster_symbols[cluster.id]
            for move in moves_by_symbol.get(symbol, [])
        ]
        if not cluster_moves:
            scores[cluster.id] = None
        else:
            scores[cluster.id] = best_market_move_score_for_event(
                affected_tickers=cluster.affected_tickers or [],
                affected_entities=cluster.affected_entities or [],
                event_time=cluster.created_at,
                moves=cluster_moves,
                pre_event_window=MARKET_MOVE_PRE_EVENT_WINDOW,
                post_event_window=MARKET_MOVE_POST_EVENT_WINDOW,
            )
    return scores


def _should_append_decision(
    *,
    latest_alert: AlertDecisionRecord | None,
    new_decision: str,
) -> bool:
    if latest_alert is None:
        return new_decision != "archive_only"
    return DECISION_RANK.get(new_decision, -1) > DECISION_RANK.get(latest_alert.decision, -1)


def _apply_model_modifier(
    *,
    adjusted_final_score: int,
    score_breakdown: dict[str, object],
    deterministic_final_score: int,
    modifier: int,
    used_modifier: int,
) -> tuple[int, int]:
    remaining_positive = MODEL_MODIFIER_LIMIT - max(0, used_modifier)
    remaining_negative = MODEL_MODIFIER_LIMIT + min(0, used_modifier)
    capped = _clamp(
        modifier,
        minimum=-remaining_negative,
        maximum=remaining_positive,
    )
    if capped == 0:
        return adjusted_final_score, used_modifier
    adjusted = min(100, max(0, adjusted_final_score + capped))
    score_breakdown.setdefault("deterministic_final_score", deterministic_final_score)
    score_breakdown["final_score"] = adjusted
    return adjusted, used_modifier + capped


async def record_alert_decisions(session: AsyncSession) -> int:
    clusters = list((await session.scalars(_candidate_clusters_stmt(datetime.now(UTC)))).all())
    thresholds, channel = await alert_thresholds_from_settings(session)
    cluster_ids = [cluster.id for cluster in clusters]
    latest_alerts = await _latest_alerts_by_cluster(session, cluster_ids)
    llm_runs = await _latest_llm_runs_by_cluster(session, cluster_ids)
    investigations = await _latest_investigations_by_cluster(session, cluster_ids)
    market_move_scores = await _market_move_scores_by_cluster(session, clusters)
    watch_entries = await watchlist_entries(session)
    count = 0
    for cluster in clusters:
        move_score = market_move_scores.get(cluster.id)
        score = score_event(
            ScoreInput(
                top_source_score=cluster.top_source_score,
                source_count=cluster.source_count,
                watchlist_tier=tier_for_entities(
                    entities=cluster.affected_entities or [],
                    tickers=cluster.affected_tickers or [],
                    entries=watch_entries,
                ),
                is_duplicate=False,
                is_stale=cluster.status == "stale",
                unique_high_quality_source_count=int(cluster.high_quality_source_count or 0),
                status=cluster.status,
                market_move_score=move_score,
            )
        )
        score_breakdown = asdict(score)
        adjusted_final_score = score.final_score
        used_model_modifier = 0
        llm_run = llm_runs.get(cluster.id)
        if llm_run is not None and llm_run.result:
            modifier = int(llm_run.result.get("score_modifier") or 0)
            adjusted_final_score, used_model_modifier = _apply_model_modifier(
                adjusted_final_score=adjusted_final_score,
                score_breakdown=score_breakdown,
                deterministic_final_score=score.final_score,
                modifier=modifier,
                used_modifier=used_model_modifier,
            )
            score_breakdown["llm"] = {
                "run_id": llm_run.id,
                "summary": llm_run.result.get("summary"),
                "event_type": llm_run.result.get("event_type"),
                "status_assessment": llm_run.result.get("status_assessment"),
                "confidence": llm_run.result.get("confidence"),
                "impact_rationale": llm_run.result.get("impact_rationale"),
                "why_it_matters": llm_run.result.get("why_it_matters"),
                "alert_message": llm_run.result.get("alert_message"),
                "risk_flags": llm_run.result.get("risk_flags", []),
                "score_modifier": _clamp(
                    modifier, minimum=-MODEL_MODIFIER_LIMIT, maximum=MODEL_MODIFIER_LIMIT
                ),
                "modifier_reason": llm_run.result.get("modifier_reason"),
            }
        investigation = investigations.get(cluster.id)
        if investigation is not None and investigation.result:
            modifier = int(investigation.result.get("suggested_score_modifier") or 0)
            confidence = int(investigation.result.get("confidence") or 0)
            if confidence >= INVESTIGATION_MODIFIER_MIN_CONFIDENCE:
                adjusted_final_score, used_model_modifier = _apply_model_modifier(
                    adjusted_final_score=adjusted_final_score,
                    score_breakdown=score_breakdown,
                    deterministic_final_score=score.final_score,
                    modifier=modifier,
                    used_modifier=used_model_modifier,
                )
            score_breakdown["investigation"] = {
                "run_id": investigation.id,
                "summary": investigation.result.get("summary"),
                "confidence": confidence,
                "official_confirmation": investigation.result.get("official_confirmation"),
                "risk_flags": investigation.result.get("risk_flags", []),
                "suggested_score_modifier": _clamp(
                    modifier, minimum=-MODEL_MODIFIER_LIMIT, maximum=MODEL_MODIFIER_LIMIT
                ),
                "suggested_alert_level": investigation.result.get("suggested_alert_level"),
                "caveats": investigation.result.get("caveats", []),
            }
        cluster.confirmation_score = score.confidence_score
        cluster.novelty_score = score.novelty_score
        cluster.urgency_score = score.urgency_score
        cluster.market_impact_score = market_impact_score(score)
        cluster.relevance_score = score.relevance_score
        cluster.final_score = adjusted_final_score
        decision = decide_alert(adjusted_final_score, thresholds)
        latest_alert = latest_alerts.get(cluster.id)
        # Alert history is append-only for escalations; lower/same-tier recalculations update
        # the cluster but do not create downgrade notifications.
        if not _should_append_decision(latest_alert=latest_alert, new_decision=decision.decision):
            continue
        session.add(
            AlertDecisionRecord(
                event_cluster_id=cluster.id,
                decision=decision.decision,
                reason=decision.reason,
                score_breakdown=score_breakdown,
                channel=channel,
            )
        )
        count += 1
    return count
