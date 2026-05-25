"""market watch bot mvp schema

Revision ID: 0001_market_watch_bot_mvp
Revises:
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_market_watch_bot_mvp"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "news_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("asset_classes", postgresql.JSONB, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("polling_interval_seconds", sa.Integer, nullable=False),
        sa.Column("source_score", sa.Integer, nullable=False),
        sa.Column("paywall_risk", sa.String(16), nullable=False),
        sa.Column("requires_auth", sa.Boolean, nullable=False),
        sa.Column("parser_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("url", name="uq_news_sources_url"),
    )
    op.create_table(
        "source_fetch_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("news_sources.id"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("error_message", sa.Text),
        sa.Column("item_count", sa.Integer),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64)),
    )
    op.create_table(
        "raw_news_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("news_sources.id"), nullable=False),
        sa.Column("raw_title", sa.Text),
        sa.Column("raw_description", sa.Text),
        sa.Column("raw_content", sa.Text),
        sa.Column("raw_url", sa.Text),
        sa.Column("raw_published_at", sa.String(255)),
        sa.Column("raw_author", sa.String(255)),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_raw_news_source_hash"),
    )
    op.create_table(
        "normalized_news_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("news_sources.id"), nullable=False),
        sa.Column("raw_item_id", sa.String(64), sa.ForeignKey("raw_news_items.id")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("snippet", sa.Text),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("canonical_url", sa.Text),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_score", sa.Integer, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("asset_classes", postgresql.JSONB, nullable=False),
        sa.Column("is_paywalled", sa.Boolean, nullable=False),
        sa.Column("full_text_available", sa.Boolean, nullable=False),
        sa.Column("title_hash", sa.String(64), nullable=False),
        sa.Column("canonical_url_hash", sa.String(64)),
        sa.Column("normalized_text_hash", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "news_entities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "news_item_id", sa.String(64), sa.ForeignKey("normalized_news_items.id"), nullable=False
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("raw_text", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("ticker", sa.String(32)),
        sa.Column("exchange", sa.String(32)),
        sa.Column("country", sa.String(64)),
        sa.Column("confidence", sa.Integer, nullable=False),
    )
    op.create_table(
        "event_clusters",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("canonical_headline", sa.Text, nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("first_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_updated_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("regions", postgresql.JSONB, nullable=False),
        sa.Column("asset_classes", postgresql.JSONB, nullable=False),
        sa.Column("affected_entities", postgresql.JSONB, nullable=False),
        sa.Column("affected_tickers", postgresql.JSONB, nullable=False),
        sa.Column("source_count", sa.Integer, nullable=False),
        sa.Column("top_source_score", sa.Integer, nullable=False),
        sa.Column("confirmation_score", sa.Integer, nullable=False),
        sa.Column("novelty_score", sa.Integer, nullable=False),
        sa.Column("urgency_score", sa.Integer, nullable=False),
        sa.Column("market_impact_score", sa.Integer, nullable=False),
        sa.Column("relevance_score", sa.Integer, nullable=False),
        sa.Column("final_score", sa.Integer, nullable=False),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True)),
        sa.Column("alert_level", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "event_cluster_items",
        sa.Column(
            "event_cluster_id", sa.String(64), sa.ForeignKey("event_clusters.id"), primary_key=True
        ),
        sa.Column(
            "news_item_id",
            sa.String(64),
            sa.ForeignKey("normalized_news_items.id"),
            primary_key=True,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("similarity_score", sa.Integer),
        sa.Column("added_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "event_score_history",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "event_cluster_id", sa.String(64), sa.ForeignKey("event_clusters.id"), nullable=False
        ),
        sa.Column("score_breakdown", postgresql.JSONB, nullable=False),
        sa.Column("final_score", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "alert_decisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "event_cluster_id", sa.String(64), sa.ForeignKey("event_clusters.id"), nullable=False
        ),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("channel", sa.String(32)),
        sa.Column("suppression_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "watchlist_entities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(64)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("tier", sa.String(1), nullable=False),
        sa.Column("region", sa.String(64)),
        sa.Column("asset_class", sa.String(64)),
        sa.Column("aliases", postgresql.JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
    )
    op.create_table(
        "retention_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("deleted_counts", postgresql.JSONB, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    for table in [
        "app_settings",
        "retention_jobs",
        "job_runs",
        "watchlist_entities",
        "alert_decisions",
        "event_score_history",
        "event_cluster_items",
        "event_clusters",
        "news_entities",
        "normalized_news_items",
        "raw_news_items",
        "source_fetch_logs",
        "news_sources",
    ]:
        op.drop_table(table)
