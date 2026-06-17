from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import StrEnum


@dataclass(frozen=True)
class EventCandidate:
    news_id: str
    title: str
    source_score: int
    entities: list[str]
    region: str
    asset_classes: list[str]
    published_at: datetime | None
    tickers: list[str] = field(default_factory=list)
    # Primary-subject mentions only. `entities`/`tickers` carry every mention (used
    # for clustering/merge overlap); the `primary_*` subsets are what define a
    # cluster's affected_tickers/affected_entities so comparison mentions don't leak in.
    primary_entities: list[str] = field(default_factory=list)
    primary_tickers: list[str] = field(default_factory=list)
    watchlist_tier: str | None = None
    source_name: str = ""
    source_type: str = ""
    snippet: str | None = None


@dataclass
class EventClusterDraft:
    canonical_headline: str
    news_ids: list[str] = field(default_factory=list)
    item_decision_metadata: dict[str, dict[str, object]] = field(default_factory=dict)
    entities: set[str] = field(default_factory=set)
    tickers: set[str] = field(default_factory=set)
    primary_entities: set[str] = field(default_factory=set)
    primary_tickers: set[str] = field(default_factory=set)
    regions: set[str] = field(default_factory=set)
    asset_classes: set[str] = field(default_factory=set)
    source_count: int = 0
    high_quality_source_count: int = 0
    top_source_score: int = 0
    watchlist_tier: str | None = None


@dataclass(frozen=True)
class VectorClusterCandidate:
    cluster_id: str
    similarity: float
    regions: list[str]
    asset_classes: list[str]
    affected_entities: list[str]


class SameEventDecisionKind(StrEnum):
    STRONG_SAME_EVENT = "strong_same_event"
    AMBIGUOUS = "ambiguous"
    REJECT = "reject"


@dataclass(frozen=True)
class SameEventDecision:
    kind: SameEventDecisionKind
    title_similarity: float
    entity_overlap: list[str]
    ticker_overlap: list[str]
    reason: str


PUBLISHER_ENTITIES = {
    "ap",
    "associated press",
    "bloomberg",
    "morning bid",
    "reuters",
}
BROAD_ENTITIES = {
    "euro",
    "euro (eur)",
    "federal reserve",
    "global markets",
    "investors",
    "japanese yen",
    "japanese yen (jpy)",
    "markets",
    "tech giants",
    "united states",
    "us dollar",
    "us dollar (usd)",
}
# Trailing publisher attribution (" - Reuters", " – Financial Times", "| Bloomberg.com").
# Stripped before comparison so two unrelated articles from the same outlet do not
# share publisher tokens or gain inflated character similarity from the common suffix.
TITLE_SOURCE_SUFFIX_RE = re.compile(
    r"\s*[-|–—]\s*"
    r"(reuters|ap|associated press|"
    r"bloomberg(?:\.com)?|bloomberg news|"
    r"financial times|ft\.com|"
    r"cnbc|cnn|"
    r"the wall street journal|wsj|"
    r"the new york times|new york times|nytimes|"
    r"the economist|nikkei asia|nikkei|"
    r"business live)"
    r"\s*$",
    re.IGNORECASE,
)
TITLE_TOKEN_RE = re.compile(r"[^\W_]+")
# Publisher names that may survive when not in trailing position; never topical.
PUBLISHER_TITLE_STOPWORDS = {
    "bloomberg",
    "reuters",
    "cnbc",
    "nikkei",
    "nytimes",
}
# High-frequency Vietnamese function and quantity words (>=4 chars, so the length
# filter does not already drop them). They carry no topical signal, so without this
# unrelated Vietnamese headlines merge on shared filler such as "triệu"/"trong".
VIETNAMESE_TITLE_STOPWORDS = {
    "trong",
    "triệu",
    "đồng",
    "nghìn",
    "ngày",
    "được",
    "không",
    "những",
    "người",
    "cũng",
    "việc",
    "theo",
    "tăng",
    "giảm",
    "thấp",
    "nhất",
    "cùng",
    "trên",
    "dưới",
    "trước",
    "khoảng",
}
TITLE_STOPWORDS = {
    "after",
    "again",
    "amid",
    "annual",
    "brief",
    "could",
    "exclusive",
    "from",
    "have",
    "into",
    "market",
    "markets",
    "more",
    "over",
    "plan",
    "plans",
    "report",
    "reports",
    "says",
    "source",
    "than",
    "that",
    "their",
    "with",
    *PUBLISHER_TITLE_STOPWORDS,
    *VIETNAMESE_TITLE_STOPWORDS,
}


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()


