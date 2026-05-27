from datetime import UTC, datetime

import pytest

import bot_worker.services as services
import bot_worker.services.events as event_services
from bot_worker.db.models import (
    EventCluster,
    EventClusterItem,
    NewsItemEmbedding,
    NormalizedNewsItem,
)
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.events import VectorClusterCandidate


class ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class FakeExecuteResult:
    rowcount = 1


class FakeSession:
    def __init__(self, scalars: list[list[object]], cluster: EventCluster | None = None) -> None:
        self._scalars = scalars
        self.cluster = cluster
        self.added: list[object] = []
        self.executed: list[object] = []
        self.flushes = 0

    async def scalars(self, _stmt):
        return ScalarRows(self._scalars.pop(0))

    async def get(self, model, key):
        if model is EventCluster and self.cluster is not None and self.cluster.id == key:
            return self.cluster
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def execute(self, stmt):
        self.executed.append(stmt)
        return FakeExecuteResult()

    async def flush(self) -> None:
        self.flushes += 1


class FakeReclusterSession:
    def __init__(self) -> None:
        self.cluster_1 = EventCluster(
            id="evt_1",
            canonical_headline="Bitcoin options are coming to Nasdaq",
            status="reported",
            regions=["crypto"],
            asset_classes=["crypto"],
            affected_entities=["Bitcoin", "are", "options"],
            source_count=1,
            top_source_score=75,
        )
        self.cluster_2 = EventCluster(
            id="evt_2",
            canonical_headline="Bitcoin trades above $110,000 as Nasdaq prepares options launch",
            status="reported",
            regions=["crypto"],
            asset_classes=["crypto"],
            affected_entities=["Bitcoin", "above", "trades"],
            source_count=1,
            top_source_score=70,
        )
        self.item_1 = NormalizedNewsItem(
            id="news_1",
            title="Bitcoin options are coming to Nasdaq. Here's what it means for you.",
            source_score=75,
            region="crypto",
            asset_classes=["crypto"],
            processing_status="normalized",
            created_at=datetime(2026, 5, 25, 3, tzinfo=UTC),
        )
        self.item_2 = NormalizedNewsItem(
            id="news_2",
            title="Bitcoin trades above $110,000 as Nasdaq prepares options launch",
            source_score=70,
            region="crypto",
            asset_classes=["crypto"],
            processing_status="normalized",
            created_at=datetime(2026, 5, 25, 4, tzinfo=UTC),
        )
        self.scalars_results = [
            ["evt_1", "evt_2"],
            [self.cluster_1, self.cluster_2],
            [self.item_1, self.item_2],
            [],
        ]
        self.added: list[object] = []
        self.executed: list[object] = []
        self.flushes = 0

    async def scalars(self, _stmt):
        return ScalarRows(self.scalars_results.pop(0))

    async def execute(self, stmt):
        self.executed.append(stmt)
        return FakeExecuteResult()

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1


class QueryRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class MappingRow:
    def __init__(self, **values: object) -> None:
        self._mapping = values


class FakeVectorQuerySession:
    def __init__(self) -> None:
        self.params: dict[str, object] | None = None

    async def get(self, model, key):
        assert model is NewsItemEmbedding
        assert key == "news_1"
        return NewsItemEmbedding(
            news_item_id="news_1",
            provider="local",
            embedding_model="local-hash",
            embedding_version="v1",
            dimensions=3,
            embedding_text_hash="hash",
            vector=[0.1, 0.2, 0.3],
        )

    async def execute(self, _stmt, params: dict[str, object]):
        self.params = params
        return QueryRows(
            [
                MappingRow(
                    cluster_id="evt_1",
                    similarity=0.91,
                    regions=["global"],
                    asset_classes=["commodity"],
                    affected_entities=["oil"],
                )
            ]
        )


@pytest.mark.asyncio
async def test_vector_cluster_candidates_use_pgvector_literal_and_config_filters() -> None:
    session = FakeVectorQuerySession()
    item = NormalizedNewsItem(id="news_1", title="Oil rises", region="global")

    candidates = await services.vector_cluster_candidates_for_item(
        session,
        item,
        config=EmbeddingConfig(
            provider="local",
            model="local-hash",
            dimensions=3,
            version="v1",
        ),
        lookback_days=7,
        limit=20,
    )

    assert candidates == [
        VectorClusterCandidate(
            cluster_id="evt_1",
            similarity=0.91,
            regions=["global"],
            asset_classes=["commodity"],
            affected_entities=["oil"],
        )
    ]
    assert session.params is not None
    assert session.params["query_vector"] == "[0.1,0.2,0.3]"
    assert session.params["provider"] == "local"
    assert session.params["model"] == "local-hash"
    assert session.params["version"] == "v1"
    assert session.params["dimensions"] == 3
    assert session.params["limit"] == 20


