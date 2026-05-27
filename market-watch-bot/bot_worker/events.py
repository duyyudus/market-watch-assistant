from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher


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


@dataclass
class EventClusterDraft:
    canonical_headline: str
    news_ids: list[str] = field(default_factory=list)
    entities: set[str] = field(default_factory=set)
    tickers: set[str] = field(default_factory=set)
    regions: set[str] = field(default_factory=set)
    asset_classes: set[str] = field(default_factory=set)
    source_count: int = 0
    top_source_score: int = 0


@dataclass(frozen=True)
class VectorClusterCandidate:
    cluster_id: str
    similarity: float
    regions: list[str]
    asset_classes: list[str]
    affected_entities: list[str]


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()


def _normalized_set(values: list[str]) -> set[str]:
    return {value.casefold() for value in values if value}


def _entity_overlap(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    return bool({item.casefold() for item in left} & {item.casefold() for item in right})


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

    candidate_entities = _normalized_set(candidate.affected_entities)
    item_entity_set = _normalized_set(item_entities)
    if candidate_entities and item_entity_set:
        return bool(candidate_entities & item_entity_set)

    return True


def cluster_candidates(candidates: list[EventCandidate]) -> list[EventClusterDraft]:
    clusters: list[EventClusterDraft] = []
    for candidate in candidates:
        candidate_entities = set(candidate.entities)
        target: EventClusterDraft | None = None
        for cluster in clusters:
            title_related = _similarity(candidate.title, cluster.canonical_headline) >= 0.45
            entity_related = _entity_overlap(candidate_entities, cluster.entities)
            compatible = candidate.region in cluster.regions or bool(
                set(candidate.asset_classes) & cluster.asset_classes
            )
            if compatible and (title_related or entity_related):
                target = cluster
                break
        if target is None:
            target = EventClusterDraft(canonical_headline=candidate.title)
            clusters.append(target)
        target.news_ids.append(candidate.news_id)
        target.entities.update(candidate_entities)
        target.tickers.update(candidate.tickers)
        target.regions.add(candidate.region)
        target.asset_classes.update(candidate.asset_classes)
        target.source_count += 1
        target.top_source_score = max(target.top_source_score, candidate.source_score)
    return clusters
