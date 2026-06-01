from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    AlertDecisionRecord,
    AppSetting,
    EventCluster,
)
from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event
from bot_worker.services.investigation import latest_successful_investigation
from bot_worker.services.llm import latest_successful_llm_analysis
from bot_worker.services.market import market_move_score_for_cluster
from bot_worker.services.watchlists import tier_for_entities, watchlist_entries


async def alert_thresholds_from_settings(
    session: AsyncSession,
) -> tuple[AlertThresholds, str]:
    if not hasattr(session, "execute"):
        return AlertThresholds(), "log"
    result = await session.execute(select(AppSetting).where(AppSetting.key == "alert_policy"))
    setting = result.scalar_one_or_none()
    if setting is None:
        return AlertThresholds(), "log"
    value = setting.value
    return (
        AlertThresholds(
            immediate=int(value.get("immediate_threshold", 80)),
            watchlist=int(value.get("watchlist_threshold", 55)),
            digest=int(value.get("digest_threshold", 30)),
        ),
        str(value.get("default_channel", "log")),
    )


async def record_alert_decisions(session: AsyncSession) -> int:
    stmt = (
        select(EventCluster)
        .outerjoin(AlertDecisionRecord, AlertDecisionRecord.event_cluster_id == EventCluster.id)
        .where(AlertDecisionRecord.id.is_(None))
    )
    clusters = list((await session.scalars(stmt)).all())
    thresholds, channel = await alert_thresholds_from_settings(session)
    watch_entries = await watchlist_entries(session)
    count = 0
    for cluster in clusters:
        move_score = await market_move_score_for_cluster(session, cluster)
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
        llm_run = await latest_successful_llm_analysis(session, cluster.id)
        if llm_run is not None and llm_run.result:
            modifier = int(llm_run.result.get("score_modifier") or 0)
            adjusted_final_score = min(100, max(0, score.final_score + modifier))
            score_breakdown["deterministic_final_score"] = score.final_score
            score_breakdown["final_score"] = adjusted_final_score
            score_breakdown["llm"] = {
                "run_id": llm_run.id,
                "summary": llm_run.result.get("summary"),
                "event_type": llm_run.result.get("event_type"),
                "status_assessment": llm_run.result.get("status_assessment"),
                "confidence": llm_run.result.get("confidence"),
                "impact_rationale": llm_run.result.get("impact_rationale"),
                "why_it_matters": llm_run.result.get("why_it_matters"),
                "risk_flags": llm_run.result.get("risk_flags", []),
                "score_modifier": modifier,
                "modifier_reason": llm_run.result.get("modifier_reason"),
            }
        else:
            adjusted_final_score = score.final_score
        investigation = await latest_successful_investigation(
            session,
            target_type="event_cluster",
            target_id=cluster.id,
        )
        if investigation is not None and investigation.result:
            modifier = int(investigation.result.get("suggested_score_modifier") or 0)
            adjusted_final_score = min(100, max(0, adjusted_final_score + modifier))
            score_breakdown.setdefault("deterministic_final_score", score.final_score)
            score_breakdown["final_score"] = adjusted_final_score
            score_breakdown["investigation"] = {
                "run_id": investigation.id,
                "summary": investigation.result.get("summary"),
                "confidence": investigation.result.get("confidence"),
                "official_confirmation": investigation.result.get("official_confirmation"),
                "risk_flags": investigation.result.get("risk_flags", []),
                "suggested_score_modifier": modifier,
                "suggested_alert_level": investigation.result.get("suggested_alert_level"),
                "caveats": investigation.result.get("caveats", []),
            }
        cluster.confirmation_score = score.confidence_score
        cluster.novelty_score = score.novelty_score
        cluster.urgency_score = score.urgency_score
        cluster.market_impact_score = max(score.impact_score, score.market_move_score)
        cluster.relevance_score = score.relevance_score
        cluster.final_score = adjusted_final_score
        decision = decide_alert(adjusted_final_score, thresholds)
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
