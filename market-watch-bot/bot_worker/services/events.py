from __future__ import annotations

from collections.abc import Callable
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
    WEAK_SAME_EVENT_REASONS,
    EventCandidate,
    EventClusterDraft,
    SameEventDecision,
    SameEventDecisionKind,
    VectorClusterCandidate,
    _compatible_context,
    _cosine,
    _specific_entity_set,
    classify_same_event,
    coherence_outlier_indices,
    is_vector_cluster_attachable,
    vector_similarity_score,
)
from bot_worker.normalize import content_hash
from bot_worker.scoring import (
    AlertThresholds,
    ScoreInput,
    decide_alert,
    market_impact_score,
    score_event,
)
from bot_worker.services.embeddings import embed_event_cluster, embed_event_clusters
from bot_worker.services.llm import (
    LLMClusterOutcome,
    evaluate_llm_cluster_decision,
    resolve_llm_cluster_decision,
)
from bot_worker.services.watchlists import (
    news_item_entities,
    news_item_primary_subjects,
    news_item_tickers,
    tier_for_entities,
    watchlist_entries,
)
from bot_worker.watchlist import WatchlistEntry, match_watchlist, symbols_for_entities
from common.llm import LLMConfig


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


# Item<->item vector grouping uses a higher cosine floor than the live item<->cluster
# attach: there is no cluster-level entity context to lean on here, so we demand near
# duplicates to avoid false merges. Matches the spirit of is_vector_cluster_attachable's
# 0.94 no-entity floor while staying configurable from the operator's attach threshold.
RECLUSTER_VECTOR_MIN_SIMILARITY = 0.9


async def vector_item_neighbors(
    session: AsyncSession,
    item_ids: list[str],
    *,
    config: EmbeddingConfig,
    min_similarity: float,
) -> dict[str, set[str]]:
    """Build an item<->item similarity graph among ``item_ids`` using pgvector.

    Returns a symmetric adjacency map ``news_id -> {similar news_id, ...}`` containing
    only pairs whose cosine similarity is at least ``min_similarity``. Items without an
    embedding (or below threshold) simply have no edges. A single self-join lets
    Postgres compute the distances in C rather than shipping vectors to Python.
    """
    neighbors: dict[str, set[str]] = {}
    if not item_ids:
        return neighbors
    max_distance = 1.0 - min_similarity
    stmt = sql_text(
        """
        SELECT a.news_item_id AS a_id, b.news_item_id AS b_id
        FROM news_item_embeddings a
        JOIN news_item_embeddings b
          ON b.news_item_id <> a.news_item_id
         AND b.news_item_id = ANY(:item_ids)
         AND b.provider = a.provider
         AND b.embedding_model = a.embedding_model
         AND b.embedding_version = a.embedding_version
         AND b.dimensions = a.dimensions
        WHERE a.news_item_id = ANY(:item_ids)
          AND a.provider = :provider
          AND a.embedding_model = :model
          AND a.embedding_version = :version
          AND a.dimensions = :dimensions
          AND (a.vector <=> b.vector) <= :max_distance
        """
    )
    rows = (
        await session.execute(
            stmt,
            {
                "item_ids": item_ids,
                "provider": config.provider,
                "model": config.model,
                "version": config.version,
                "dimensions": config.dimensions,
                "max_distance": max_distance,
            },
        )
    ).all()
    for row in rows:
        values = row._mapping
        left = values["a_id"]
        right = values["b_id"]
        neighbors.setdefault(left, set()).add(right)
        neighbors.setdefault(right, set()).add(left)
    return neighbors


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
    cluster.market_impact_score = market_impact_score(score)
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
    primary_entities: list[str],
    primary_tickers: list[str],
    similarity: float,
    watch_entries: list[WatchlistEntry],
    decision_metadata: dict[str, object] | None = None,
    embedding_config: EmbeddingConfig | None = None,
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
    cluster.affected_entities = sorted(set(cluster.affected_entities or []) | set(primary_entities))
    cluster.affected_tickers = sorted(set(cluster.affected_tickers or []) | set(primary_tickers))
    cluster.source_count += 1
    if item.source_score >= 75:
        cluster.high_quality_source_count = int(cluster.high_quality_source_count or 0) + 1
    cluster.top_source_score = max(cluster.top_source_score, item.source_score)
    _rescore_cluster(cluster, watch_entries)
    # The cluster's text (headline/entities/regions) just changed, so its embedding is
    # stale. Recompute it in place (compute-then-swap) rather than deleting and waiting
    # for the next pipeline embed pass: a cluster with no embedding row is invisible to
    # vector attach, so a later item in this same batch could miss it and spawn a
    # duplicate cluster. When no embedding provider is configured, fall back to dropping
    # the stale row.
    if embedding_config is not None:
        await embed_event_cluster(session, cluster, config=embedding_config)
    else:
        await session.execute(
            delete(EventClusterEmbedding).where(
                EventClusterEmbedding.event_cluster_id == cluster.id
            )
        )


