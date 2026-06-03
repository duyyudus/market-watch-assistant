from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import bindparam, delete, func, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    EventCluster,
    EventClusterEmbedding,
    EventClusterItem,
    NewsItemEmbedding,
    NormalizedNewsItem,
    Vector,
    new_id,
    utcnow,
)
from bot_worker.embeddings import (
    EmbeddingConfig,
)
from bot_worker.events import (
    EventCandidate,
    EventClusterDraft,
    SameEventDecisionKind,
    VectorClusterCandidate,
    classify_same_event,
    is_vector_cluster_attachable,
    vector_similarity_score,
)
from bot_worker.llm import LLMConfig
from bot_worker.normalize import content_hash
from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event
from bot_worker.services.llm import resolve_llm_cluster_decision
from bot_worker.services.watchlists import (
    news_item_entities,
    news_item_tickers,
    tier_for_entities,
    watchlist_entries,
)
from bot_worker.watchlist import WatchlistEntry, match_watchlist


@dataclass(frozen=True)
class ClusterBuildStats:
    created_clusters: int = 0
    attached_existing: int = 0
    llm_cluster_decisions: int = 0
    llm_cluster_attaches: int = 0


def validate_pgvector(vector: list[float], *, dimensions: int | None = None) -> None:
    if not vector:
        raise ValueError("vector must not be empty")
    if dimensions is not None and len(vector) != dimensions:
        raise ValueError(f"vector dimensions mismatch: expected {dimensions}, got {len(vector)}")
    for value in vector:
        if not isinstance(value, int | float):
            raise ValueError("vector values must be numeric")