def _normalized_set(values: list[str]) -> set[str]:
    return {value.casefold() for value in values if value}


def _clean_title(value: str) -> str:
    return TITLE_SOURCE_SUFFIX_RE.sub("", value).strip()


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in TITLE_TOKEN_RE.findall(_clean_title(value).casefold())
        if len(token) > 3 and token not in TITLE_STOPWORDS
    }


def _specific_entity_set(values: list[str] | set[str]) -> set[str]:
    return {
        value.casefold()
        for value in values
        if value
        and value.casefold() not in PUBLISHER_ENTITIES
        and value.casefold() not in BROAD_ENTITIES
    }


def _weak_entity_set(values: list[str] | set[str]) -> set[str]:
    return {
        value.casefold()
        for value in values
        if value and value.casefold() in BROAD_ENTITIES
    }


def _compatible_context(left: EventCandidate, right: EventCandidate) -> bool:
    left_assets = {value.casefold() for value in left.asset_classes if value}
    right_assets = {value.casefold() for value in right.asset_classes if value}
    asset_overlap = left_assets & right_assets
    if asset_overlap and asset_overlap != {"global_macro"}:
        return True

    left_region = left.region.casefold()
    right_region = right.region.casefold()
    return (
        left_region
        and left_region == right_region
        and left_region != "global"
        and bool(left_assets or right_assets)
    )


def classify_same_event(candidate: EventCandidate, existing: EventCandidate) -> SameEventDecision:
    title_similarity = _similarity(_clean_title(candidate.title), _clean_title(existing.title))
    candidate_tokens = _title_tokens(candidate.title)
    existing_tokens = _title_tokens(existing.title)
    title_token_overlap = candidate_tokens & existing_tokens
    compatible = _compatible_context(candidate, existing)
    entity_overlap = sorted(
        _specific_entity_set(candidate.entities) & _specific_entity_set(existing.entities)
    )
    weak_entity_overlap = sorted(
        _weak_entity_set(candidate.entities) & _weak_entity_set(existing.entities)
    )

    ticker_overlap = sorted(_normalized_set(candidate.tickers) & _normalized_set(existing.tickers))
    if (
        ticker_overlap
        and compatible
        and (
            title_similarity >= 0.55
            or (
                title_similarity >= 0.38
                and (bool(entity_overlap) or len(title_token_overlap) >= 2)
            )
        )
    ):
        return SameEventDecision(
            kind=SameEventDecisionKind.STRONG_SAME_EVENT,
            title_similarity=title_similarity,
            entity_overlap=entity_overlap,
            ticker_overlap=ticker_overlap,
            reason="ticker_overlap_with_title_support",
        )

    if title_similarity >= 0.45 and len(title_token_overlap) >= 2:
        return SameEventDecision(
            kind=SameEventDecisionKind.STRONG_SAME_EVENT,
            title_similarity=title_similarity,
            entity_overlap=entity_overlap,
            ticker_overlap=ticker_overlap,
            reason="strong_title_topic_overlap",
        )

    if compatible and entity_overlap and (
        title_similarity >= 0.45 or bool(title_token_overlap)
    ):
        return SameEventDecision(
            kind=SameEventDecisionKind.STRONG_SAME_EVENT,
            title_similarity=title_similarity,
            entity_overlap=entity_overlap,
            ticker_overlap=ticker_overlap,
            reason="specific_entity_overlap_with_title_support",
        )

    if compatible and entity_overlap:
        return SameEventDecision(
            kind=SameEventDecisionKind.AMBIGUOUS,
            title_similarity=title_similarity,
            entity_overlap=entity_overlap,
            ticker_overlap=ticker_overlap,
            reason="specific_entity_overlap_without_title_support",
        )

    if compatible and weak_entity_overlap:
        return SameEventDecision(
            kind=SameEventDecisionKind.AMBIGUOUS,
            title_similarity=title_similarity,
            entity_overlap=weak_entity_overlap,
            ticker_overlap=ticker_overlap,
            reason="weak_entity_overlap_requires_arbitration",
        )

    return SameEventDecision(
        kind=SameEventDecisionKind.REJECT,
        title_similarity=title_similarity,
        entity_overlap=[],
        ticker_overlap=[],
        reason="insufficient_same_event_signal",
    )


