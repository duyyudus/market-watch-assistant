from datetime import UTC, datetime

from bot_worker.db.models import EventCluster, EventClusterItem, NormalizedNewsItem
from bot_worker.events import (
    EventCandidate,
    SameEventDecisionKind,
    VectorClusterCandidate,
    classify_same_event,
    cluster_candidates,
    is_vector_cluster_attachable,
    vector_similarity_score,
)
from bot_worker.services.events import (
    compact_archived_events,
    merge_event_clusters,
    split_event_cluster,
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


def test_cluster_candidates_rejects_reuters_global_macro_contamination() -> None:
    candidates = [
        EventCandidate(
            news_id="news_iran",
            title="Hostilities flare in Iran war, oil jumps with talks at a stalemate - Reuters",
            source_score=60,
            entities=["Iran", "Reuters"],
            region="global",
            asset_classes=["global_macro"],
            published_at=datetime(2026, 6, 2, 23, 24, tzinfo=UTC),
        ),
        EventCandidate(
            news_id="news_spacex",
            title=(
                "Exclusive: SpaceX plans to set IPO price at $135 per share, "
                "targeting $75 billion raise, source says - Reuters"
            ),
            source_score=60,
            entities=["SpaceX", "Reuters"],
            region="global",
            asset_classes=["global_macro"],
            published_at=datetime(2026, 6, 3, 0, 26, tzinfo=UTC),
        ),
        EventCandidate(
            news_id="news_dg",
            title="Dollar General flags strain on core shoppers, lifts profit forecast - Reuters",
            source_score=60,
            entities=["Dollar General", "Reuters", "DG"],
            region="global",
            asset_classes=["global_macro"],
            published_at=datetime(2026, 6, 2, 16, 59, tzinfo=UTC),
            tickers=["DG"],
        ),
        EventCandidate(
            news_id="news_oil",
            title="Oil prices rise as new Middle East hostilities flare and talks stall - Reuters",
            source_score=60,
            entities=["Middle East hostilities", "oil prices", "Reuters"],
            region="global",
            asset_classes=["global_macro"],
            published_at=datetime(2026, 6, 3, 0, 36, tzinfo=UTC),
        ),
    ]

    clusters = cluster_candidates(candidates)

    assert [cluster.news_ids for cluster in clusters] == [
        ["news_iran", "news_oil"],
        ["news_spacex"],
        ["news_dg"],
    ]


def test_same_event_decision_rejects_publisher_overlap_only() -> None:
    candidate = EventCandidate(
        news_id="news_2",
        title="Dollar General flags strain on core shoppers, lifts profit forecast - Reuters",
        source_score=60,
        entities=["Dollar General", "Reuters"],
        region="global",
        asset_classes=["global_macro"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    existing = EventCandidate(
        news_id="news_1",
        title="Hostilities flare in Iran war, oil jumps with talks at a stalemate - Reuters",
        source_score=60,
        entities=["Iran", "Reuters"],
        region="global",
        asset_classes=["global_macro"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    decision = classify_same_event(candidate, existing)

    assert decision.kind is SameEventDecisionKind.REJECT
    assert decision.entity_overlap == []


def test_same_event_decision_marks_same_broad_entity_different_action_ambiguous() -> None:
    candidate = EventCandidate(
        news_id="news_2",
        title="Fed governor speaks on bank capital rules",
        source_score=75,
        entities=["Federal Reserve"],
        region="us",
        asset_classes=["rates"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    existing = EventCandidate(
        news_id="news_1",
        title="Fed holds rates steady after June meeting",
        source_score=75,
        entities=["Federal Reserve"],
        region="us",
        asset_classes=["rates"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    decision = classify_same_event(candidate, existing)

    assert decision.kind is SameEventDecisionKind.AMBIGUOUS
    assert decision.entity_overlap == ["federal reserve"]


def test_same_event_decision_uses_vietnamese_title_tokens() -> None:
    candidate = EventCandidate(
        news_id="news_2",
        title="Đại hội cổ đông thường niên Vingroup thông qua kế hoạch lợi nhuận",
        source_score=75,
        entities=[],
        region="vietnam",
        asset_classes=["vietnam_equity"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    existing = EventCandidate(
        news_id="news_1",
        title="Vingroup tổ chức đại hội cổ đông thường niên",
        source_score=75,
        entities=[],
        region="vietnam",
        asset_classes=["vietnam_equity"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    decision = classify_same_event(candidate, existing)

    assert decision.kind is SameEventDecisionKind.STRONG_SAME_EVENT
    assert decision.reason == "strong_title_topic_overlap"


def test_same_event_decision_rejects_vietnamese_generic_filler_overlap() -> None:
    # Two unrelated Vietnamese headlines that only share generic filler words
    # ("triệu" = million, "trong" = in) must not merge on title alone.
    candidate = EventCandidate(
        news_id="news_2",
        title="Vì sao giá vàng giảm 7 triệu đồng chỉ trong một ngày?",
        source_score=75,
        entities=["Vàng miếng SJC"],
        region="vietnam",
        asset_classes=["commodity"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    existing = EventCandidate(
        news_id="news_1",
        title="VinFast sẽ cung cấp 1 triệu ôtô cho Green SM trong 4 năm",
        source_score=75,
        entities=["VinFast", "Green SM"],
        region="vietnam",
        asset_classes=["vietnam_equity"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    decision = classify_same_event(candidate, existing)

    assert decision.kind is SameEventDecisionKind.REJECT


def test_same_event_decision_rejects_shared_financial_times_suffix() -> None:
    # The "- Financial Times" attribution must be stripped so two unrelated FT
    # articles do not merge on the shared "financial"/"times" tokens.
    candidate = EventCandidate(
        news_id="news_2",
        title="Cycling Washington DC’s 18-mile Mount Vernon Trail - Financial Times",
        source_score=75,
        entities=["Washington"],
        region="us",
        asset_classes=["global_macro"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    existing = EventCandidate(
        news_id="news_1",
        title="Donald Trump’s $100,000 H-1B visa fee blocked by judge - Financial Times",
        source_score=75,
        entities=["Donald Trump"],
        region="us",
        asset_classes=["global_macro"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    decision = classify_same_event(candidate, existing)

    assert decision.kind is SameEventDecisionKind.REJECT


def test_same_event_decision_strips_bloomberg_dotcom_suffix() -> None:
    # "- Bloomberg.com" (regex previously missed the ".com") must be stripped so
    # the surviving "bloomberg" token cannot create a spurious overlap.
    candidate = EventCandidate(
        news_id="news_2",
        title="Trump Says Fed Rate Increase Would Be Wrong Ahead of Warsh Debut - Bloomberg.com",
        source_score=75,
        entities=["Federal Reserve"],
        region="us",
        asset_classes=["rates"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    existing = EventCandidate(
        news_id="news_1",
        title="OPEC+ Agrees Another Symbolic Quota Increase for July - Bloomberg.com",
        source_score=75,
        entities=["OPEC"],
        region="global",
        asset_classes=["commodity"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    decision = classify_same_event(candidate, existing)

    assert decision.kind is SameEventDecisionKind.REJECT


def test_same_ticker_different_topic_with_weak_title_support_is_not_strong_event() -> None:
    candidate = EventCandidate(
        news_id="news_2",
        title="Apple supplier warns on iPhone demand report",
        source_score=75,
        entities=[],
        tickers=["AAPL"],
        region="us",
        asset_classes=["equity"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    existing = EventCandidate(
        news_id="news_1",
        title="Apple faces EU antitrust fine over App Store",
        source_score=75,
        entities=[],
        tickers=["AAPL"],
        region="us",
        asset_classes=["equity"],
        published_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    decision = classify_same_event(candidate, existing)

    assert decision.kind is not SameEventDecisionKind.STRONG_SAME_EVENT


def test_cluster_candidates_uses_best_strong_match_not_first_match() -> None:
    candidates = [
        EventCandidate(
            news_id="news_oil",
            title="Oil jumps after tanker incident near Hormuz",
            source_score=70,
            entities=["Hormuz"],
            region="global",
            asset_classes=["commodity"],
            published_at=datetime(2026, 6, 2, tzinfo=UTC),
        ),
        EventCandidate(
            news_id="news_copper",
            title="Copper rises after China demand surprise",
            source_score=70,
            entities=["China demand"],
            region="global",
            asset_classes=["commodity"],
            published_at=datetime(2026, 6, 2, tzinfo=UTC),
        ),
        EventCandidate(
            news_id="news_follow",
            title="Oil rises after China demand surprise",
            source_score=70,
            entities=["Hormuz", "China demand"],
            region="global",
            asset_classes=["commodity"],
            published_at=datetime(2026, 6, 2, tzinfo=UTC),
        ),
    ]

    clusters = cluster_candidates(candidates)

    assert [cluster.news_ids for cluster in clusters] == [
        ["news_oil"],
        ["news_copper", "news_follow"],
    ]


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


def test_vector_cluster_attach_policy_allows_missing_entities_only_at_high_similarity() -> None:
    candidate = VectorClusterCandidate(
        cluster_id="evt_1",
        similarity=0.95,
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


class EventOperationSession:
    def __init__(self) -> None:
        self.clusters = {
            "evt_target": EventCluster(
                id="evt_target",
                canonical_headline="Target",
                status="reported",
                regions=["global"],
                asset_classes=["crypto"],
                affected_entities=["Bitcoin"],
                affected_tickers=["BTC"],
                source_count=1,
                high_quality_source_count=1,
                top_source_score=90,
            ),
            "evt_source": EventCluster(
                id="evt_source",
                canonical_headline="Source",
                status="reported",
                regions=["crypto"],
                asset_classes=["crypto"],
                affected_entities=["Ethereum"],
                affected_tickers=["ETH"],
                source_count=1,
                high_quality_source_count=0,
                top_source_score=70,
            ),
        }
        self.items = {
            "news_1": NormalizedNewsItem(
                id="news_1",
                title="Bitcoin ETF inflows rise",
                source_id="src_1",
                source_name="A",
                source_type="rss",
                source_score=90,
                url="https://example.com/1",
                region="global",
                asset_classes=["crypto"],
                title_hash="t1",
                normalized_text_hash="n1",
            ),
            "news_2": NormalizedNewsItem(
                id="news_2",
                title="Ether follows crypto rally",
                source_id="src_2",
                source_name="B",
                source_type="rss",
                source_score=70,
                url="https://example.com/2",
                region="crypto",
                asset_classes=["crypto"],
                title_hash="t2",
                normalized_text_hash="n2",
            ),
        }
        self.links = [
            EventClusterItem(event_cluster_id="evt_target", news_item_id="news_1"),
            EventClusterItem(event_cluster_id="evt_source", news_item_id="news_2"),
        ]
        self.added: list[object] = []
        self.deleted_embeddings_for: list[str] = []

    async def get(self, model, key):
        if model is EventCluster:
            return self.clusters.get(key)
        if model is NormalizedNewsItem:
            return self.items.get(key)
        return None

    async def execute(self, stmt):
        text = str(stmt)
        if "event_cluster_embeddings" in text:
            self.deleted_embeddings_for.extend(
                cluster_id for cluster_id in self.clusters if cluster_id in text
            )

        class Result:
            rowcount = 1

            def all(self):
                return []

        return Result()

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, EventCluster):
                self.clusters[value.id] = value
            if isinstance(value, EventClusterItem):
                self.links.append(value)


async def test_merge_event_clusters_moves_items_and_marks_source_merged() -> None:
    session = EventOperationSession()

    result = await merge_event_clusters(session, source_id="evt_source", target_id="evt_target")

    assert result["status"] == "merged"
    assert session.clusters["evt_source"].status == "merged"
    assert session.clusters["evt_source"].summary == "Merged into evt_target"
    assert session.clusters["evt_target"].source_count == 2
    assert session.clusters["evt_target"].top_source_score == 90


async def test_split_event_cluster_moves_selected_items_to_new_cluster() -> None:
    session = EventOperationSession()
    session.links[1].event_cluster_id = "evt_target"

    result = await split_event_cluster(
        session,
        source_id="evt_target",
        news_item_ids=["news_2"],
    )

    assert result["status"] == "split"
    assert result["source_event_id"] == "evt_target"
    assert result["new_event_id"].startswith("evt_")
    new_cluster = session.clusters[result["new_event_id"]]
    assert new_cluster.canonical_headline == "Ether follows crypto rally"
    assert new_cluster.source_count == 1


async def test_compact_archived_events_preserves_cluster_and_deletes_embeddings() -> None:
    session = EventOperationSession()
    cluster = session.clusters["evt_source"]
    cluster.alert_level = "archive_only"
    cluster.created_at = datetime(2026, 4, 1, tzinfo=UTC)

    result = await compact_archived_events(
        session,
        older_than=datetime(2026, 5, 1, tzinfo=UTC),
        dry_run=False,
    )

    assert result["status"] == "compacted"
    assert result["compacted"] == 1
    assert cluster.compacted_at is not None
    assert cluster.archive_summary["canonical_headline"] == "Source"
