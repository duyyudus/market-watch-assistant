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


@dataclass
class EventClusterDraft:
    canonical_headline: str
    news_ids: list[str] = field(default_factory=list)
    entities: set[str] = field(default_factory=set)
    regions: set[str] = field(default_factory=set)
    asset_classes: set[str] = field(default_factory=set)
    source_count: int = 0
    top_source_score: int = 0


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()


def _entity_overlap(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    return bool({item.casefold() for item in left} & {item.casefold() for item in right})


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
        target.regions.add(candidate.region)
        target.asset_classes.update(candidate.asset_classes)
        target.source_count += 1
        target.top_source_score = max(target.top_source_score, candidate.source_score)
    return clusters
