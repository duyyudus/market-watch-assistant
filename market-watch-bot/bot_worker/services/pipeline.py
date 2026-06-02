from __future__ import annotations

import logging
from datetime import UTC, datetime

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
from bot_worker.services.full_text import extract_full_text_for_priority_events
from bot_worker.services.ingestion import mark_exact_duplicates, normalize_pending_raw_items
from bot_worker.services.investigation import (
    queue_event_investigation_runs,
    queue_investigations_for_missed_catalysts,
    run_investigations_concurrently,
)
from bot_worker.services.llm import enrich_event_clusters_with_llm, extract_entities_with_llm
from bot_worker.services.market import (
    fetch_market_moves_with_stats,
    run_missed_catalyst_review,
    store_market_moves,
)
from bot_worker.services.pipeline_metrics import PipelineRunMetrics
from bot_worker.services.sources import fetch_source
from bot_worker.services.watchlists import watchlist_entries

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
) -> dict[str, object]:
    if dry_run:
        return {"status": "dry_run", "jobs": len(CORE_JOBS)}

    metrics = PipelineRunMetrics()

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
    skipped_sources = 0
    poll_source_cooldown_skips = 0
    failed_sources = 0
    degraded_stages: list[str] = []
    failed_stages: list[str] = []
    rate_limit_skips: dict[str, int] = {}
    provider_retries: dict[str, object] = {}
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 1/11] Polling News Sources ───")
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
        elif result.get("status") == "skipped":
            skipped_sources += 1
            reason = str(result.get("reason", "skipped"))
            if reason == "failure_cooldown":
                poll_source_cooldown_skips += 1
                rate_limit_skips["rss"] = rate_limit_skips.get("rss", 0) + 1
            logger.info("  ⚠ Skipped source %s: %s", source.name, reason)
        elif result.get("status") == "not_modified":
            logger.info("  ✓ Source %s not modified (304)", source.name)
        else:
            failed_sources += 1
            logger.error("  ❌ Failed to fetch source %s: %s", source.name, result.get("error"))
    if poll_source_cooldown_skips:
        degraded_stages.append("poll_sources")
    if failed_sources:
        degraded_stages.append("poll_sources")
    metrics.record_stage(
        stage_name="poll_sources",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_in=len(sources),
        items_out=fetched,
        status="degraded" if poll_source_cooldown_skips or failed_sources else "success",
    )

    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 2/11] Normalizing Raw Items ───")
    normalized = await normalize_pending_raw_items(
        session, freshness_hours=freshness_hours, tracking_params=tracking_params
    )
    logger.info("  ✓ Normalized %d news items", normalized)
    metrics.record_stage(
        stage_name="normalize_raw_items",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=normalized,
    )

    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 3/11] Deduplicating News Items ───")
    duplicates = await mark_exact_duplicates(session)
    logger.info("  ✓ Marked %d duplicate news items", duplicates)
    metrics.record_stage(
        stage_name="dedupe_news_items",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=duplicates,
    )

    news_embeddings = 0
    entities_extracted = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 4/11] Extracting News Entities ───")
    stage_status = "success"
    if llm_config is not None and llm_config.enabled:
        try:
            entities_extracted = await extract_entities_with_llm(session, config=llm_config)
        except Exception as exc:  # noqa: BLE001
            degraded_stages.append("extract_entities")
            stage_status = "degraded"
            logger.error("  ❌ Failed to extract entities with LLM: %s", exc)
        logger.info("  ✓ Extracted entities for %d news items", entities_extracted)
    else:
        stage_status = "skipped"
        logger.info("  ⚠ LLM config disabled or not provided, skipping entity extraction")
    metrics.record_stage(
        stage_name="extract_entities",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=entities_extracted,
        status=stage_status,
    )

    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 5/11] Generating News Embeddings ───")
    stage_status = "success"
    if embedding_config is not None:
        try:
            news_embeddings = await embed_pending_news_items(session, config=embedding_config)
        except Exception as exc:  # noqa: BLE001
            degraded_stages.append("generate_embeddings")
            stage_status = "degraded"
            logger.error("  ❌ Failed to generate news embeddings: %s", exc)
        logger.info("  ✓ Generated embeddings for %d news items", news_embeddings)
    else:
        stage_status = "skipped"
        logger.info("  ⚠ Embedding config not provided, skipping news embedding generation")
    metrics.record_stage(
        stage_name="generate_embeddings",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=news_embeddings,
        status=stage_status,
    )

    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 6/11] Building Event Clusters ───")
    stage_status = "success"
    try:
        cluster_stats: ClusterBuildStats = await build_event_clusters(
            session,
            embedding_config=embedding_config,
            llm_config=llm_config,
        )
    except Exception as exc:  # noqa: BLE001
        failed_stages.append("cluster_events")
        stage_status = "failed"
        logger.error("  ❌ Failed to build event clusters: %s", exc)
        cluster_stats = ClusterBuildStats()
    logger.info("  ✓ Built %d new event clusters", cluster_stats.created_clusters)
    logger.info(
        "  ✓ Attached %d items to existing clusters (%d LLM decisions, %d LLM attaches)",
        cluster_stats.attached_existing,
        cluster_stats.llm_cluster_decisions,
        cluster_stats.llm_cluster_attaches,
    )
    metrics.record_stage(
        stage_name="cluster_events",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=cluster_stats.created_clusters + cluster_stats.attached_existing,
        status=stage_status,
    )

    event_embeddings = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 7/11] Generating Event Embeddings ───")
    stage_status = "success"
    if embedding_config is not None:
        try:
            event_embeddings = await embed_pending_event_clusters(session, config=embedding_config)
        except Exception as exc:  # noqa: BLE001
            degraded_stages.append("generate_event_embeddings")
            stage_status = "degraded"
            logger.error("  ❌ Failed to generate event embeddings: %s", exc)
        logger.info("  ✓ Generated embeddings for %d event clusters", event_embeddings)
    else:
        stage_status = "skipped"
        logger.info(
            "  ⚠ Embedding config not provided, skipping event cluster embedding generation"
        )
    metrics.record_stage(
        stage_name="generate_event_embeddings",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=event_embeddings,
        status=stage_status,
    )

    llm_enriched = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 8/11] LLM Event Enrichment ───")
    stage_status = "success"
    if llm_config is not None and llm_config.enabled:
        try:
            llm_enriched = await enrich_event_clusters_with_llm(session, config=llm_config)
        except Exception as exc:  # noqa: BLE001
            degraded_stages.append("enrich_events_with_llm")
            stage_status = "degraded"
            logger.error("  ❌ Failed to enrich events with LLM: %s", exc)
        logger.info("  ✓ Enriched %d event clusters with LLM analysis", llm_enriched)
    else:
        stage_status = "skipped"
        logger.info("  ⚠ LLM config disabled or not provided, skipping event enrichment")
    metrics.record_stage(
        stage_name="enrich_events_with_llm",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=llm_enriched,
        status=stage_status,
    )

    market_moves_fetched = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 9/11] Fetching Market Moves ───")
    stage_status = "success"
    try:
        from common.config import load_settings
        settings = load_settings()
        watchlist = await watchlist_entries(session)
        symbols = list({entry.symbol for entry in watchlist if entry.symbol})
        if symbols:
            logger.info(
                "  Fetching market moves for %d watchlisted assets: %s",
                len(symbols),
                ", ".join(symbols),
            )
            market_result = await fetch_market_moves_with_stats(
                symbols=symbols,
                window="1d",
                vn_base_url=settings.market_data.vn_base_url,
                symbol_map=settings.market_data.symbol_map,
                crypto_provider=settings.market_data.crypto_provider,
                crypto_fallback_provider=settings.market_data.crypto_fallback_provider,
            )
            provider_retries["market_data"] = {
                "degraded_providers": market_result.degraded_providers,
                "failed_providers": market_result.failed_providers,
                "errors": market_result.errors,
            }
            if market_result.degraded_providers:
                degraded_stages.append("fetch_market_moves")
                stage_status = "degraded"
            if market_result.failed_providers:
                degraded_stages.append("fetch_market_moves")
                stage_status = "degraded"
            market_moves_fetched = await store_market_moves(session, market_result.moves)
            logger.info("  ✓ Successfully fetched and stored %d market moves", market_moves_fetched)
        else:
            stage_status = "skipped"
            logger.info("  ⚠ No watchlisted assets with symbols found, skipping market fetch")
    except Exception as exc:  # noqa: BLE001
        failed_stages.append("fetch_market_moves")
        stage_status = "failed"
        logger.error("  ❌ Failed to fetch market moves: %s", exc)
    metrics.record_stage(
        stage_name="fetch_market_moves",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=market_moves_fetched,
        status=stage_status,
    )

    full_text_extracted = 0
    full_text_attempted = 0
    full_text_fallback_used = 0
    full_text_skipped = 0
    full_text_retryable_failed = 0
    full_text_failed = 0
    stage_start = datetime.now(UTC)
    stage_status = "success"
    try:
        full_text_stats = await extract_full_text_for_priority_events(session)
        full_text_attempted = getattr(full_text_stats, "attempted", 0)
        full_text_extracted = full_text_stats.extracted
        full_text_fallback_used = getattr(full_text_stats, "fallback_used", 0)
        full_text_skipped = getattr(full_text_stats, "skipped", 0)
        full_text_retryable_failed = getattr(full_text_stats, "retryable_failed", 0)
        full_text_failed = getattr(full_text_stats, "failed", full_text_retryable_failed)
        if full_text_retryable_failed:
            degraded_stages.append("full_text_extraction")
            stage_status = "degraded"
    except Exception as exc:  # noqa: BLE001
        degraded_stages.append("full_text_extraction")
        stage_status = "degraded"
        logger.error("  ❌ Failed to extract full text: %s", exc)
    metrics.record_stage(
        stage_name="full_text_extraction",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=full_text_extracted,
        status=stage_status,
    )

    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 10/11] Recording Alert Decisions ───")
    stage_status = "success"
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
            if llm_config is not None and event_investigations:
                res = await run_investigations_concurrently(
                    session,
                    event_investigations,
                    config=investigation_config,
                    llm_config=llm_config,
                )
                completed_investigations = res.get("completed", 0)
                failed_investigations = res.get("failed", 0)
            elif event_investigations:
                failed_investigations = len(event_investigations)
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
            degraded_stages.append("investigation")
            stage_status = "degraded"
            logger.error("  ❌ Failed to queue agent investigations: %s", exc)
    alerts = await record_alert_decisions(session)
    logger.info("  ✓ Recorded alert decisions for %d event clusters", alerts)
    delivered_alerts = 0
    failed_alert_deliveries = 0
    if alert_delivery_config is not None and alert_delivery_config.channel == "telegram":
        delivery_counts = await dispatch_pending_alerts(session, alert_delivery_config)
        delivered_alerts = delivery_counts["sent"]
        failed_alert_deliveries = delivery_counts["failed"]
        if failed_alert_deliveries:
            degraded_stages.append("dispatch_alerts")
            stage_status = "degraded"
        logger.info(
            "  ✓ Delivered %d Telegram alerts (%d failed)",
            delivered_alerts,
            failed_alert_deliveries,
        )
    else:
        logger.info("  ⚠ Alert delivery config not provided or not Telegram, skipping dispatch")
    metrics.record_stage(
        stage_name="record_alert_decisions",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=alerts,
        status=stage_status,
    )

    missed_catalysts_created = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 11/11] Missed Catalyst Review ───")
    stage_status = "success"
    try:
        missed_catalysts_created = await run_missed_catalyst_review(session, window="1d")
        logger.info(
            "  ✓ Completed review; created %d missed catalyst tasks",
            missed_catalysts_created,
        )
    except Exception as exc:  # noqa: BLE001
        degraded_stages.append("run_missed_catalyst_review")
        stage_status = "degraded"
        logger.error("  ❌ Failed to run missed catalyst review: %s", exc)
    metrics.record_stage(
        stage_name="run_missed_catalyst_review",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=missed_catalysts_created,
        status=stage_status,
    )
    metrics.finish(status="degraded" if degraded_stages or failed_stages else "success")

    logger.info("======================================================================")
    logger.info("🎉 Pipeline run completed successfully!")
    logger.info("======================================================================")
    return {
        "fetched": fetched,
        "skipped_sources": skipped_sources,
        "poll_source_cooldown_skips": poll_source_cooldown_skips,
        "failed_sources": failed_sources,
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
        "market_moves_fetched": market_moves_fetched,
        "full_text_attempted": full_text_attempted,
        "full_text_extracted": full_text_extracted,
        "full_text_fallback_used": full_text_fallback_used,
        "full_text_skipped": full_text_skipped,
        "full_text_retryable_failed": full_text_retryable_failed,
        "full_text_failed": full_text_failed,
        "queued_investigations": queued_investigations,
        "completed_investigations": completed_investigations,
        "failed_investigations": failed_investigations,
        "alerts": alerts,
        "delivered_alerts": delivered_alerts,
        "failed_alert_deliveries": failed_alert_deliveries,
        "missed_catalysts_created": missed_catalysts_created,
        "degraded_stages": sorted(set(degraded_stages)),
        "failed_stages": sorted(set(failed_stages)),
        "rate_limit_skips": rate_limit_skips,
        "provider_retries": provider_retries,
        "pipeline_metrics": metrics.to_dict(),
    }