@pytest.mark.asyncio
async def test_build_event_clusters_attaches_embedding_match(monkeypatch) -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Brent rises as Hormuz shipping risks increase",
        source_score=80,
        region="global",
        asset_classes=["commodity"],
        processing_status="normalized",
        created_at=datetime(2026, 5, 25, 4, tzinfo=UTC),
    )
    cluster = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after tanker incident near Hormuz",
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["hormuz"],
        source_count=1,
        top_source_score=70,
    )
    session = FakeSession(scalars=[[item], []], cluster=cluster)

    async def fake_news_item_entities(_session, news_item_id: str) -> list[str]:
        assert news_item_id == "news_1"
        return ["hormuz", "brent"]

    async def fake_news_item_tickers(_session, news_item_id: str) -> list[str]:
        assert news_item_id == "news_1"
        return []

    async def fake_vector_cluster_candidates_for_item(
        _session,
        news_item: NormalizedNewsItem,
        *,
        config: EmbeddingConfig,
        lookback_days: int,
        limit: int,
    ) -> list[VectorClusterCandidate]:
        assert news_item is item
        assert config.provider == "local"
        assert lookback_days == 7
        assert limit == 20
        return [
            VectorClusterCandidate(
                cluster_id="evt_1",
                similarity=0.89,
                regions=["global"],
                asset_classes=["commodity"],
                affected_entities=["hormuz"],
            )
        ]

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)
    monkeypatch.setattr(
        event_services,
        "vector_cluster_candidates_for_item",
        fake_vector_cluster_candidates_for_item,
    )

    created = await services.build_event_clusters(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
    )

    assert created == 0
    cluster_items = [value for value in session.added if isinstance(value, EventClusterItem)]
    assert len(cluster_items) == 1
    assert cluster_items[0].event_cluster_id == "evt_1"
    assert cluster_items[0].news_item_id == "news_1"
    assert cluster_items[0].similarity_score == 89
    assert cluster.source_count == 2
    assert cluster.top_source_score == 80
    assert cluster.affected_entities == ["brent", "hormuz"]
    assert cluster.final_score > 0
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_build_event_clusters_creates_new_cluster_when_vector_match_is_not_compatible(
    monkeypatch,
) -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Fed keeps rates unchanged",
        source_score=90,
        region="us",
        asset_classes=["equity"],
        processing_status="normalized",
    )
    session = FakeSession(scalars=[[item], []])

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["fed"]

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    async def fake_vector_cluster_candidates_for_item(*_args, **_kwargs):
        return [
            VectorClusterCandidate(
                cluster_id="evt_1",
                similarity=0.95,
                regions=["global"],
                asset_classes=["commodity"],
                affected_entities=["oil"],
            )
        ]

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)
    monkeypatch.setattr(
        event_services,
        "vector_cluster_candidates_for_item",
        fake_vector_cluster_candidates_for_item,
    )

    created = await services.build_event_clusters(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
    )

    assert created == 1
    assert any(isinstance(value, EventCluster) for value in session.added)
    cluster_items = [value for value in session.added if isinstance(value, EventClusterItem)]
    assert len(cluster_items) == 1
    assert cluster_items[0].similarity_score is None
    assert session.executed == []


@pytest.mark.asyncio
async def test_build_event_clusters_uses_empty_entities_without_title_word_fallback(
    monkeypatch,
) -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Bitcoin options are coming to Nasdaq. Here's what it means for you.",
        source_score=75,
        region="crypto",
        asset_classes=["crypto"],
        processing_status="normalized",
    )
    session = FakeSession(scalars=[[item], []])

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return []

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    created = await services.build_event_clusters(session)

    assert created == 1
    cluster = next(value for value in session.added if isinstance(value, EventCluster))
    assert cluster.affected_entities == []
    assert not ({"Bitcoin", "options", "are"} & set(cluster.affected_entities))


@pytest.mark.asyncio
async def test_build_event_clusters_populates_affected_tickers_from_news_entities(
    monkeypatch,
) -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Bitcoin options are coming to Nasdaq. Here's what it means for you.",
        source_score=75,
        region="crypto",
        asset_classes=["crypto"],
        processing_status="normalized",
    )
    session = FakeSession(scalars=[[item], []])

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["Bitcoin"]

    async def fake_news_item_tickers(_session, news_item_id: str) -> list[str]:
        assert news_item_id == "news_1"
        return ["BTC"]

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    created = await services.build_event_clusters(session)

    assert created == 1
    cluster = next(value for value in session.added if isinstance(value, EventCluster))
    assert cluster.affected_entities == ["Bitcoin"]
    assert cluster.affected_tickers == ["BTC"]


@pytest.mark.asyncio
async def test_recluster_recent_event_clusters_merges_duplicate_clusters_with_clean_entities(
    monkeypatch,
) -> None:
    session = FakeReclusterSession()

    async def fake_news_item_entities(_session, news_item_id: str) -> list[str]:
        assert news_item_id in {"news_1", "news_2"}
        return ["Bitcoin"]

    async def fake_news_item_tickers(_session, news_item_id: str) -> list[str]:
        assert news_item_id in {"news_1", "news_2"}
        return ["BTC"]

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    result = await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=False,
    )

    cluster_items = [value for value in session.added if isinstance(value, EventClusterItem)]
    assert result["status"] == "reclustered"
    assert result["affected_clusters"] == 2
    assert result["news_items"] == 2
    assert result["new_clusters"] == 1
    assert result["stale_clusters"] == 1
    assert len(cluster_items) == 2
    assert {item.event_cluster_id for item in cluster_items} == {"evt_1"}
    assert session.cluster_1.affected_entities == ["Bitcoin"]
    assert session.cluster_1.affected_tickers == ["BTC"]
    assert session.cluster_1.source_count == 2
    assert session.cluster_2.status == "stale"
    assert session.cluster_2.source_count == 0
    assert len(session.executed) == 2


@pytest.mark.asyncio
async def test_recluster_recent_event_clusters_dry_run_does_not_mutate(monkeypatch) -> None:
    session = FakeReclusterSession()

    async def fake_news_item_entities(_session, news_item_id: str) -> list[str]:
        assert news_item_id in {"news_1", "news_2"}
        return ["Bitcoin"]

    async def fake_news_item_tickers(_session, news_item_id: str) -> list[str]:
        assert news_item_id in {"news_1", "news_2"}
        return ["BTC"]

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    result = await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["affected_clusters"] == 2
    assert result["news_items"] == 2
    assert result["new_clusters"] == 1
    assert session.added == []
    assert session.executed == []
    assert session.cluster_2.status == "reported"
