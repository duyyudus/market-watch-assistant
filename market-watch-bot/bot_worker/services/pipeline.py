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
from bot_worker.investigation import InvestigationConfig
from bot_worker.llm import (
    LLMConfig,
)
from bot_worker.services.alert_delivery import AlertDeliveryConfig, dispatch_pending_alerts
from bot_worker.services.alerts import record_alert_decisions
from bot_worker.services.embeddings import embed_pending_event_clusters, embed_pending_news_items
from bot_worker.services.events import ClusterBuildStats, build_event_clusters
from bot_worker.services.ingestion import mark_exact_duplicates, normalize_pending_raw_items
from bot_worker.services.investigation import (
    queue_event_investigation_runs,
    queue_investigations_for_missed_catalysts,
    run_existing_investigation,
)
from bot_worker.services.llm import enrich_event_clusters_with_llm, extract_entities_with_llm
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
    investigation_config: InvestigationConfig | None = None,
    alert_delivery_config: AlertDeliveryConfig | None = None,
    tracking_params: list[str] | None = None,
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
    logger.info("─── [Stage 1/9] Polling News Sources ───")
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

    logger.info("─── [Stage 2/9] Normalizing Raw Items ───")
    normalized = await normalize_pending_raw_items(
        session, freshness_hours=freshness_hours, tracking_params=tracking_params
    )
    logger.info("  ✓ Normalized %d news items", normalized)

    logger.info("─── [Stage 3/9] Deduplicating News Items ───")
    duplicates = await mark_exact_duplicates(session)
    logger.info("  ✓ Marked %d duplicate news items", duplicates)

    news_embeddings = 0
    entities_extracted = 0
    logger.info("─── [Stage 4/9] Extracting News Entities ───")
    if llm_config is not None and llm_config.enabled:
        entities_extracted = await extract_entities_with_llm(session, config=llm_config)
        logger.info("  ✓ Extracted entities for %d news items", entities_extracted)
    else:
        logger.info("  ⚠ LLM config disabled or not provided, skipping entity extraction")

    logger.info("─── [Stage 5/9] Generating News Embeddings ───")
    if embedding_config is not None:
        news_embeddings = await embed_pending_news_items(session, config=embedding_config)
        logger.info("  ✓ Generated embeddings for %d news items", news_embeddings)
    else:
        logger.info("  ⚠ Embedding config not provided, skipping news embedding generation")

    logger.info("─── [Stage 6/9] Building Event Clusters ───")
    cluster_stats: ClusterBuildStats = await build_event_clusters(
        session,
        embedding_config=embedding_config,
        llm_config=llm_config,
    )
    logger.info("  ✓ Built %d new event clusters", cluster_stats.created_clusters)
    logger.info(
        "  ✓ Attached %d items to existing clusters (%d LLM decisions, %d LLM attaches)",
        cluster_stats.attached_existing,
        cluster_stats.llm_cluster_decisions,
        cluster_stats.llm_cluster_attaches,
    )

    event_embeddings = 0
    logger.info("─── [Stage 7/9] Generating Event Embeddings ───")
    if embedding_config is not None:
        event_embeddings = await embed_pending_event_clusters(session, config=embedding_config)
        logger.info("  ✓ Generated embeddings for %d event clusters", event_embeddings)
    else:
        logger.info(
            "  ⚠ Embedding config not provided, skipping event cluster embedding generation"
        )

    llm_enriched = 0
    logger.info("─── [Stage 8/9] LLM Event Enrichment ───")
    if llm_config is not None and llm_config.enabled:
        llm_enriched = await enrich_event_clusters_with_llm(session, config=llm_config)
        logger.info("  ✓ Enriched %d event clusters with LLM analysis", llm_enriched)
    else:
        logger.info("  ⚠ LLM config disabled or not provided, skipping event enrichment")

    logger.info("─── [Stage 9/9] Recording Alert Decisions ───")
    queued_investigations = 0
    completed_investigations = 0
    failed_investigations = 0
    if investigation_config is not None and investigation_config.enabled:
        try:
            event_investigations = await queue_event_investigation_runs(
                session,
                config=investigation_config,
            )
            queued_investigations += len(event_investigations)
            if llm_config is not None:
                for run in event_investigations:
                    result = await run_existing_investigation(
                        session,
                        run,
                        config=investigation_config,
                        llm_config=llm_config,
                    )
                    if result.status == "succeeded":
                        completed_investigations += 1
                    else:
                        failed_investigations += 1
            else:
                failed_investigations += len(event_investigations)
            queued_investigations += await queue_investigations_for_missed_catalysts(
                session,
                config=investigation_config,
            )
            logger.info(
                "  ✓ Queued %d agent investigations; completed %d, failed %d",
                queued_investigations,
                completed_investigations,
                failed_investigations,
            )
        except Exception as exc:  # noqa: BLE001 - investigation queueing must not block alerts
            logger.error("  ❌ Failed to queue agent investigations: %s", exc)
    alerts = await record_alert_decisions(session)
    logger.info("  ✓ Recorded alert decisions for %d event clusters", alerts)
    delivered_alerts = 0
    failed_alert_deliveries = 0
    if alert_delivery_config is not None and alert_delivery_config.channel == "telegram":
        delivery_counts = await dispatch_pending_alerts(session, alert_delivery_config)
        delivered_alerts = delivery_counts["sent"]
        failed_alert_deliveries = delivery_counts["failed"]
        logger.info(
            "  ✓ Delivered %d Telegram alerts (%d failed)",
            delivered_alerts,
            failed_alert_deliveries,
        )
    else:
        logger.info("  ⚠ Alert delivery config not provided or not Telegram, skipping dispatch")

    logger.info("======================================================================")
    logger.info("🎉 Pipeline run completed successfully!")
    logger.info("======================================================================")
    return {
        "fetched": fetched,
        "normalized": normalized,
        "duplicates": duplicates,
        "entities_extracted": entities_extracted,
        "news_embeddings": news_embeddings,
        "clusters": cluster_stats.created_clusters,
        "cluster_attached_existing": cluster_stats.attached_existing,
        "llm_cluster_decisions": cluster_stats.llm_cluster_decisions,
        "llm_cluster_attaches": cluster_stats.llm_cluster_attaches,
        "event_embeddings": event_embeddings,
        "llm_enriched": llm_enriched,
        "queued_investigations": queued_investigations,
        "completed_investigations": completed_investigations,
        "failed_investigations": failed_investigations,
        "alerts": alerts,
        "delivered_alerts": delivered_alerts,
        "failed_alert_deliveries": failed_alert_deliveries,
    }