def vector_similarity_score(similarity: float) -> int:
    return round(similarity * 100)


def is_vector_cluster_attachable(
    candidate: VectorClusterCandidate,
    *,
    item_region: str,
    item_asset_classes: list[str],
    item_entities: list[str],
    min_similarity: float,
) -> bool:
    if candidate.similarity < min_similarity:
        return False

    candidate_regions = _normalized_set(candidate.regions)
    region = item_region.casefold()
    if region not in candidate_regions and "global" not in candidate_regions and region != "global":
        return False

    candidate_asset_classes = _normalized_set(candidate.asset_classes)
    item_asset_class_set = _normalized_set(item_asset_classes)
    if candidate_asset_classes and item_asset_class_set and not (
        candidate_asset_classes & item_asset_class_set
    ):
        return False

    candidate_entities = _specific_entity_set(candidate.affected_entities)
    item_entity_set = _specific_entity_set(item_entities)
    if candidate_entities and item_entity_set:
        return bool(candidate_entities & item_entity_set)

    return candidate.similarity >= max(min_similarity, 0.94)


# Same-event reasons that rest on title/entity surface overlap alone, with no strong
# corroboration (shared ticker, near-duplicate embedding). These are the branches that
# let unrelated articles in when they share boilerplate phrasing or a single incidental
# entity, so they are the ones the embedding-coherence guard re-checks.
WEAK_SAME_EVENT_REASONS = frozenset(
    {
        "strong_title_topic_overlap",
        "specific_entity_overlap_with_title_support",
        "specific_entity_overlap_without_title_support",
        "weak_entity_overlap_requires_arbitration",
    }
)
# Embedding-coherence guard. A weak-branch member is treated as a cluster intruder when
# its best cosine to any cluster-mate is BOTH low in absolute terms AND well below the
# cluster's tightest internal pair. The test is relative to each cluster's own
# coherence, not an absolute floor: a uniformly-loose-but-legitimate cluster keeps its
# members, while a hanger-on on a tight core is ejected. Thresholds were validated
# against the live corpus -- this catches the known false merges at a ~7% link-flag
# rate, whereas an absolute 0.75 floor flagged ~50% of all existing memberships.
COHERENCE_GUARD_MIN_CLUSTER_SIZE = 3
COHERENCE_GUARD_ABS_FLOOR = 0.70
COHERENCE_GUARD_GAP = 0.15


def _cosine(left: list[float], right: list[float]) -> float:
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for a, b in zip(left, right, strict=False):
        dot += a * b
        norm_left += a * a
        norm_right += b * b
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 0.0
    return dot / math.sqrt(norm_left * norm_right)