def _result_rowcount(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def vector_cluster_candidates_for_item(
    session: AsyncSession,
    news_item: NormalizedNewsItem,
    *,
    config: EmbeddingConfig,
    lookback_days: int,
    limit: int,
) -> list[VectorClusterCandidate]:
    embedding = await session.get(NewsItemEmbedding, news_item.id)
    if embedding is None:
        return []
    validate_pgvector(embedding.vector, dimensions=config.dimensions)

    cutoff = utcnow() - timedelta(days=lookback_days)
    stmt = sql_text(
        """
        SELECT
            ec.id AS cluster_id,
            1 - (ece.vector <=> CAST(:query_vector AS vector)) AS similarity,
            ec.regions AS regions,
            ec.asset_classes AS asset_classes,
            ec.affected_entities AS affected_entities
        FROM event_cluster_embeddings ece
        JOIN event_clusters ec ON ec.id = ece.event_cluster_id
        WHERE ec.last_updated_at >= :cutoff
          AND ece.provider = :provider
          AND ece.embedding_model = :model
          AND ece.embedding_version = :version
          AND ece.dimensions = :dimensions
        ORDER BY ece.vector <=> CAST(:query_vector AS vector)
        LIMIT :limit
        """
    ).bindparams(
        bindparam("query_vector", type_=Vector(config.dimensions)),
    )
    rows = (
        await session.execute(
            stmt,
            {
                "query_vector": embedding.vector,
                "cutoff": cutoff,
                "provider": config.provider,
                "model": config.model,
                "version": config.version,
                "dimensions": config.dimensions,
                "limit": limit,
            },
        )
    ).all()
    candidates: list[VectorClusterCandidate] = []
    for row in rows:
        values = row._mapping
        candidates.append(
            VectorClusterCandidate(
                cluster_id=values["cluster_id"],
                similarity=float(values["similarity"]),
                regions=list(values["regions"] or []),
                asset_classes=list(values["asset_classes"] or []),
                affected_entities=list(values["affected_entities"] or []),
            )
        )
    return candidates


def _effective_news_time() -> object:
    return func.coalesce(
        NormalizedNewsItem.published_at,
        NormalizedNewsItem.fetched_at,
        NormalizedNewsItem.created_at,
    )


def _rescore_cluster(
    cluster: EventCluster,
    watch_entries: list[WatchlistEntry] | None = None,
) -> None:
    tier = (
        tier_for_entities(
            entities=cluster.affected_entities or [],
            tickers=cluster.affected_tickers or [],
            entries=watch_entries,
        )
        if watch_entries is not None
        else ("A" if cluster.affected_entities else None)
    )
    score = score_event(
        ScoreInput(
            top_source_score=cluster.top_source_score,
            source_count=cluster.source_count,
            watchlist_tier=tier,
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=int(cluster.high_quality_source_count or 0),
        )
    )
    cluster.confirmation_score = score.confidence_score
    cluster.novelty_score = score.novelty_score
    cluster.urgency_score = score.urgency_score
    cluster.market_impact_score = score.impact_score
    cluster.relevance_score = score.relevance_score
    cluster.final_score = score.final_score
    cluster.alert_level = decide_alert(score.final_score, AlertThresholds()).decision


def _candidate_has_plausible_context(
    candidate: VectorClusterCandidate,
    *,
    item_region: str,
    item_asset_classes: list[str],
) -> bool:
    candidate_regions = {value.casefold() for value in candidate.regions if value}
    region = item_region.casefold()
    if region not in candidate_regions and "global" not in candidate_regions and region != "global":
        return False

    candidate_asset_classes = {value.casefold() for value in candidate.asset_classes if value}
    item_asset_class_set = {value.casefold() for value in item_asset_classes if value}
    return not (
        candidate_asset_classes
        and item_asset_class_set
        and not (candidate_asset_classes & item_asset_class_set)
    )


def _is_gray_zone_cluster_candidate(
    candidate: VectorClusterCandidate,
    *,
    item_region: str,
    item_asset_classes: list[str],
    embedding_config: EmbeddingConfig,
    llm_config: LLMConfig | None,
) -> bool:
    if llm_config is None:
        return False
    if candidate.similarity < llm_config.cluster_ambiguous_min_similarity:
        return False
    if candidate.similarity >= embedding_config.cluster_attach_min_similarity:
        return False
    return _candidate_has_plausible_context(
        candidate,
        item_region=item_region,
        item_asset_classes=item_asset_classes,
    )
async def _attach_news_item_to_cluster(
    session: AsyncSession,
    *,
    item: NormalizedNewsItem,
    cluster: EventCluster,
    entities: list[str],
    tickers: list[str],
    similarity: float,
    watch_entries: list[WatchlistEntry],
    decision_metadata: dict[str, object] | None = None,
) -> None:
    session.add(
        EventClusterItem(
            event_cluster_id=cluster.id,
            news_item_id=item.id,
            similarity_score=vector_similarity_score(similarity),
            decision_metadata=decision_metadata
            or {
                "decision_source": "vector",
                "decision": "strong_same_event",
                "similarity": round(similarity, 4),
            },
        )
    )
    cluster.last_updated_at = utcnow()
    cluster.regions = sorted(set(cluster.regions or []) | {item.region})
    cluster.asset_classes = sorted(set(cluster.asset_classes or []) | set(item.asset_classes))
    cluster.affected_entities = sorted(set(cluster.affected_entities or []) | set(entities))
    cluster.affected_tickers = sorted(set(cluster.affected_tickers or []) | set(tickers))
    cluster.source_count += 1
    if item.source_score >= 75:
        cluster.high_quality_source_count = int(cluster.high_quality_source_count or 0) + 1
    cluster.top_source_score = max(cluster.top_source_score, item.source_score)
    _rescore_cluster(cluster, watch_entries)
    await session.execute(
        delete(EventClusterEmbedding).where(EventClusterEmbedding.event_cluster_id == cluster.id)
    )


async def _candidate_from_item(
    session: AsyncSession,
    item: NormalizedNewsItem,
    watch_entries: list[WatchlistEntry],
) -> EventCandidate:
    matches = match_watchlist(f"{item.title} {item.snippet or ''}", watch_entries)
    stored_entities = await news_item_entities(session, item.id)
    stored_tickers = await news_item_tickers(session, item.id)
    entities = stored_entities or [match.name for match in matches]
    tickers = stored_tickers or [match.symbol for match in matches if match.symbol]
    return EventCandidate(
        news_id=item.id,
        title=item.title,
        source_score=item.source_score,
        entities=entities,
        tickers=tickers,
        region=item.region,
        asset_classes=item.asset_classes,
        published_at=item.published_at,
        watchlist_tier=tier_for_entities(entities=entities, tickers=tickers, entries=watch_entries),
        source_name=item.source_name,
        source_type=item.source_type,
        snippet=item.snippet,
    )


def _draft_candidate(draft: EventClusterDraft) -> EventCandidate:
    return EventCandidate(
        news_id="draft",
        title=draft.canonical_headline,
        source_score=draft.top_source_score,
        entities=list(draft.entities),
        tickers=list(draft.tickers),
        region=next(iter(draft.regions), "global"),
        asset_classes=list(draft.asset_classes),
        published_at=None,
        watchlist_tier=draft.watchlist_tier,
    )


def _draft_cluster(draft: EventClusterDraft) -> EventCluster:
    stable_id = f"draft_{content_hash('|'.join(draft.news_ids))[:16]}"
    return EventCluster(
        id=stable_id,
        canonical_headline=draft.canonical_headline,
        regions=sorted(draft.regions),
        asset_classes=sorted(draft.asset_classes),
        affected_entities=sorted(draft.entities),
        affected_tickers=sorted(draft.tickers),
        source_count=draft.source_count,
        high_quality_source_count=draft.high_quality_source_count,
        top_source_score=draft.top_source_score,
    )


def _add_candidate_to_draft(draft: EventClusterDraft, candidate: EventCandidate) -> None:
    _add_candidate_to_draft_with_metadata(
        draft,
        candidate,
        metadata={"decision_source": "seed", "decision": "seed"},
    )


def _add_candidate_to_draft_with_metadata(
    draft: EventClusterDraft,
    candidate: EventCandidate,
    *,
    metadata: dict[str, object],
) -> None:
    draft.news_ids.append(candidate.news_id)
    draft.item_decision_metadata[candidate.news_id] = metadata
    draft.entities.update(candidate.entities)
    draft.tickers.update(candidate.tickers)
    draft.regions.add(candidate.region)
    draft.asset_classes.update(candidate.asset_classes)
    draft.source_count += 1
    if candidate.source_score >= 75:
        draft.high_quality_source_count += 1
    draft.top_source_score = max(draft.top_source_score, candidate.source_score)
    if candidate.watchlist_tier is not None:
        ranks = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
        current = draft.watchlist_tier or "D"
        if ranks.get(candidate.watchlist_tier, 0) > ranks.get(current, 0):
            draft.watchlist_tier = candidate.watchlist_tier


async def _cluster_candidates_with_llm_arbitration(
    session: AsyncSession,
    candidates: list[EventCandidate],
    *,
    llm_config: LLMConfig | None,
) -> tuple[list[EventClusterDraft], int, int]:
    drafts: list[EventClusterDraft] = []
    llm_decisions = 0
    llm_attaches = 0
    for candidate in candidates:
        target: EventClusterDraft | None = None
        metadata: dict[str, object] | None = None
        for draft in drafts:
            decision = classify_same_event(candidate, _draft_candidate(draft))
            if decision.kind is SameEventDecisionKind.STRONG_SAME_EVENT:
                target = draft
                metadata = {
                    "decision_source": "deterministic",
                    "decision": decision.kind.value,
                    "reason": decision.reason,
                    "title_similarity": round(decision.title_similarity, 4),
                    "entity_overlap": decision.entity_overlap,
                    "ticker_overlap": decision.ticker_overlap,
                }
                break
            if decision.kind is not SameEventDecisionKind.AMBIGUOUS:
                continue
            if llm_config is None or not llm_config.enabled or not llm_config.api_key:
                continue
            attempted, should_attach = await resolve_llm_cluster_decision(
                session=session,
                item=NormalizedNewsItem(
                    id=candidate.news_id,
                    title=candidate.title,
                    snippet=candidate.snippet,
                    source_name=candidate.source_name,
                    source_type=candidate.source_type,
                    source_score=candidate.source_score,
                    region=candidate.region,
                    asset_classes=candidate.asset_classes,
                ),
                cluster=_draft_cluster(draft),
                similarity=decision.title_similarity,
                config=llm_config,
                entities=candidate.entities,
                tickers=candidate.tickers,
            )
            if attempted:
                llm_decisions += 1
            if should_attach:
                llm_attaches += 1
                target = draft
                metadata = {
                    "decision_source": "llm",
                    "decision": "same_event",
                    "reason": decision.reason,
                    "title_similarity": round(decision.title_similarity, 4),
                    "entity_overlap": decision.entity_overlap,
                    "ticker_overlap": decision.ticker_overlap,
                    "llm_attempted": attempted,
                }
                break
        if target is None:
            target = EventClusterDraft(canonical_headline=candidate.title)
            drafts.append(target)
        _add_candidate_to_draft_with_metadata(
            target,
            candidate,
            metadata=metadata or {"decision_source": "seed", "decision": "seed"},
        )
    return drafts, llm_decisions, llm_attaches


def _update_cluster_from_draft(
    cluster: EventCluster,
    draft: EventClusterDraft,
    watch_entries: list[WatchlistEntry],
) -> None:
    cluster.canonical_headline = draft.canonical_headline
    cluster.first_seen_at = cluster.first_seen_at or utcnow()
    cluster.last_updated_at = utcnow()
    cluster.status = "reported"
    cluster.regions = sorted(draft.regions)
    cluster.asset_classes = sorted(draft.asset_classes)
    cluster.affected_entities = sorted(draft.entities)
    cluster.affected_tickers = sorted(draft.tickers)
    cluster.source_count = draft.source_count
    cluster.high_quality_source_count = draft.high_quality_source_count
    cluster.top_source_score = draft.top_source_score
    score = score_event(
        ScoreInput(
            top_source_score=draft.top_source_score,
            source_count=draft.source_count,
            watchlist_tier=draft.watchlist_tier
            or tier_for_entities(
                entities=list(draft.entities),
                tickers=list(draft.tickers),
                entries=watch_entries,
            ),
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=draft.high_quality_source_count,
        )
    )
    cluster.confirmation_score = score.confidence_score
    cluster.novelty_score = score.novelty_score
    cluster.urgency_score = score.urgency_score
    cluster.market_impact_score = score.impact_score
    cluster.relevance_score = score.relevance_score
    cluster.final_score = score.final_score
    cluster.alert_level = decide_alert(score.final_score, AlertThresholds()).decision


def _mark_cluster_stale(cluster: EventCluster) -> None:
    cluster.status = "stale"
    cluster.last_updated_at = utcnow()
    cluster.affected_entities = []
    cluster.affected_tickers = []
    cluster.source_count = 0
    cluster.top_source_score = 0
    cluster.confirmation_score = 0
    cluster.novelty_score = 0
    cluster.urgency_score = 0
    cluster.market_impact_score = 0
    cluster.relevance_score = 0
    cluster.final_score = 0
    cluster.alert_level = None


async def recluster_recent_event_clusters(
    session: AsyncSession,
    *,
    since: datetime,
    dry_run: bool = True,
    limit: int = 500,
) -> dict[str, int | str]:
    cluster_ids = list(
        (
            await session.scalars(
                select(EventCluster.id)
                .where(EventCluster.last_updated_at >= since)
                .order_by(EventCluster.last_updated_at.desc())
                .limit(limit)
            )
        ).all()
    )
    if not cluster_ids:
        return {
            "status": "dry_run" if dry_run else "reclustered",
            "affected_clusters": 0,
            "news_items": 0,
            "new_clusters": 0,
            "stale_clusters": 0,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
        }

    clusters = list(
        (
            await session.scalars(
                select(EventCluster)
                .where(EventCluster.id.in_(cluster_ids))
                .order_by(EventCluster.last_updated_at.desc())
            )
        ).all()
    )
    items = list(
        (
            await session.scalars(
                select(NormalizedNewsItem)
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id.in_(cluster_ids))
                .order_by(_effective_news_time())
            )
        ).all()
    )
    if not items:
        return {
            "status": "dry_run" if dry_run else "reclustered",
            "affected_clusters": len(cluster_ids),
            "news_items": 0,
            "new_clusters": 0,
            "stale_clusters": 0,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
        }

    watch_entries = await watchlist_entries(session)
    candidates = [
        await _candidate_from_item(session, item, watch_entries)
        for item in items
    ]
    drafts, _, _ = await _cluster_candidates_with_llm_arbitration(
        session,
        candidates,
        llm_config=None,
    )
    stale_clusters = max(0, len(clusters) - len(drafts))
    if dry_run:
        return {
            "status": "dry_run",
            "affected_clusters": len(cluster_ids),
            "news_items": len(items),
            "new_clusters": len(drafts),
            "stale_clusters": stale_clusters,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
        }

    items_deleted = _result_rowcount(
        await session.execute(
            delete(EventClusterItem).where(EventClusterItem.event_cluster_id.in_(cluster_ids))
        )
    )
    embeddings_deleted = _result_rowcount(
        await session.execute(
            delete(EventClusterEmbedding).where(
                EventClusterEmbedding.event_cluster_id.in_(cluster_ids)
            )
        )
    )
    for cluster, draft in zip(clusters, drafts, strict=False):
        _update_cluster_from_draft(cluster, draft, watch_entries)
        for news_id in draft.news_ids:
            session.add(
                EventClusterItem(
                    event_cluster_id=cluster.id,
                    news_item_id=news_id,
                    decision_metadata=draft.item_decision_metadata.get(news_id),
                )
            )
    for cluster in clusters[len(drafts) :]:
        _mark_cluster_stale(cluster)

    return {
        "status": "reclustered",
        "affected_clusters": len(cluster_ids),
        "news_items": len(items),
        "new_clusters": len(drafts),
        "stale_clusters": stale_clusters,
        "event_cluster_items_deleted": items_deleted,
        "event_cluster_embeddings_deleted": embeddings_deleted,
    }


