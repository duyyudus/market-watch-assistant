from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("src"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rss")
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    polling_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    source_score: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    paywall_risk: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    requires_auth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parser_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rss")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (UniqueConstraint("url", name="uq_news_sources_url"),)


class SourceFetchLog(Base):
    __tablename__ = "source_fetch_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("fetch"))
    source_id: Mapped[str] = mapped_column(ForeignKey("news_sources.id"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64))


class RawNewsItem(Base):
    __tablename__ = "raw_news_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("raw"))
    source_id: Mapped[str] = mapped_column(ForeignKey("news_sources.id"), nullable=False)
    raw_title: Mapped[str | None] = mapped_column(Text)
    raw_description: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)
    raw_url: Mapped[str | None] = mapped_column(Text)
    raw_published_at: Mapped[str | None] = mapped_column(String(255))
    raw_author: Mapped[str | None] = mapped_column(String(255))
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_raw_news_source_hash"),
    )


class NormalizedNewsItem(Base):
    __tablename__ = "normalized_news_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("news"))
    source_id: Mapped[str] = mapped_column(ForeignKey("news_sources.id"), nullable=False)
    raw_item_id: Mapped[str | None] = mapped_column(ForeignKey("raw_news_items.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_score: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_paywalled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    full_text_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_url_hash: Mapped[str | None] = mapped_column(String(64))
    normalized_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class NewsEntity(Base):
    __tablename__ = "news_entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ent"))
    news_item_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_news_items.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_text: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(32))
    exchange: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)


class EventCluster(Base):
    __tablename__ = "event_clusters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evt"))
    canonical_headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reported")
    regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    asset_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    affected_entities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    affected_tickers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    top_source_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmation_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    novelty_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urgency_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    market_impact_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_level: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EventClusterItem(Base):
    __tablename__ = "event_cluster_items"

    event_cluster_id: Mapped[str] = mapped_column(ForeignKey("event_clusters.id"), primary_key=True)
    news_item_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_news_items.id"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="related")
    similarity_score: Mapped[int | None] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventScoreHistory(Base):
    __tablename__ = "event_score_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("score"))
    event_cluster_id: Mapped[str] = mapped_column(ForeignKey("event_clusters.id"), nullable=False)
    score_breakdown: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertDecisionRecord(Base):
    __tablename__ = "alert_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("alert"))
    event_cluster_id: Mapped[str] = mapped_column(ForeignKey("event_clusters.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    score_breakdown: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str | None] = mapped_column(String(32))
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchlistEntity(Base):
    __tablename__ = "watchlist_entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("watch"))
    symbol: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tier: Mapped[str] = mapped_column(String(1), nullable=False, default="D")
    region: Mapped[str | None] = mapped_column(String(64))
    asset_class: Mapped[str | None] = mapped_column(String(64))
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("jobrun"))
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)


class RetentionJob(Base):
    __tablename__ = "retention_jobs"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: new_id("retention")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    deleted_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