def coherence_outlier_indices(
    vectors: list[list[float] | None],
    *,
    guarded: set[int],
) -> set[int]:
    """Return indices of cluster members that are embedding-coherence intruders.

    ``vectors`` are the member embeddings (``None`` for members without one), and
    ``guarded`` restricts the test to members joined via a weak same-event branch --
    strong joins (shared ticker, near-duplicate) are never second-guessed.

    A guarded member is an outlier when its maximum cosine to any other member is below
    ``COHERENCE_GUARD_ABS_FLOOR`` and more than ``COHERENCE_GUARD_GAP`` below the
    cluster's tightest internal pair. Clusters smaller than
    ``COHERENCE_GUARD_MIN_CLUSTER_SIZE`` never flag: a pair has no stable core to
    deviate from, so the intruder is indistinguishable from its host.
    """
    n = len(vectors)
    if n < COHERENCE_GUARD_MIN_CLUSTER_SIZE:
        return set()
    pair_cosine: dict[tuple[int, int], float] = {}
    for i in range(n):
        if vectors[i] is None:
            continue
        for j in range(i + 1, n):
            if vectors[j] is None:
                continue
            pair_cosine[(i, j)] = _cosine(vectors[i], vectors[j])
    if not pair_cosine:
        return set()
    cluster_max = max(pair_cosine.values())
    outliers: set[int] = set()
    for i in guarded:
        if i >= n or vectors[i] is None:
            continue
        neighbours = [
            pair_cosine[(min(i, j), max(i, j))]
            for j in range(n)
            if j != i and vectors[j] is not None
        ]
        if not neighbours:
            continue
        best = max(neighbours)
        if best < COHERENCE_GUARD_ABS_FLOOR and best < cluster_max - COHERENCE_GUARD_GAP:
            outliers.add(i)
    return outliers


def _candidate_from_cluster_draft(cluster: EventClusterDraft) -> EventCandidate:
    return EventCandidate(
        news_id="cluster",
        title=cluster.canonical_headline,
        source_score=cluster.top_source_score,
        entities=list(cluster.entities),
        tickers=list(cluster.tickers),
        primary_entities=list(cluster.primary_entities),
        primary_tickers=list(cluster.primary_tickers),
        region=next(iter(cluster.regions), "global"),
        asset_classes=list(cluster.asset_classes),
        published_at=None,
        watchlist_tier=cluster.watchlist_tier,
    )


def cluster_candidates(candidates: list[EventCandidate]) -> list[EventClusterDraft]:
    clusters: list[EventClusterDraft] = []
    for candidate in candidates:
        target: EventClusterDraft | None = None
        target_decision: SameEventDecision | None = None
        for cluster in clusters:
            decision = classify_same_event(candidate, _candidate_from_cluster_draft(cluster))
            if decision.kind is SameEventDecisionKind.STRONG_SAME_EVENT and (
                target_decision is None
                or decision.title_similarity > target_decision.title_similarity
            ):
                target = cluster
                target_decision = decision
        if target is None:
            target = EventClusterDraft(canonical_headline=candidate.title)
            clusters.append(target)
        target.news_ids.append(candidate.news_id)
        target.item_decision_metadata[candidate.news_id] = (
            {
                "decision_source": "deterministic",
                "decision": target_decision.kind.value,
                "reason": target_decision.reason,
                "title_similarity": round(target_decision.title_similarity, 4),
                "entity_overlap": target_decision.entity_overlap,
                "ticker_overlap": target_decision.ticker_overlap,
            }
            if target_decision is not None
            else {"decision_source": "seed", "decision": "seed"}
        )
        target.entities.update(candidate.entities)
        target.tickers.update(candidate.tickers)
        target.primary_entities.update(candidate.primary_entities)
        target.primary_tickers.update(candidate.primary_tickers)
        target.regions.add(candidate.region)
        target.asset_classes.update(candidate.asset_classes)
        target.source_count += 1
        if candidate.source_score >= 75:
            target.high_quality_source_count += 1
        target.top_source_score = max(target.top_source_score, candidate.source_score)
        if candidate.watchlist_tier is not None:
            ranks = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
            current = target.watchlist_tier or "D"
            if ranks.get(candidate.watchlist_tier, 0) > ranks.get(current, 0):
                target.watchlist_tier = candidate.watchlist_tier
    return clusters