async def build_event_clusters(
    session: AsyncSession,
    *,
    limit: int = 500,
    embedding_config: EmbeddingConfig | None = None,
    llm_config: LLMConfig | None = None,
) -> ClusterBuildStats:
    existing_news = select(EventClusterItem.news_item_id)
    stmt = (
        select(NormalizedNewsItem)
        .where(NormalizedNewsItem.processing_status.in_(["normalized", "deduped"]))
        .where(NormalizedNewsItem.id.not_in(existing_news))
        .limit(limit)
    )
    items = list((await session.scalars(stmt)).all())
    if not items:
        return ClusterBuildStats()
    watch_entries = await watchlist_entries(session)
    candidates: list[EventCandidate] = []
    attached_existing = 0
    llm_cluster_decisions = 0
    llm_cluster_attaches = 0
    for item in items:
        candidate = await _candidate_from_item(session, item, watch_entries)
        entities = candidate.entities
        tickers = candidate.tickers
        attached = False
        if embedding_config is not None and embedding_config.cluster_attach_enabled:
            vector_candidates = await vector_cluster_candidates_for_item(
                session,
                item,
                config=embedding_config,
                lookback_days=embedding_config.cluster_attach_lookback_days,
                limit=embedding_config.cluster_attach_candidate_limit,
            )
            for vector_candidate in vector_candidates:
                if not is_vector_cluster_attachable(
                    vector_candidate,
                    item_region=item.region,
                    item_asset_classes=item.asset_classes,
                    item_entities=entities,
                    min_similarity=embedding_config.cluster_attach_min_similarity,
                ):
                    continue
                cluster = await session.get(EventCluster, vector_candidate.cluster_id)
                if cluster is None:
                    continue
                await _attach_news_item_to_cluster(
                    session,
                    item=item,
                    cluster=cluster,
                    entities=entities,
                    tickers=tickers,
                    similarity=vector_candidate.similarity,
                    watch_entries=watch_entries,
                    decision_metadata={
                        "decision_source": "vector",
                        "decision": "strong_same_event",
                        "similarity": round(vector_candidate.similarity, 4),
                    },
                )
                attached_existing += 1
                attached = True
                break
            if attached:
                continue
            for vector_candidate in vector_candidates[: (
                llm_config.cluster_decision_candidate_limit if llm_config is not None else 0
            )]:
                if not _is_gray_zone_cluster_candidate(
                    vector_candidate,
                    item_region=item.region,
                    item_asset_classes=item.asset_classes,
                    embedding_config=embedding_config,
                    llm_config=llm_config,
                ):
                    continue
                cluster = await session.get(EventCluster, vector_candidate.cluster_id)
                if cluster is None:
                    continue
                attempted, should_attach = await resolve_llm_cluster_decision(
                    session=session,
                    item=item,
                    cluster=cluster,
                    similarity=vector_candidate.similarity,
                    config=llm_config,
                    entities=entities,
                    tickers=tickers,
                )
                if attempted:
                    llm_cluster_decisions += 1
                if not should_attach:
                    continue
                await _attach_news_item_to_cluster(
                    session,
                    item=item,
                    cluster=cluster,
                    entities=entities,
                    tickers=tickers,
                    similarity=vector_candidate.similarity,
                    watch_entries=watch_entries,
                    decision_metadata={
                        "decision_source": "llm",
                        "decision": "same_event",
                        "similarity": round(vector_candidate.similarity, 4),
                        "llm_attempted": attempted,
                    },
                )
                attached_existing += 1
                llm_cluster_attaches += 1
                attached = True
                break
        if attached:
            continue
        candidates.append(
            candidate
        )
    batch_drafts, batch_llm_decisions, batch_llm_attaches = (
        await _cluster_candidates_with_llm_arbitration(
            session,
            candidates,
            llm_config=llm_config,
        )
    )
    drafts = batch_drafts
    llm_cluster_decisions += batch_llm_decisions
    llm_cluster_attaches += batch_llm_attaches
    for draft in drafts:
        first_seen = utcnow()
        cluster = EventCluster(
            canonical_headline=draft.canonical_headline,
            first_seen_at=first_seen,
            last_updated_at=first_seen,
            regions=sorted(draft.regions),
            asset_classes=sorted(draft.asset_classes),
            affected_entities=sorted(draft.entities),
            affected_tickers=sorted(draft.tickers),
            source_count=draft.source_count,
            high_quality_source_count=draft.high_quality_source_count,
            top_source_score=draft.top_source_score,
        )
        score = score_event(
            ScoreInput(
                top_source_score=draft.top_source_score,
                source_count=draft.source_count,
                watchlist_tier=draft.watchlist_tier
                or tier_for_entities(
                    entities=list(draft.entities),
                    tickers=list(draft.tickers),
                    entries=watch_entries,
                ),
                is_duplicate=False,
                is_stale=False,
                unique_high_quality_source_count=draft.high_quality_source_count,
            )
        )
        cluster.confirmation_score = score.confidence_score
        cluster.novelty_score = score.novelty_score
        cluster.urgency_score = score.urgency_score
        cluster.market_impact_score = score.impact_score
        cluster.relevance_score = score.relevance_score
        cluster.final_score = score.final_score
        cluster.alert_level = decide_alert(score.final_score, AlertThresholds()).decision
        session.add(cluster)
        await session.flush()
        for news_id in draft.news_ids:
            session.add(
                EventClusterItem(
                    event_cluster_id=cluster.id,
                    news_item_id=news_id,
                    decision_metadata=draft.item_decision_metadata.get(news_id),
                )
            )
    return ClusterBuildStats(
        created_clusters=len(drafts),
        attached_existing=attached_existing,
        llm_cluster_decisions=llm_cluster_decisions,
        llm_cluster_attaches=llm_cluster_attaches,
    )