async def _candidate_from_item(
    session: AsyncSession,
    item: NormalizedNewsItem,
    watch_entries: list[WatchlistEntry],
) -> EventCandidate:
    matches = match_watchlist(f"{item.title} {item.snippet or ''}", watch_entries)
    stored_entities = await news_item_entities(session, item.id)
    stored_tickers = await news_item_tickers(session, item.id)
    stored_primary_entities, stored_primary_tickers = await news_item_primary_subjects(
        session, item.id
    )
    entities = stored_entities or [match.name for match in matches]
    # Tickers come from two safe sources: tickers the LLM attached to entities, and
    # watchlist symbols resolved from the LLM-recognized entity names (e.g.
    # "Vingroup" -> VIC). Only genuine LLM entities feed the watchlist mapping;
    # the title-substring fallback names are excluded so we never attach a symbol
    # from a naive word match.
    tickers = sorted(
        set(stored_tickers) | set(symbols_for_entities(stored_entities, watch_entries))
    )
    # Primary-subject subsets drive affected_*. When the LLM extracted entities, only
    # its primary picks count (a "SpaceX tops Apple/Amazon" story has no primary AAPL).
    # With no extraction at all, the title's watchlist matches are the de-facto subject.
    if stored_entities:
        primary_entities = stored_primary_entities
        primary_tickers = sorted(
            set(stored_primary_tickers)
            | set(symbols_for_entities(stored_primary_entities, watch_entries))
        )
    else:
        primary_entities = entities
        primary_tickers = tickers
    return EventCandidate(
        news_id=item.id,
        title=item.title,
        source_score=item.source_score,
        entities=entities,
        tickers=tickers,
        primary_entities=primary_entities,
        primary_tickers=primary_tickers,
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
        primary_entities=list(draft.primary_entities),
        primary_tickers=list(draft.primary_tickers),
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
        affected_entities=sorted(draft.primary_entities),
        affected_tickers=sorted(draft.primary_tickers),
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
    draft.primary_entities.update(candidate.primary_entities)
    draft.primary_tickers.update(candidate.primary_tickers)
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


async def _load_item_vectors(
    session: AsyncSession,
    item_ids: list[str],
    *,
    config: EmbeddingConfig,
) -> dict[str, list[float]]:
    """Fetch embedding vectors for ``item_ids`` matching the active embedding config."""
    if not item_ids:
        return {}
    rows = (
        await session.execute(
            select(NewsItemEmbedding.news_item_id, NewsItemEmbedding.vector).where(
                NewsItemEmbedding.news_item_id.in_(item_ids),
                NewsItemEmbedding.provider == config.provider,
                NewsItemEmbedding.embedding_model == config.model,
                NewsItemEmbedding.embedding_version == config.version,
                NewsItemEmbedding.dimensions == config.dimensions,
            )
        )
    ).all()
    return {row[0]: list(row[1]) for row in rows}


async def _eject_coherence_outliers(
    session: AsyncSession,
    drafts: list[EventClusterDraft],
    candidates: list[EventCandidate],
    *,
    embedding_config: EmbeddingConfig,
    llm_config: LLMConfig | None,
) -> tuple[list[EventClusterDraft], int, int]:
    """Re-check weak-branch members against each cluster's embedding coherence.

    A member that joined via a title/entity-only branch but sits far below its
    cluster's coherent core (see ``coherence_outlier_indices``) is routed back through
    LLM arbitration. If the LLM declines -- or cannot run -- the member is split into
    its own cluster. Strong joins (ticker, near-duplicate) are never revisited.
    """
    if not any(
        len(draft.news_ids) >= 3 for draft in drafts
    ):
        return drafts, 0, 0
    cand_by_id = {candidate.news_id: candidate for candidate in candidates}
    all_ids = [news_id for draft in drafts for news_id in draft.news_ids]
    vectors_by_id = await _load_item_vectors(session, all_ids, config=embedding_config)

    rebuilt: list[EventClusterDraft] = []
    llm_decisions = 0
    llm_splits = 0
    for draft in drafts:
        member_ids = list(draft.news_ids)
        guarded = {
            index
            for index, news_id in enumerate(member_ids)
            if (draft.item_decision_metadata.get(news_id, {}) or {}).get("reason")
            in WEAK_SAME_EVENT_REASONS
        }
        if not guarded:
            rebuilt.append(draft)
            continue
        member_vectors = [vectors_by_id.get(news_id) for news_id in member_ids]
        outlier_indices = coherence_outlier_indices(member_vectors, guarded=guarded)
        if not outlier_indices:
            rebuilt.append(draft)
            continue

        kept_ids = [
            news_id
            for index, news_id in enumerate(member_ids)
            if index not in outlier_indices
        ]
        ejected: list[str] = []
        for index in sorted(outlier_indices):
            news_id = member_ids[index]
            candidate = cand_by_id.get(news_id)
            kept_candidates = [cand_by_id[n] for n in kept_ids if n in cand_by_id]
            outcome = LLMClusterOutcome.DISABLED
            if candidate is not None and kept_candidates and llm_config is not None:
                kept_draft = _rebuild_draft(draft, kept_candidates)
                best = max(
                    (
                        _vector_cosine(member_vectors[index], member_vectors[k])
                        for k, n in enumerate(member_ids)
                        if n in kept_ids and member_vectors[index] and member_vectors[k]
                    ),
                    default=0.0,
                )
                outcome = await evaluate_llm_cluster_decision(
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
                    cluster=_draft_cluster(kept_draft),
                    similarity=best,
                    config=llm_config,
                    entities=candidate.entities,
                    tickers=candidate.tickers,
                )
            if outcome in (LLMClusterOutcome.ATTACH, LLMClusterOutcome.REJECT):
                llm_decisions += 1
            # Fail safe: only split on an explicit REJECT verdict. If the LLM is
            # unavailable (disabled or provider error), keep the deterministic merge
            # intact rather than splitting on a transient outage.
            if outcome is LLMClusterOutcome.REJECT:
                ejected.append(news_id)
                llm_splits += 1
            else:
                kept_ids.append(news_id)

        if not ejected:
            rebuilt.append(draft)
            continue
        ordered_kept = [n for n in member_ids if n in set(kept_ids)]
        rebuilt.append(
            _rebuild_draft(
                draft,
                [cand_by_id[n] for n in ordered_kept if n in cand_by_id],
            )
        )
        for news_id in ejected:
            candidate = cand_by_id.get(news_id)
            if candidate is None:
                continue
            split = EventClusterDraft(canonical_headline=candidate.title)
            original = draft.item_decision_metadata.get(news_id, {}) or {}
            _add_candidate_to_draft_with_metadata(
                split,
                candidate,
                metadata={
                    "decision_source": "coherence_guard",
                    "decision": "split",
                    "reason": "embedding_outlier",
                    "prior_reason": original.get("reason"),
                },
            )
            rebuilt.append(split)
    return rebuilt, llm_decisions, llm_splits


def _rebuild_draft(
    template: EventClusterDraft,
    members: list[EventCandidate],
) -> EventClusterDraft:
    """Reconstruct a draft from a subset of its members, preserving join metadata."""
    fresh = EventClusterDraft(canonical_headline=template.canonical_headline)
    for candidate in members:
        metadata = template.item_decision_metadata.get(candidate.news_id) or {
            "decision_source": "seed",
            "decision": "seed",
        }
        _add_candidate_to_draft_with_metadata(fresh, candidate, metadata=metadata)
    return fresh


def _vector_cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    return _cosine(left, right)


async def _cluster_candidates_with_llm_arbitration(
    session: AsyncSession,
    candidates: list[EventCandidate],
    *,
    llm_config: LLMConfig | None,
    embedding_config: EmbeddingConfig | None = None,
    vector_neighbors: dict[str, set[str]] | None = None,
) -> tuple[list[EventClusterDraft], int, int]:
    drafts: list[EventClusterDraft] = []
    llm_decisions = 0
    llm_attaches = 0
    for candidate in candidates:
        target: EventClusterDraft | None = None
        metadata: dict[str, object] | None = None
        target_decision: SameEventDecision | None = None
        ambiguous_matches: list[tuple[EventClusterDraft, SameEventDecision]] = []
        for draft in drafts:
            decision = classify_same_event(candidate, _draft_candidate(draft))
            if decision.kind is SameEventDecisionKind.STRONG_SAME_EVENT:
                if (
                    target_decision is None
                    or decision.title_similarity > target_decision.title_similarity
                ):
                    target = draft
                    target_decision = decision
                continue
            if decision.kind is not SameEventDecisionKind.AMBIGUOUS:
                continue
            ambiguous_matches.append((draft, decision))
        if target is not None and target_decision is not None:
            metadata = {
                "decision_source": "deterministic",
                "decision": target_decision.kind.value,
                "reason": target_decision.reason,
                "title_similarity": round(target_decision.title_similarity, 4),
                "entity_overlap": target_decision.entity_overlap,
                "ticker_overlap": target_decision.ticker_overlap,
            }
        if target is None:
            for draft, decision in ambiguous_matches:
                if target is not None:
                    break
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
    if vector_neighbors:
        drafts = _merge_drafts_by_vector(drafts, vector_neighbors)
    if embedding_config is not None:
        drafts, guard_decisions, _ = await _eject_coherence_outliers(
            session,
            drafts,
            candidates,
            embedding_config=embedding_config,
            llm_config=llm_config,
        )
        llm_decisions += guard_decisions
    return drafts, llm_decisions, llm_attaches


def _combine_drafts(members: list[EventClusterDraft]) -> EventClusterDraft:
    """Fold several drafts into one, keeping the largest as the headline/base."""
    members = sorted(
        members,
        key=lambda draft: (len(draft.news_ids), draft.top_source_score),
        reverse=True,
    )
    base = members[0]
    ranks = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
    for other in members[1:]:
        base.news_ids.extend(other.news_ids)
        base.item_decision_metadata.update(other.item_decision_metadata)
        base.entities |= other.entities
        base.tickers |= other.tickers
        base.primary_entities |= other.primary_entities
        base.primary_tickers |= other.primary_tickers
        base.regions |= other.regions
        base.asset_classes |= other.asset_classes
        base.source_count += other.source_count
        base.high_quality_source_count += other.high_quality_source_count
        base.top_source_score = max(base.top_source_score, other.top_source_score)
        if other.watchlist_tier is not None and ranks.get(other.watchlist_tier, 0) > ranks.get(
            base.watchlist_tier or "", 0
        ):
            base.watchlist_tier = other.watchlist_tier
    return base


def _merge_drafts_by_vector(
    drafts: list[EventClusterDraft],
    vector_neighbors: dict[str, set[str]],
) -> list[EventClusterDraft]:
    """Union drafts whose members are near-duplicates by embedding.

    Item-level lexical matching already gives every item a home in its own draft, so a
    cross-cluster paraphrase can only be caught by merging the *drafts* those two items
    landed in. Two drafts are merged when some vector edge links a member of one to a
    member of the other, their region/asset context is compatible, AND they share a
    specific entity. The entity requirement is what keeps near-duplicate *boilerplate*
    (e.g. templated "Net Asset Value" filings for different funds, which score >0.95
    cosine) from collapsing into one event: same template, but different fund names.
    """
    if len(drafts) < 2:
        return drafts
    parent = list(range(len(drafts)))
    entity_sets = [_specific_entity_set(list(draft.entities)) for draft in drafts]

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    draft_of = {news_id: index for index, draft in enumerate(drafts) for news_id in draft.news_ids}
    for news_id, neighbors in vector_neighbors.items():
        left = draft_of.get(news_id)
        if left is None:
            continue
        for other in neighbors:
            right = draft_of.get(other)
            if right is None or find(left) == find(right):
                continue
            if not (entity_sets[left] & entity_sets[right]):
                continue
            if _compatible_context(
                _draft_candidate(drafts[left]), _draft_candidate(drafts[right])
            ):
                parent[find(right)] = find(left)
    groups: dict[int, list[EventClusterDraft]] = {}
    for index, draft in enumerate(drafts):
        groups.setdefault(find(index), []).append(draft)
    return [_combine_drafts(members) for members in groups.values()]


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
    cluster.affected_entities = sorted(draft.primary_entities)
    cluster.affected_tickers = sorted(draft.primary_tickers)
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
    cluster.market_impact_score = market_impact_score(score)
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


def _match_drafts_to_clusters(
    drafts: list[EventClusterDraft],
    clusters: list[EventCluster],
    news_origin: dict[str, str],
) -> tuple[list[tuple[EventCluster | None, EventClusterDraft]], set[str]]:
    """Pair each regrouped draft with the existing cluster it shares the most news
    items with, so cluster identity (id, first_seen_at, score/alert history) follows
    content instead of list position.

    Greedy: larger drafts choose first, each existing cluster is claimed at most once,
    ties broken toward the more recently updated cluster. A draft that matches no
    available cluster pairs with ``None`` so a fresh cluster is created on apply -- this
    is what lets a split produce more clusters than it started with without orphaning
    any news item.
    """
    cluster_by_id = {cluster.id: cluster for cluster in clusters}
    cluster_rank = {cluster.id: index for index, cluster in enumerate(clusters)}
    assignments: list[tuple[EventCluster | None, EventClusterDraft]] = []
    claimed: set[str] = set()
    ordered = sorted(
        drafts,
        key=lambda draft: (len(draft.news_ids), draft.source_count),
        reverse=True,
    )
    for draft in ordered:
        overlap: dict[str, int] = {}
        for news_id in draft.news_ids:
            origin = news_origin.get(news_id)
            if origin is not None and origin not in claimed:
                overlap[origin] = overlap.get(origin, 0) + 1
        if overlap:
            best = min(
                overlap,
                key=lambda cid: (-overlap[cid], cluster_rank.get(cid, len(clusters))),
            )
            claimed.add(best)
            assignments.append((cluster_by_id[best], draft))
        else:
            assignments.append((None, draft))
    return assignments, claimed


async def recompute_affected_from_primary_entities(
    session: AsyncSession,
    *,
    dry_run: bool = True,
    limit: int | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, int | str]:
    """Rebuild every cluster's affected_tickers/affected_entities from its members'
    primary-subject mentions only, dropping comparison/peer mentions that leaked in
    before the primary-subject filter existed. Makes no LLM calls. Dry-run by default.
    """
    watch_entries = await watchlist_entries(session)
    stmt = select(EventCluster).order_by(EventCluster.last_updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    clusters = list((await session.scalars(stmt)).all())
    changed = 0
    for index, cluster in enumerate(clusters, start=1):
        if progress is not None:
            progress("recomputing", index, len(clusters))
        member_ids = list(
            (
                await session.scalars(
                    select(EventClusterItem.news_item_id).where(
                        EventClusterItem.event_cluster_id == cluster.id
                    )
                )
            ).all()
        )
        primary_entities: set[str] = set()
        primary_tickers: set[str] = set()
        for news_item_id in member_ids:
            names, tickers = await news_item_primary_subjects(session, news_item_id)
            primary_entities.update(names)
            primary_tickers.update(tickers)
            primary_tickers.update(symbols_for_entities(names, watch_entries))
        new_entities = sorted(primary_entities)
        new_tickers = sorted(primary_tickers)
        if new_entities == cluster.affected_entities and new_tickers == cluster.affected_tickers:
            continue
        changed += 1
        if not dry_run:
            cluster.affected_entities = new_entities
            cluster.affected_tickers = new_tickers
    if not dry_run:
        await session.flush()
    return {
        "clusters_scanned": len(clusters),
        "clusters_changed": changed,
        "mode": "dry_run" if dry_run else "applied",
    }


async def recluster_recent_event_clusters(
    session: AsyncSession,
    *,
    since: datetime,
    dry_run: bool = True,
    limit: int | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    llm_config: LLMConfig | None = None,
    embedding_config: EmbeddingConfig | None = None,
    use_vector_signal: bool = False,
) -> dict[str, int | str]:
    # ``embedding_config`` being set means embeddings are usable, which is enough to
    # regenerate the cluster embeddings recluster invalidates on apply (lifecycle hygiene,
    # always done). ``use_vector_signal`` is the separate opt-in for *also* using stored
    # vectors as a grouping signal during the regroup.
    # Exclude already-stale clusters: they are emptied husks whose last_updated_at is
    # re-bumped each time they are re-staled, which would otherwise keep them in every
    # window forever, inflating affected/stale counts with no real work. --since scopes the
    # run; --limit is an optional cap (unbounded by default).
    cluster_stmt = (
        select(EventCluster.id)
        .where(EventCluster.last_updated_at >= since)
        .where(EventCluster.status != "stale")
        .order_by(EventCluster.last_updated_at.desc())
    )
    if limit is not None:
        cluster_stmt = cluster_stmt.limit(limit)
    cluster_ids = list((await session.scalars(cluster_stmt)).all())
    if not cluster_ids:
        return {
            "status": "dry_run" if dry_run else "reclustered",
            "affected_clusters": 0,
            "news_items": 0,
            "new_clusters": 0,
            "created_clusters": 0,
            "reused_clusters": 0,
            "stale_clusters": 0,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
            "event_cluster_embeddings_written": 0,
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
            "created_clusters": 0,
            "reused_clusters": 0,
            "stale_clusters": 0,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
            "event_cluster_embeddings_written": 0,
        }

    watch_entries = await watchlist_entries(session)
    candidates = []
    for index, item in enumerate(items, start=1):
        candidates.append(await _candidate_from_item(session, item, watch_entries))
        if progress is not None:
            progress("scanning clustered items", index, len(items))
    vector_neighbors: dict[str, set[str]] | None = None
    if embedding_config is not None and use_vector_signal:
        vector_neighbors = await vector_item_neighbors(
            session,
            [candidate.news_id for candidate in candidates],
            config=embedding_config,
            min_similarity=max(
                embedding_config.cluster_attach_min_similarity,
                RECLUSTER_VECTOR_MIN_SIMILARITY,
            ),
        )
    drafts, _, _ = await _cluster_candidates_with_llm_arbitration(
        session,
        candidates,
        llm_config=llm_config,
        embedding_config=embedding_config,
        vector_neighbors=vector_neighbors,
    )
    membership = list(
        (
            await session.scalars(
                select(EventClusterItem).where(
                    EventClusterItem.event_cluster_id.in_(cluster_ids)
                )
            )
        ).all()
    )
    news_origin = {row.news_item_id: row.event_cluster_id for row in membership}
    assignments, claimed_cluster_ids = _match_drafts_to_clusters(drafts, clusters, news_origin)
    created_clusters = sum(1 for cluster, _ in assignments if cluster is None)
    reused_clusters = len(claimed_cluster_ids)
    stale_clusters = len(clusters) - reused_clusters
    if dry_run:
        return {
            "status": "dry_run",
            "affected_clusters": len(cluster_ids),
            "news_items": len(items),
            "new_clusters": len(drafts),
            "created_clusters": created_clusters,
            "reused_clusters": reused_clusters,
            "stale_clusters": stale_clusters,
            "event_cluster_items_deleted": 0,
            "event_cluster_embeddings_deleted": 0,
            "event_cluster_embeddings_written": 0,
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
    touched_clusters: list[EventCluster] = []
    for cluster, draft in assignments:
        if cluster is None:
            cluster = EventCluster(canonical_headline=draft.canonical_headline)
            session.add(cluster)
        _update_cluster_from_draft(cluster, draft, watch_entries)
        await session.flush()
        for news_id in draft.news_ids:
            session.add(
                EventClusterItem(
                    event_cluster_id=cluster.id,
                    news_item_id=news_id,
                    decision_metadata=draft.item_decision_metadata.get(news_id),
                )
            )
        touched_clusters.append(cluster)
    for cluster in clusters:
        if cluster.id not in claimed_cluster_ids:
            _mark_cluster_stale(cluster)

    # Recluster just rewrote membership and headlines, so the bulk delete above left the
    # surviving clusters with no embedding. Regenerate them now (when an embedding
    # provider is configured) instead of leaving a gap until the next pipeline embed pass:
    # an un-embedded cluster is invisible to live vector attach, so newly ingested items
    # could miss it and spawn duplicates before the lazy re-embed catches up.
    embeddings_written = 0
    if embedding_config is not None:
        embeddings_written = await embed_event_clusters(
            session, touched_clusters, config=embedding_config, progress=progress
        )

    return {
        "status": "reclustered",
        "affected_clusters": len(cluster_ids),
        "news_items": len(items),
        "new_clusters": len(drafts),
        "created_clusters": created_clusters,
        "reused_clusters": reused_clusters,
        "stale_clusters": stale_clusters,
        "event_cluster_items_deleted": items_deleted,
        "event_cluster_embeddings_deleted": embeddings_deleted,
        "event_cluster_embeddings_written": embeddings_written,
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
        .where(NormalizedNewsItem.processing_status == "normalized")
        .where(NormalizedNewsItem.id.not_in(existing_news))
        .order_by(
            func.coalesce(
                NormalizedNewsItem.published_at,
                NormalizedNewsItem.fetched_at,
                NormalizedNewsItem.created_at,
            ).desc()
        )
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
                    primary_entities=candidate.primary_entities,
                    primary_tickers=candidate.primary_tickers,
                    similarity=vector_candidate.similarity,
                    watch_entries=watch_entries,
                    decision_metadata={
                        "decision_source": "vector",
                        "decision": "strong_same_event",
                        "similarity": round(vector_candidate.similarity, 4),
                    },
                    embedding_config=embedding_config,
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
                    primary_entities=candidate.primary_entities,
                    primary_tickers=candidate.primary_tickers,
                    similarity=vector_candidate.similarity,
                    watch_entries=watch_entries,
                    decision_metadata={
                        "decision_source": "llm",
                        "decision": "same_event",
                        "similarity": round(vector_candidate.similarity, 4),
                        "llm_attempted": attempted,
                    },
                    embedding_config=embedding_config,
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
            embedding_config=embedding_config,
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
            affected_entities=sorted(draft.primary_entities),
            affected_tickers=sorted(draft.primary_tickers),
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
        cluster.market_impact_score = market_impact_score(score)
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
