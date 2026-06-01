from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    DigestRecord,
    EventCluster,
    EventClusterItem,
    NormalizedNewsItem,
)

if TYPE_CHECKING:
    from bot_worker.services.alert_delivery import AlertDeliveryConfig, TelegramSender

type ReportTimeRange = tuple[datetime, datetime]


def _effective_report_time(
    published_at: datetime | None,
    fetched_at: datetime | None,
    created_at: datetime,
) -> datetime:
    effective_time = published_at or fetched_at or created_at
    if effective_time.tzinfo is None:
        return effective_time.replace(tzinfo=UTC)
    return effective_time


def digest_time_in_window(
    *,
    published_at: datetime | None,
    fetched_at: datetime | None,
    created_at: datetime,
    since: datetime,
    until: datetime,
) -> bool:
    effective_time = _effective_report_time(published_at, fetched_at, created_at)
    return since <= effective_time < until


def select_report_time_range(
    members: list[tuple[datetime | None, datetime | None, datetime]],
) -> ReportTimeRange | None:
    if not members:
        return None
    times = [
        _effective_report_time(published_at, fetched_at, created_at)
        for published_at, fetched_at, created_at in members
    ]
    return min(times), max(times)


def _format_report_timestamp(value: datetime) -> str:
    value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return f"{value:%b} {value.day} {value:%H:%M}"


def format_report_time_range(report_time_range: ReportTimeRange | None) -> str:
    if report_time_range is None:
        return ""
    reported_at, latest_report_at = report_time_range
    if reported_at == latest_report_at:
        return f"reported {_format_report_timestamp(reported_at)}"
    return (
        f"reports {_format_report_timestamp(reported_at)}"
        f" - {_format_report_timestamp(latest_report_at)}"
    )


def format_report_time_span(report_time_range: ReportTimeRange | None) -> str:
    if report_time_range is None:
        return ""
    reported_at, latest_report_at = report_time_range
    if reported_at == latest_report_at:
        return _format_report_timestamp(reported_at)
    return f"{_format_report_timestamp(reported_at)} - {_format_report_timestamp(latest_report_at)}"


async def event_report_time_range(
    session: AsyncSession,
    event_cluster_id: str,
) -> ReportTimeRange | None:
    rows = list(
        (
            await session.execute(
                select(
                    NormalizedNewsItem.published_at,
                    NormalizedNewsItem.fetched_at,
                    NormalizedNewsItem.created_at,
                )
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id == event_cluster_id)
            )
        ).all()
    )
    return select_report_time_range(
        [(published_at, fetched_at, created_at) for published_at, fetched_at, created_at in rows]
    )


def select_digest_headline(
    *,
    canonical_headline: str,
    members: list[tuple[str, datetime | None, datetime | None, datetime]],
    since: datetime,
    until: datetime,
) -> str:
    in_window: list[tuple[str, datetime]] = []
    for title, published_at, fetched_at, created_at in members:
        effective_time = _effective_report_time(published_at, fetched_at, created_at)
        if since <= effective_time < until:
            in_window.append((title, effective_time))
    if not in_window:
        return canonical_headline
    return max(in_window, key=lambda item: item[1])[0]
async def digest_preview(
    session: AsyncSession,
    *,
    limit: int = 20,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[EventCluster]:
    stmt = (
        select(EventCluster)
        .order_by(EventCluster.final_score.desc(), EventCluster.created_at.desc())
        .limit(limit)
    )
    if since is not None or until is not None:
        item_time = func.coalesce(
            NormalizedNewsItem.published_at,
            NormalizedNewsItem.fetched_at,
            NormalizedNewsItem.created_at,
        )
        matching_clusters = (
            select(EventClusterItem.event_cluster_id)
            .join(NormalizedNewsItem, NormalizedNewsItem.id == EventClusterItem.news_item_id)
            .distinct()
        )
        if since is not None:
            matching_clusters = matching_clusters.where(item_time >= since)
        if until is not None:
            matching_clusters = matching_clusters.where(item_time < until)
        stmt = stmt.where(EventCluster.id.in_(matching_clusters))
    return list((await session.scalars(stmt)).all())
async def digest_display_headline(
    session: AsyncSession,
    event: EventCluster,
    *,
    since: datetime | None,
    until: datetime | None,
) -> str:
    if since is None or until is None:
        return event.canonical_headline
    rows = list(
        (
            await session.execute(
                select(
                    NormalizedNewsItem.title,
                    NormalizedNewsItem.published_at,
                    NormalizedNewsItem.fetched_at,
                    NormalizedNewsItem.created_at,
                )
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id == event.id)
            )
        ).all()
    )
    return select_digest_headline(
        canonical_headline=event.canonical_headline,
        members=[
            (title, published_at, fetched_at, created_at)
            for title, published_at, fetched_at, created_at in rows
        ],
        since=since,
        until=until,
    )


def _digest_group(event: EventCluster) -> str:
    region = (event.regions or ["global"])[0].upper()
    asset_class = (event.asset_classes or ["market"])[0]
    return f"{region} / {asset_class}"


def format_digest_message(
    events: list[EventCluster],
    *,
    since: datetime,
    until: datetime,
) -> str:
    lines = [
        "[Daily Market Digest]",
        f"Window: {format_report_time_span((since, until))}",
    ]
    grouped: dict[str, list[EventCluster]] = {}
    for event in events:
        grouped.setdefault(_digest_group(event), []).append(event)
    for group in sorted(grouped):
        lines.extend(["", group])
        for event in sorted(grouped[group], key=lambda item: item.final_score, reverse=True):
            lines.append(
                f"- {event.final_score} {event.status}: {event.canonical_headline}"
                f" ({event.source_count} sources)"
            )
    if not events:
        lines.extend(["", "No digest-worthy events in this window."])
    return "\n".join(lines)


async def build_digest_record(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    threshold: int,
    limit: int = 50,
) -> DigestRecord:
    events = [
        event
        for event in await digest_preview(session, limit=limit, since=since, until=until)
        if event.final_score >= threshold
    ]
    digest = DigestRecord(
        digest_type="daily",
        window_start=since,
        window_end=until,
        content=format_digest_message(events, since=since, until=until),
        status="built",
        event_count=len(events),
    )
    session.add(digest)
    await session.flush()
    return digest


async def send_digest_record(
    session: AsyncSession,
    digest: DigestRecord,
    config: AlertDeliveryConfig,
    *,
    send_telegram_message: TelegramSender | None = None,
) -> DigestRecord:
    if send_telegram_message is None:
        from bot_worker.services.alert_delivery import send_telegram_message as telegram_sender
        send_telegram_message = telegram_sender
    if config.channel != "telegram" or not config.telegram_configured:
        digest.status = "skipped"
        digest.error_message = "Telegram digest delivery is not configured"
        return digest
    assert config.telegram_chat_id is not None
    digest.channel = "telegram"
    digest.recipient = config.telegram_chat_id
    try:
        digest.provider_response = await send_telegram_message(
            config,
            config.telegram_chat_id,
            digest.content,
        )
    except Exception as exc:  # noqa: BLE001 - digest history should record delivery failure
        digest.status = "failed"
        digest.error_message = str(exc)
        return digest
    digest.status = "sent"
    digest.sent_at = datetime.now(UTC)
    await session.flush()
    return digest