async def _cluster_items(session: AsyncSession, cluster_id: str) -> list[NormalizedNewsItem]:
    if hasattr(session, "links") and hasattr(session, "items"):
        return [
            session.items[link.news_item_id]
            for link in session.links
            if link.event_cluster_id == cluster_id and link.news_item_id in session.items
        ]
    return list(
        (
            await session.scalars(
                select(NormalizedNewsItem)
                .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
                .where(EventClusterItem.event_cluster_id == cluster_id)
            )
        ).all()
    )


def _apply_cluster_item_summary(
    cluster: EventCluster,
    items: list[NormalizedNewsItem],
    watch_entries: list[WatchlistEntry] | None = None,
) -> None:
    if not items:
        _mark_cluster_stale(cluster)
        return
    latest = max(
        items,
        key=lambda item: item.published_at or item.fetched_at or item.created_at or utcnow(),
    )
    cluster.canonical_headline = latest.title
    cluster.last_updated_at = utcnow()
    cluster.regions = sorted({item.region for item in items})
    cluster.asset_classes = sorted(
        {asset_class for item in items for asset_class in item.asset_classes}
    )
    cluster.source_count = len(items)
    cluster.high_quality_source_count = sum(1 for item in items if item.source_score >= 75)
    cluster.top_source_score = max(item.source_score for item in items)
    _rescore_cluster(cluster, watch_entries)


