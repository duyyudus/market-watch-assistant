from datetime import UTC, datetime

from bot_worker.events import (
    EventCandidate,
    VectorClusterCandidate,
    cluster_candidates,
    is_vector_cluster_attachable,
    vector_similarity_score,
)


def test_cluster_candidates_groups_related_titles_with_entity_overlap() -> None:
    candidates = [
        EventCandidate(
            news_id="news_1",
            title="Oil jumps after tanker incident near Hormuz",
            source_score=75,
            entities=["oil", "hormuz"],
            region="global",
            asset_classes=["commodity"],
            published_at=datetime(2026, 5, 25, 3, tzinfo=UTC),
        ),
        EventCandidate(
            news_id="news_2",
            title="Brent rises as Hormuz shipping risks increase",
            source_score=70,
            entities=["brent", "hormuz"],
            region="global",
            asset_classes=["commodity"],
            published_at=datetime(2026, 5, 25, 4, tzinfo=UTC),
        ),
    ]

    clusters = cluster_candidates(candidates)

    assert len(clusters) == 1
    assert clusters[0].source_count == 2
    assert clusters[0].top_source_score == 75


def test_cluster_candidates_groups_similar_bitcoin_options_titles_without_filler_entities() -> None:
    candidates = [
        EventCandidate(
            news_id="news_1",
            title="Bitcoin options are coming to Nasdaq. Here's what it means for you.",
            source_score=75,
            entities=["Bitcoin"],
            region="crypto",
            asset_classes=["crypto"],
            published_at=datetime(2026, 5, 25, 3, tzinfo=UTC),
        ),
        EventCandidate(
            news_id="news_2",
            title="Bitcoin trades above $110,000 as Nasdaq prepares options launch",
            source_score=70,
            entities=["Bitcoin"],
            region="crypto",
            asset_classes=["crypto"],
            published_at=datetime(2026, 5, 25, 4, tzinfo=UTC),
        ),
    ]

    clusters = cluster_candidates(candidates)

    assert len(clusters) == 1
    assert clusters[0].entities == {"Bitcoin"}
    assert not ({"are", "above", "trades", "options"} & clusters[0].entities)


def test_vector_cluster_attach_policy_accepts_strict_compatible_match() -> None:
    candidate = VectorClusterCandidate(
        cluster_id="evt_1",
        similarity=0.89,
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["hormuz", "oil"],
    )

    assert is_vector_cluster_attachable(
        candidate,
        item_region="us",
        item_asset_classes=["commodity"],
        item_entities=["hormuz", "brent"],
        min_similarity=0.88,
    )
    assert vector_similarity_score(candidate.similarity) == 89


def test_vector_cluster_attach_policy_rejects_low_similarity() -> None:
    candidate = VectorClusterCandidate(
        cluster_id="evt_1",
        similarity=0.87,
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["hormuz"],
    )

    assert not is_vector_cluster_attachable(
        candidate,
        item_region="global",
        item_asset_classes=["commodity"],
        item_entities=["hormuz"],
        min_similarity=0.88,
    )


def test_vector_cluster_attach_policy_rejects_unrelated_asset_class() -> None:
    candidate = VectorClusterCandidate(
        cluster_id="evt_1",
        similarity=0.93,
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["hormuz"],
    )

    assert not is_vector_cluster_attachable(
        candidate,
        item_region="global",
        item_asset_classes=["equity"],
        item_entities=["hormuz"],
        min_similarity=0.88,
    )


def test_vector_cluster_attach_policy_rejects_entity_mismatch_when_both_have_entities() -> None:
    candidate = VectorClusterCandidate(
        cluster_id="evt_1",
        similarity=0.93,
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["hormuz"],
    )

    assert not is_vector_cluster_attachable(
        candidate,
        item_region="global",
        item_asset_classes=["commodity"],
        item_entities=["fed"],
        min_similarity=0.88,
    )


def test_vector_cluster_attach_policy_allows_missing_entities_with_strict_gates() -> None:
    candidate = VectorClusterCandidate(
        cluster_id="evt_1",
        similarity=0.93,
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=[],
    )

    assert is_vector_cluster_attachable(
        candidate,
        item_region="global",
        item_asset_classes=["commodity"],
        item_entities=[],
        min_similarity=0.88,
    )
