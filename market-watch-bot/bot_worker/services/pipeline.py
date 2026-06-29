from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
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
from bot_worker.services.alert_delivery import AlertDeliveryConfig
from bot_worker.services.alerts import record_alert_decisions
from bot_worker.services.embeddings import embed_pending_event_clusters, embed_pending_news_items
from bot_worker.services.events import ClusterBuildStats, build_event_clusters
from bot_worker.services.full_text import extract_full_text_for_pending_items
from bot_worker.services.ingestion import (
    NormalizationStats,
    mark_exact_duplicates,
)
from bot_worker.services.ingestion import (
    normalize_pending_raw_items_with_stats as normalize_pending_raw_items,
)
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
from common.llm import (
    LLMConfig,
)
from common.market_symbol_resolver import watchlist_market_symbol_requests

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


async def _run_stage_savepoint[T](
    session: AsyncSession,
    operation: Callable[[], Awaitable[T]],
) -> T:
    begin_nested = getattr(session, "begin_nested", None)
    if begin_nested is None:
        return await operation()
    async with begin_nested():
        return await operation()


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
    disclosure_noise_patterns: list[str] | None = None,
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
    logger.info("─── [Stage 1/12] Polling News Sources ───")
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
                provider = source.source_type if source.source_type in {"rss", "crawler"} else "rss"
                rate_limit_skips[provider] = rate_limit_skips.get(provider, 0) + 1
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
    logger.info("─── [Stage 2/12] Normalizing Raw Items ───")
    normalization_result = await normalize_pending_raw_items(
        session,
        freshness_hours=freshness_hours,
        tracking_params=tracking_params,
        disclosure_noise_patterns=disclosure_noise_patterns,
    )
    normalization_stats = (
        normalization_result
        if isinstance(normalization_result, NormalizationStats)
        else NormalizationStats(inserted_total=int(normalization_result))
    )
    normalized = normalization_stats.inserted_total
    logger.info("  ✓ Normalized %d news items", normalized)
    metrics.record_stage(
        stage_name="normalize_raw_items",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=normalized,
    )

    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 3/12] Deduplicating News Items ───")
    duplicates = await mark_exact_duplicates(session)
    logger.info("  ✓ Marked %d duplicate news items", duplicates)
    metrics.record_stage(
        stage_name="dedupe_news_items",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=duplicates,
    )

    full_text_extracted = 0
    full_text_attempted = 0
    full_text_fallback_used = 0
    full_text_skipped = 0
    full_text_retryable_failed = 0
    full_text_failed = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 4/12] Extracting Full Text ───")
    stage_status = "success"
    try:
        full_text_stats = await _run_stage_savepoint(
            session,
            lambda: extract_full_text_for_pending_items(session),
        )
        full_text_attempted = getattr(full_text_stats, "attempted", 0)
        full_text_extracted = full_text_stats.extracted
        full_text_fallback_used = getattr(full_text_stats, "fallback_used", 0)
        full_text_skipped = getattr(full_text_stats, "skipped", 0)
        full_text_retryable_failed = getattr(full_text_stats, "retryable_failed", 0)
        full_text_failed = getattr(full_text_stats, "failed", full_text_retryable_failed)
        logger.info(
            "  ✓ Extracted full text for %d news items (attempted=%d, fallback=%d, skipped=%d)",
            full_text_extracted,
            full_text_attempted,
            full_text_fallback_used,
            full_text_skipped,
        )
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

    news_embeddings = 0
    entities_extracted = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 5/12] Extracting News Entities ───")
    stage_status = "success"
    if llm_config is not None and llm_config.enabled:
        try:
            entities_extracted = await _run_stage_savepoint(
                session,
                lambda: extract_entities_with_llm(session, config=llm_config),
            )
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
    logger.info("─── [Stage 6/12] Generating News Embeddings ───")
    stage_status = "success"
    if embedding_config is not None:
        try:
            news_embeddings = await _run_stage_savepoint(
                session,
                lambda: embed_pending_news_items(session, config=embedding_config),
            )
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
    logger.info("─── [Stage 7/12] Building Event Clusters ───")
    stage_status = "success"
    try:
        cluster_stats: ClusterBuildStats = await _run_stage_savepoint(
            session,
            lambda: build_event_clusters(
                session,
                embedding_config=embedding_config,
                llm_config=llm_config,
            ),
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
    logger.info("─── [Stage 8/12] Generating Event Embeddings ───")
    stage_status = "success"
    if embedding_config is not None:
        try:
            event_embeddings = await _run_stage_savepoint(
                session,
                lambda: embed_pending_event_clusters(session, config=embedding_config),
            )
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
    logger.info("─── [Stage 9/12] LLM Event Enrichment ───")
    stage_status = "success"
    if llm_config is not None and llm_config.enabled:
        try:
            llm_enriched = await _run_stage_savepoint(
                session,
                lambda: enrich_event_clusters_with_llm(session, config=llm_config),
            )
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
    logger.info("─── [Stage 10/12] Fetching Market Moves ───")
    stage_status = "success"
    try:
        from common.config import load_settings
        settings = load_settings()
        market_symbols = await watchlist_market_symbol_requests(session, settings=settings)
        symbols = sorted({request.symbol for request in market_symbols})
        if symbols:
            logger.info(
                "  Fetching market moves for %d watchlisted assets: %s",
                len(symbols),
                ", ".join(symbols),
            )
            market_result = await fetch_market_moves_with_stats(
                resolved_symbols=market_symbols,
                window="1d",
                vn_base_url=settings.market_data.vn_base_url,
                symbol_map=settings.market_data.symbol_map,
                crypto_provider=settings.market_data.crypto_provider,
                crypto_fallback_provider=settings.market_data.crypto_fallback_provider,
                coingecko_api_key=settings.coingecko_api_key,
                global_provider=settings.market_data.global_provider,
                hyperliquid_base_url=settings.market_data.hyperliquid_base_url,
                hyperliquid_dex=settings.market_data.hyperliquid_dex,
                hyperliquid_min_day_notional_volume=(
                    settings.market_data.hyperliquid_min_day_notional_volume
                ),
            )
            provider_retries["market_data"] = {
                "degraded_providers": market_result.degraded_providers,
                "failed_providers": market_result.failed_providers,
                "errors": market_result.errors,
                "skipped_symbols": market_result.skipped_symbols,
                "unavailable_symbols": market_result.unavailable_symbols,
            }
            if market_result.skipped_symbols:
                logger.warning(
                    "  ⚠ Skipped %d watchlisted assets by quality gate: %s",
                    len(market_result.skipped_symbols),
                    "; ".join(
                        f"{symbol} ({reason})"
                        for symbol, reason in market_result.skipped_symbols.items()
                    ),
                )
            if market_result.unavailable_symbols:
                logger.warning(
                    "  ⚠ No market data for %d watchlisted assets: %s",
                    len(market_result.unavailable_symbols),
                    "; ".join(
                        f"{symbol} ({reason})"
                        for symbol, reason in market_result.unavailable_symbols.items()
                    ),
                )
            if (
                market_result.degraded_providers
                or market_result.failed_providers
                or market_result.unavailable_symbols
            ):
                degraded_stages.append("fetch_market_moves")
                stage_status = "degraded"
            market_moves_fetched = await _run_stage_savepoint(
                session,
                lambda: store_market_moves(session, market_result.moves),
            )
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

    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 11/12] Recording Alert Decisions ───")
    stage_status = "success"
    queued_investigations = 0
    completed_investigations = 0
    failed_investigations = 0
    if investigation_config is not None and investigation_config.enabled:
        try:
            event_investigations = await _run_stage_savepoint(
                session,
                lambda: queue_event_investigation_runs(
                    session,
                    config=investigation_config,
                ),
            )
            queued_investigations += len(event_investigations)
            if llm_config is not None and event_investigations:
                res = await _run_stage_savepoint(
                    session,
                    lambda: run_investigations_concurrently(
                        session,
                        event_investigations,
                        config=investigation_config,
                        llm_config=llm_config,
                    ),
                )
                completed_investigations = res.get("completed", 0)
                failed_investigations = res.get("failed", 0)
            elif event_investigations:
                failed_investigations = len(event_investigations)
            queued_investigations += await _run_stage_savepoint(
                session,
                lambda: queue_investigations_for_missed_catalysts(
                    session,
                    config=investigation_config,
                ),
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
    # Alert delivery runs outside this transaction (see deliver_pending_alerts) so a
    # crash later in the run cannot roll back ``sent_at`` and re-deliver alerts.
    delivered_alerts = 0
    failed_alert_deliveries = 0
    metrics.record_stage(
        stage_name="record_alert_decisions",
        start_time=stage_start,
        end_time=datetime.now(UTC),
        items_out=alerts,
        status=stage_status,
    )

    missed_catalysts_created = 0
    stage_start = datetime.now(UTC)
    logger.info("─── [Stage 12/12] Missed Catalyst Review ───")
    stage_status = "success"
    try:
        missed_catalysts_created = await _run_stage_savepoint(
            session,
            lambda: run_missed_catalyst_review(session, window="1d"),
        )
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
        "rss_freshness_hours": freshness_hours,
        "skipped_sources": skipped_sources,
        "poll_source_cooldown_skips": poll_source_cooldown_skips,
        "failed_sources": failed_sources,
        "normalized": normalized,
        "normalization_diagnostics": normalization_stats.as_dict(),
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
