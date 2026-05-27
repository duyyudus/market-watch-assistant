from __future__ import annotations

from bot_worker.services.alert_delivery import (
    AlertDeliveryConfig,
    dispatch_pending_alerts,
    format_alert_message,
    send_test_alert,
)
from bot_worker.services.alerts import (
    record_alert_decisions,
)
from bot_worker.services.digests import (
    digest_display_headline,
    digest_preview,
    digest_time_in_window,
    select_digest_headline,
)
from bot_worker.services.embeddings import (
    embed_pending_event_clusters,
    embed_pending_news_items,
)
from bot_worker.services.events import (
    build_event_clusters,
    pgvector_literal,
    recluster_recent_event_clusters,
    vector_cluster_candidates_for_item,
)
from bot_worker.services.ingestion import (
    is_rss_item_fresh,
    mark_exact_duplicates,
    normalize_pending_raw_items,
    raw_item_from_parsed,
)
from bot_worker.services.jobs import (
    record_job_run,
)
from bot_worker.services.llm import (
    classify_news_item_with_llm,
    enrich_event_clusters_with_llm,
    extract_entities_with_llm,
    latest_llm_analysis,
    latest_successful_llm_analysis,
    score_event_with_llm,
    summarize_event_with_llm,
)
from bot_worker.services.market import (
    fetch_market_moves,
    market_move_score_for_cluster,
    run_missed_catalyst_review,
    store_market_moves,
)
from bot_worker.services.pipeline import (
    CORE_JOBS,
    run_pipeline,
)
from bot_worker.services.retention import (
    baseline_reset_preview,
    retention_preview,
    run_baseline_reset,
    run_retention,
)
from bot_worker.services.sources import (
    add_source,
    fetch_source,
    fetch_source_content,
    get_source,
    import_sources_yaml,
    list_sources,
    purge_source,
    seed_starter_sources,
    set_source_enabled,
)
from bot_worker.services.watchlists import (
    add_watchlist_entry,
    news_item_entities,
    news_item_tickers,
    watchlist_entries,
)

__all__ = [
    "AlertDeliveryConfig",
    "CORE_JOBS",
    "add_source",
    "add_watchlist_entry",
    "baseline_reset_preview",
    "build_event_clusters",
    "classify_news_item_with_llm",
    "digest_display_headline",
    "digest_preview",
    "digest_time_in_window",
    "dispatch_pending_alerts",
    "embed_pending_event_clusters",
    "embed_pending_news_items",
    "enrich_event_clusters_with_llm",
    "extract_entities_with_llm",
    "fetch_market_moves",
    "fetch_source",
    "fetch_source_content",
    "format_alert_message",
    "get_source",
    "import_sources_yaml",
    "is_rss_item_fresh",
    "latest_llm_analysis",
    "latest_successful_llm_analysis",
    "list_sources",
    "mark_exact_duplicates",
    "market_move_score_for_cluster",
    "news_item_entities",
    "news_item_tickers",
    "normalize_pending_raw_items",
    "pgvector_literal",
    "purge_source",
    "raw_item_from_parsed",
    "record_alert_decisions",
    "record_job_run",
    "recluster_recent_event_clusters",
    "retention_preview",
    "run_baseline_reset",
    "run_missed_catalyst_review",
    "run_pipeline",
    "run_retention",
    "score_event_with_llm",
    "seed_starter_sources",
    "select_digest_headline",
    "send_test_alert",
    "set_source_enabled",
    "store_market_moves",
    "summarize_event_with_llm",
    "vector_cluster_candidates_for_item",
    "watchlist_entries",
]
