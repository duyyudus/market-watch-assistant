from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw: object) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, _dialect):
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(self, _dialect, _coltype):
        def process(value: object | None) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            text = str(value).strip("[]")
            if not text:
                return []
            return [float(item) for item in text.split(",")]

        return process


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
    auto_quality_score: Mapped[int | None] = mapped_column(Integer)
    quality_metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    quality_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paywall_risk: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    requires_auth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parser_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rss")
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    burst_until_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_until_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (UniqueConstraint("url", name="uq_news_sources_url"),)

    @property
    def effective_source_score(self) -> int:
        if self.auto_quality_score is None:
            return int(self.source_score)
        return round(int(self.source_score) * 0.7 + int(self.auto_quality_score) * 0.3)


class SourceFetchLog(Base):
    __tablename__ = "source_fetch_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("fetch"))
    source_id: Mapped[str] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False
    )
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
    source_id: Mapped[str] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False
    )
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
    source_id: Mapped[str] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False
    )
    raw_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_news_items.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)
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
    full_text_extraction_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    full_text_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    full_text_last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    full_text_last_http_status: Mapped[int | None] = mapped_column(Integer)
    full_text_last_error: Mapped[str | None] = mapped_column(Text)
    full_text_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        ForeignKey("normalized_news_items.id", ondelete="CASCADE"), nullable=False
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
    high_quality_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_source_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmation_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    novelty_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urgency_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    market_impact_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_level: Mapped[str | None] = mapped_column(String(32))
    archive_summary: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    compacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EventClusterItem(Base):
    __tablename__ = "event_cluster_items"

    event_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="CASCADE"), primary_key=True
    )
    news_item_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_news_items.id", ondelete="CASCADE"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="related")
    similarity_score: Mapped[int | None] = mapped_column(Integer)
    decision_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventScoreHistory(Base):
    __tablename__ = "event_score_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("score"))
    event_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="CASCADE"), nullable=False
    )
    score_breakdown: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsItemEmbedding(Base):
    __tablename__ = "news_item_embeddings"

    news_item_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_news_items.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=1536)
    embedding_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventClusterEmbedding(Base):
    __tablename__ = "event_cluster_embeddings"

    event_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=1536)
    embedding_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LLMAnalysisRun(Base):
    __tablename__ = "llm_analysis_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("llm"))
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "target_id",
            "provider",
            "model",
            "prompt_version",
            name="uq_llm_analysis_runs_target_model_prompt",
        ),
    )


class AgentInvestigation(Base):
    __tablename__ = "agent_investigations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("inv"))
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    usage: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MarketMove(Base):
    __tablename__ = "market_moves"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("move"))
    asset_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window: Mapped[str] = mapped_column(String(16), nullable=False)
    price_change_pct: Mapped[float] = mapped_column(nullable=False)
    volume_change_pct: Mapped[float | None] = mapped_column()
    value_traded_change_pct: Mapped[float | None] = mapped_column()
    z_score: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MissedCatalystReview(Base):
    __tablename__ = "missed_catalyst_reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("review"))
    asset_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(64), nullable=False)
    move_window: Mapped[str] = mapped_column(String(16), nullable=False)
    price_change_pct: Mapped[float] = mapped_column(nullable=False)
    volume_change_pct: Mapped[float | None] = mapped_column()
    detected_event_cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    agent_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AlertDecisionRecord(Base):
    __tablename__ = "alert_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("alert"))
    event_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    score_breakdown: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str | None] = mapped_column(String(32))
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertChannel(Base):
    __tablename__ = "alert_channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("chan"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AlertSuppressionRule(Base):
    __tablename__ = "alert_suppression_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rule"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AlertDeliveryRecord(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: new_id("delivery")
    )
    alert_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_decisions.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider_response: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permanently_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderCooldown(Base):
    __tablename__ = "provider_cooldowns"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="cooling_down")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    cooldown_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DigestRecord(Base):
    __tablename__ = "digests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("digest"))
    digest_type: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="built")
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[str | None] = mapped_column(String(32))
    recipient: Mapped[str | None] = mapped_column(String(255))
    provider_response: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class BotCommand(Base):
    __tablename__ = "bot_commands"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cmd"))
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