async def _delete_cluster_embeddings(session: AsyncSession, cluster_ids: list[str]) -> int:
    if not cluster_ids:
        return 0
    result = await session.execute(
        delete(EventClusterEmbedding).where(EventClusterEmbedding.event_cluster_id.in_(cluster_ids))
    )
    return _result_rowcount(result)


async def merge_event_clusters(
    session: AsyncSession,
    *,
    source_id: str,
    target_id: str,
) -> dict[str, object]:
    if source_id == target_id:
        raise ValueError("source and target event clusters must be different")
    source = await session.get(EventCluster, source_id)
    target = await session.get(EventCluster, target_id)
    if source is None:
        raise ValueError(f"Event not found: {source_id}")
    if target is None:
        raise ValueError(f"Event not found: {target_id}")

    moved = 0
    if hasattr(session, "links"):
        existing_target_news = {
            link.news_item_id for link in session.links if link.event_cluster_id == target_id
        }
        for link in session.links:
            if link.event_cluster_id != source_id:
                continue
            if link.news_item_id in existing_target_news:
                continue
            link.event_cluster_id = target_id
            moved += 1
    else:
        source_news_ids = list(
            (
                await session.scalars(
                    select(EventClusterItem.news_item_id).where(
                        EventClusterItem.event_cluster_id == source_id
                    )
                )
            ).all()
        )
        for news_id in source_news_ids:
            exists_stmt = select(EventClusterItem.news_item_id).where(
                EventClusterItem.event_cluster_id == target_id,
                EventClusterItem.news_item_id == news_id,
            )
            if await session.scalar(exists_stmt):
                continue
            session.add(EventClusterItem(event_cluster_id=target_id, news_item_id=news_id))
            moved += 1
        await session.execute(
            delete(EventClusterItem).where(EventClusterItem.event_cluster_id == source_id)
        )

    watch_entries = None if hasattr(session, "links") else await watchlist_entries(session)
    _apply_cluster_item_summary(target, await _cluster_items(session, target_id), watch_entries)
    source.status = "merged"
    source.summary = f"Merged into {target.id}"
    source.last_updated_at = utcnow()
    embeddings_deleted = await _delete_cluster_embeddings(session, [source_id, target_id])
    if hasattr(session, "flush"):
        await session.flush()
    return {
        "status": "merged",
        "source_event_id": source.id,
        "target_event_id": target.id,
        "moved_items": moved,
        "event_cluster_embeddings_deleted": embeddings_deleted,
        "final_score": target.final_score,
    }


