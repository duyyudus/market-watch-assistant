from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import new_id, utcnow


class EventCluster(Base):
    __tablename__ = "event_clusters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evt"))
    canonical_headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reported")
    regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    asset_classes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    affected_entities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    affected_tickers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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

    event_cluster_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    news_item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="related")
    similarity_score: Mapped[int | None] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventScoreHistory(Base):
    __tablename__ = "event_score_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("score"))
    event_cluster_id: Mapped[str] = mapped_column(String(64), nullable=False)
    score_breakdown: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
