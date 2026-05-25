from datetime import UTC, datetime

from bot_worker.events import EventCandidate, cluster_candidates


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
