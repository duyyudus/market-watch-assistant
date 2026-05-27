from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    NewsSource,
)
from bot_worker.embeddings import (
    EmbeddingConfig,
)
from bot_worker.llm import (
    LLMConfig,
)
from bot_worker.services.alerts import record_alert_decisions
from bot_worker.services.embeddings import embed_pending_event_clusters, embed_pending_news_items
from bot_worker.services.events import build_event_clusters
from bot_worker.services.ingestion import mark_exact_duplicates, normalize_pending_raw_items
from bot_worker.services.llm import enrich_event_clusters_with_llm
from bot_worker.services.sources import fetch_source

logger = logging.getLogger("bot_worker")
CORE_JOBS = [
    "poll_sources",
    "normalize_raw_items",
    "dedupe_news_items",
    "extract_entities",
    "generate_embeddings",
    "cluster_events",
    "enrich_events_with_llm",
    "fetch_market_moves",
    "score_events",
    "dispatch_alerts",
    "build_digest",
    "run_missed_catalyst_review",
    "retention_cleanup",
    "source_health_check",
]
async def run_pipeline(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    freshness_hours: int = 72,
    embedding_config: EmbeddingConfig | None = None,
    llm_config: LLMConfig | None = None,
) -> dict[str, int | str]:
    if dry_run:
        return {"status": "dry_run", "jobs": len(CORE_JOBS)}

    logger.info("======================================================================")
    logger.info(
        "🚀 Starting pipeline run [freshness_hours=%d, embeddings=%s]",
        freshness_hours,
        "enabled" if embedding_config is not None else "disabled",
    )
    logger.info("======================================================================")

    sources = list(
        (await session.scalars(select(NewsSource).where(NewsSource.enabled.is_(True)))).all()
    )
    fetched = 0
    logger.info("─── [Stage 1/8] Polling News Sources ───")
    logger.info("  Found %d enabled news sources to poll", len(sources))
    for source in sources:
        logger.info("  → Polling source: %s (%s)", source.name, source.url)
        result = await fetch_source(session, source)
        if result.get("status") == "success":
            inserted = int(result.get("inserted", 0))
            fetched += inserted
            logger.info(
                "  ✓ Successfully fetched %d items from %s (inserted %d new)",
                result.get("items", 0),
                source.name,
                inserted,
            )
        else:
            logger.error("  ❌ Failed to fetch source %s: %s", source.name, result.get("error"))

    logger.info("─── [Stage 2/8] Normalizing Raw Items ───")
    normalized = await normalize_pending_raw_items(session, freshness_hours=freshness_hours)
    logger.info("  ✓ Normalized %d news items", normalized)

    logger.info("─── [Stage 3/8] Deduplicating News Items ───")
    duplicates = await mark_exact_duplicates(session)
    logger.info("  ✓ Marked %d duplicate news items", duplicates)

    news_embeddings = 0
    logger.info("─── [Stage 4/8] Generating News Embeddings ───")
    if embedding_config is not None:
        news_embeddings = await embed_pending_news_items(session, config=embedding_config)
        logger.info("  ✓ Generated embeddings for %d news items", news_embeddings)
    else:
        logger.info("  ⚠ Embedding config not provided, skipping news embedding generation")

    logger.info("─── [Stage 5/8] Building Event Clusters ───")
    clusters = await build_event_clusters(session, embedding_config=embedding_config)
    logger.info("  ✓ Built %d new event clusters", clusters)

    event_embeddings = 0
    logger.info("─── [Stage 6/8] Generating Event Embeddings ───")
    if embedding_config is not None:
        event_embeddings = await embed_pending_event_clusters(session, config=embedding_config)
        logger.info("  ✓ Generated embeddings for %d event clusters", event_embeddings)
    else:
        logger.info(
            "  ⚠ Embedding config not provided, skipping event cluster embedding generation"
        )

    llm_enriched = 0
    logger.info("─── [Stage 7/8] LLM Event Enrichment ───")
    if llm_config is not None and llm_config.enabled:
        llm_enriched = await enrich_event_clusters_with_llm(session, config=llm_config)
        logger.info("  ✓ Enriched %d event clusters with LLM analysis", llm_enriched)
    else:
        logger.info("  ⚠ LLM config disabled or not provided, skipping event enrichment")

    logger.info("─── [Stage 8/8] Recording Alert Decisions ───")
    alerts = await record_alert_decisions(session)
    logger.info("  ✓ Recorded alert decisions for %d event clusters", alerts)

    logger.info("======================================================================")
    logger.info("🎉 Pipeline run completed successfully!")
    logger.info("======================================================================")
    return {
        "fetched": fetched,
        "normalized": normalized,
        "duplicates": duplicates,
        "news_embeddings": news_embeddings,
        "clusters": clusters,
        "event_embeddings": event_embeddings,
        "llm_enriched": llm_enriched,
        "alerts": alerts,
    }
