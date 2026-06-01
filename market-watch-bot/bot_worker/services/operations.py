from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import AlertDeliveryRecord, JobRun, LLMAnalysisRun, SourceFetchLog
from bot_worker.services.alert_delivery import AlertDeliveryConfig

SUPPRESSION_WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class OperationalAlert:
    alert_type: str
    message: str


async def run_operational_checks(
    session: AsyncSession,
    *,
    settings,
    alert_delivery_config: AlertDeliveryConfig,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now(UTC)
    alerts = await collect_operational_alerts(session, settings=settings, now=current)
    sent = 0
    suppressed = 0
    emitted: list[str] = []
    for alert in alerts:
        if await _recently_sent(session, alert.alert_type, current):
            suppressed += 1
            continue
        _record_operational_alert(session, alert, alert_delivery_config, current)
        sent += 1
        emitted.append(alert.alert_type)
    return {"sent": sent, "suppressed": suppressed, "alerts": emitted}


async def collect_operational_alerts(
    session: AsyncSession,
    *,
    settings,
    now: datetime,
) -> list[OperationalAlert]:
    alerts: list[OperationalAlert] = []
    bot_settings = getattr(settings, "bot", settings)
    polling_interval = int(getattr(bot_settings, "polling_interval_seconds", 300))
    latest_pipeline = await _latest_pipeline_run(session)
    if latest_pipeline is not None and latest_pipeline.completed_at is not None:
        completed_at = _aware_utc(latest_pipeline.completed_at)
        if now - completed_at > timedelta(seconds=polling_interval * 2):
            alerts.append(
                OperationalAlert(
                    alert_type="worker_heartbeat",
                    message="Market Watch worker appears to be down",
                )
            )

    failing_sources, total_sources = await _source_failure_counts(session, now)
    if total_sources > 0 and failing_sources / total_sources > 0.5:
        alerts.append(
            OperationalAlert(
                alert_type="source_failures",
                message="Multiple source fetch failures",
            )
        )

    failed_llm_runs = await _recent_failed_llm_runs(session, now)
    if failed_llm_runs >= 3:
        alerts.append(
            OperationalAlert(
                alert_type="llm_provider_unreachable",
                message="LLM provider unreachable",
            )
        )
    return alerts


async def _latest_pipeline_run(session: AsyncSession) -> JobRun | None:
    if hasattr(session, "latest_pipeline"):
        return session.latest_pipeline
    if not hasattr(session, "scalar"):
        return None
    return await session.scalar(
        select(JobRun)
        .where(JobRun.job_name == "pipeline", JobRun.status == "success")
        .order_by(JobRun.completed_at.desc())
        .limit(1)
    )


async def _source_failure_counts(session: AsyncSession, now: datetime) -> tuple[int, int]:
    if hasattr(session, "source_logs"):
        latest_by_source: dict[str, SourceFetchLog] = {}
        for log in session.source_logs:
            current = latest_by_source.get(log.source_id)
            if current is None or log.fetched_at > current.fetched_at:
                latest_by_source[log.source_id] = log
        total = len(latest_by_source)
        failing = sum(1 for log in latest_by_source.values() if log.status != "success")
        return failing, total
    if not hasattr(session, "execute"):
        return 0, 0

    rows = list(
        (
            await session.execute(
                select(SourceFetchLog.source_id, SourceFetchLog.status, SourceFetchLog.fetched_at)
                .where(SourceFetchLog.fetched_at >= now - timedelta(hours=24))
                .order_by(SourceFetchLog.source_id.asc(), SourceFetchLog.fetched_at.desc())
            )
        ).all()
    )
    latest_by_source: dict[str, str] = {}
    for source_id, status, _fetched_at in rows:
        latest_by_source.setdefault(source_id, status)
    total = len(latest_by_source)
    failing = sum(1 for status in latest_by_source.values() if status != "success")
    return failing, total


async def _recent_failed_llm_runs(session: AsyncSession, now: datetime) -> int:
    if hasattr(session, "llm_runs"):
        return sum(
            1
            for run in session.llm_runs
            if run.status == "failed" and _aware_utc(run.created_at) >= now - timedelta(hours=1)
        )
    if not hasattr(session, "scalar"):
        return 0
    return int(
        await session.scalar(
            select(func.count(LLMAnalysisRun.id)).where(
                LLMAnalysisRun.status == "failed",
                LLMAnalysisRun.created_at >= now - timedelta(hours=1),
            )
        )
        or 0
    )


async def _recently_sent(session: AsyncSession, alert_type: str, now: datetime) -> bool:
    marker = f"[Operational Alert]\n{alert_type}\n"
    cutoff = now - SUPPRESSION_WINDOW
    if hasattr(session, "deliveries"):
        return any(
            delivery.status == "sent"
            and _aware_utc(delivery.attempted_at) >= cutoff
            and delivery.message_text.startswith(marker)
            for delivery in session.deliveries
        )
    existing = await session.scalar(
        select(AlertDeliveryRecord.id)
        .where(
            AlertDeliveryRecord.status == "sent",
            AlertDeliveryRecord.attempted_at >= cutoff,
            AlertDeliveryRecord.message_text.like(f"{marker}%"),
        )
        .limit(1)
    )
    return existing is not None


def _record_operational_alert(
    session: AsyncSession,
    alert: OperationalAlert,
    config: AlertDeliveryConfig,
    now: datetime,
) -> None:
    recipient = config.telegram_chat_id or config.channel
    session.add(
        AlertDeliveryRecord(
            channel=config.channel,
            recipient=recipient,
            status="sent",
            message_text=f"[Operational Alert]\n{alert.alert_type}\n{alert.message}",
            provider_response={"operational_alert": alert.alert_type},
            attempted_at=now,
        )
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