async def split_event_cluster(
    session: AsyncSession,
    *,
    source_id: str,
    news_item_ids: list[str],
) -> dict[str, object]:
    source = await session.get(EventCluster, source_id)
    if source is None:
        raise ValueError(f"Event not found: {source_id}")
    selected_ids = [item_id for item_id in dict.fromkeys(news_item_ids) if item_id]
    if not selected_ids:
        raise ValueError("at least one news item is required")
    items = [await session.get(NormalizedNewsItem, item_id) for item_id in selected_ids]
    selected_items = [item for item in items if item is not None]
    if len(selected_items) != len(selected_ids):
        raise ValueError("one or more news items were not found")

    new_cluster = EventCluster(
        id=new_id("evt"),
        canonical_headline=selected_items[0].title,
        first_seen_at=utcnow(),
        last_updated_at=utcnow(),
        status="reported",
        regions=[],
        asset_classes=[],
        affected_entities=[],
        affected_tickers=[],
        source_count=0,
        top_source_score=0,
    )
    session.add(new_cluster)
    if hasattr(session, "flush"):
        await session.flush()

    if hasattr(session, "links"):
        for link in session.links:
            if link.event_cluster_id == source_id and link.news_item_id in selected_ids:
                link.event_cluster_id = new_cluster.id
    else:
        await session.execute(
            delete(EventClusterItem).where(
                EventClusterItem.event_cluster_id == source_id,
                EventClusterItem.news_item_id.in_(selected_ids),
            )
        )
        for item_id in selected_ids:
            session.add(EventClusterItem(event_cluster_id=new_cluster.id, news_item_id=item_id))

    watch_entries = None if hasattr(session, "links") else await watchlist_entries(session)
    _apply_cluster_item_summary(new_cluster, selected_items, watch_entries)
    _apply_cluster_item_summary(source, await _cluster_items(session, source_id), watch_entries)
    embeddings_deleted = await _delete_cluster_embeddings(session, [source_id, new_cluster.id])
    if hasattr(session, "flush"):
        await session.flush()
    return {
        "status": "split",
        "source_event_id": source.id,
        "new_event_id": new_cluster.id,
        "moved_items": len(selected_items),
        "event_cluster_embeddings_deleted": embeddings_deleted,
    }


async def compact_archived_events(
    session: AsyncSession,
    *,
    older_than: datetime,
    dry_run: bool = True,
    limit: int = 500,
) -> dict[str, object]:
    if hasattr(session, "clusters"):
        clusters = [
            cluster
            for cluster in session.clusters.values()
            if cluster.alert_level == "archive_only"
            and cluster.created_at < older_than
            and cluster.compacted_at is None
        ][:limit]
    else:
        clusters = list(
            (
                await session.scalars(
                    select(EventCluster)
                    .where(EventCluster.alert_level == "archive_only")
                    .where(EventCluster.created_at < older_than)
                    .where(EventCluster.compacted_at.is_(None))
                    .order_by(EventCluster.created_at.asc())
                    .limit(limit)
                )
            ).all()
        )
    if dry_run:
        return {"status": "dry_run", "eligible": len(clusters), "compacted": 0}
    cluster_ids = [cluster.id for cluster in clusters]
    for cluster in clusters:
        cluster.archive_summary = {
            "id": cluster.id,
            "canonical_headline": cluster.canonical_headline,
            "summary": cluster.summary,
            "regions": cluster.regions,
            "asset_classes": cluster.asset_classes,
            "affected_entities": cluster.affected_entities,
            "affected_tickers": cluster.affected_tickers,
            "source_count": cluster.source_count,
            "final_score": cluster.final_score,
        }
        cluster.compacted_at = utcnow()
    event_embeddings_deleted = await _delete_cluster_embeddings(session, cluster_ids)
    news_embeddings_deleted = 0
    if cluster_ids:
        news_ids = select(EventClusterItem.news_item_id).where(
            EventClusterItem.event_cluster_id.in_(cluster_ids)
        )
        result = await session.execute(
            delete(NewsItemEmbedding).where(NewsItemEmbedding.news_item_id.in_(news_ids))
        )
        news_embeddings_deleted = _result_rowcount(result)
    return {
        "status": "compacted",
        "eligible": len(clusters),
        "compacted": len(clusters),
        "event_cluster_embeddings_deleted": event_embeddings_deleted,
        "news_item_embeddings_deleted": news_embeddings_deleted,
    }
