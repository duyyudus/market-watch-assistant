from datetime import UTC, datetime

import pytest

import bot_worker.services as services
import bot_worker.services.events as event_services
from bot_worker.db.models import (
    EventCluster,
    EventClusterItem,
    LLMAnalysisRun,
    NewsItemEmbedding,
    NormalizedNewsItem,
)
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.events import VectorClusterCandidate
from bot_worker.llm import LLMConfig


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
        self.scalars_statements: list[object] = []
        self.flushes = 0
        self.scalar_results: list[object | None] = []

    async def scalars(self, stmt):
        self.scalars_statements.append(stmt)
        return ScalarRows(self._scalars.pop(0))

    async def scalar(self, _stmt):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

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
async def test_vector_cluster_candidates_use_typed_vector_param_and_config_filters() -> None:
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
    assert session.params["query_vector"] == [0.1, 0.2, 0.3]
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

    stats = await services.build_event_clusters(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
    )

    assert stats.created_clusters == 0
    assert stats.attached_existing == 1
    assert stats.llm_cluster_decisions == 0
    assert stats.llm_cluster_attaches == 0
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

    stats = await services.build_event_clusters(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
    )

    assert stats.created_clusters == 1
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

    stats = await services.build_event_clusters(session)

    assert stats.created_clusters == 1
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

    stats = await services.build_event_clusters(session)

    assert stats.created_clusters == 1
    cluster = next(value for value in session.added if isinstance(value, EventCluster))
    assert cluster.affected_entities == ["Bitcoin"]
    assert cluster.affected_tickers == ["BTC"]


@pytest.mark.asyncio
async def test_build_event_clusters_excludes_deduped_news_items() -> None:
    session = FakeSession(scalars=[[], []])

    stats = await services.build_event_clusters(session)

    assert stats.created_clusters == 0
    sql = str(session.scalars_statements[0]).lower()
    assert "processing_status = :processing_status_1" in sql
    assert "deduped" not in sql


@pytest.mark.asyncio
async def test_build_event_clusters_attaches_gray_zone_match_when_llm_confirms(
    monkeypatch,
) -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Brent rises as Hormuz shipping risks increase",
        source_score=80,
        region="global",
        asset_classes=["commodity"],
        processing_status="normalized",
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

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["hormuz", "brent"]

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    async def fake_vector_cluster_candidates_for_item(*_args, **_kwargs):
        return [
            VectorClusterCandidate(
                cluster_id="evt_1",
                similarity=0.87,
                regions=["global"],
                asset_classes=["commodity"],
                affected_entities=["hormuz"],
            )
        ]

    async def fake_resolve_llm_cluster_decision(
        *,
        session,
        item,
        cluster,
        similarity,
        config,
        entities,
        tickers,
    ):
        assert item.id == "news_1"
        assert cluster.id == "evt_1"
        assert similarity == 0.87
        assert config.cluster_decision_min_confidence == 70
        assert entities == ["hormuz", "brent"]
        assert tickers == []
        return True, True

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)
    monkeypatch.setattr(
        event_services,
        "vector_cluster_candidates_for_item",
        fake_vector_cluster_candidates_for_item,
    )
    monkeypatch.setattr(
        event_services,
        "resolve_llm_cluster_decision",
        fake_resolve_llm_cluster_decision,
    )

    stats = await services.build_event_clusters(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
        llm_config=LLMConfig(enabled=True, api_key="key"),
    )

    assert stats.created_clusters == 0
    assert stats.attached_existing == 1
    assert stats.llm_cluster_decisions == 1
    assert stats.llm_cluster_attaches == 1
    cluster_items = [value for value in session.added if isinstance(value, EventClusterItem)]
    assert len(cluster_items) == 1
    assert cluster_items[0].event_cluster_id == "evt_1"
    assert cluster_items[0].similarity_score == 87


@pytest.mark.asyncio
async def test_build_event_clusters_does_not_attach_gray_zone_match_when_llm_rejects(
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
    cluster = EventCluster(
        id="evt_1",
        canonical_headline="Fed cuts rates after emergency meeting",
        regions=["us"],
        asset_classes=["equity"],
        affected_entities=["fed"],
        source_count=1,
        top_source_score=90,
    )
    session = FakeSession(scalars=[[item], []], cluster=cluster)

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["fed"]

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    async def fake_vector_cluster_candidates_for_item(*_args, **_kwargs):
        return [
            VectorClusterCandidate(
                cluster_id="evt_1",
                similarity=0.87,
                regions=["us"],
                asset_classes=["equity"],
                affected_entities=["fed"],
            )
        ]

    async def fake_resolve_llm_cluster_decision(**_kwargs):
        return True, False

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)
    monkeypatch.setattr(
        event_services,
        "vector_cluster_candidates_for_item",
        fake_vector_cluster_candidates_for_item,
    )
    monkeypatch.setattr(
        event_services,
        "resolve_llm_cluster_decision",
        fake_resolve_llm_cluster_decision,
    )

    stats = await services.build_event_clusters(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
        llm_config=LLMConfig(enabled=True, api_key="key"),
    )

    assert stats.created_clusters == 1
    assert stats.attached_existing == 0
    assert stats.llm_cluster_decisions == 1
    assert stats.llm_cluster_attaches == 0


@pytest.mark.asyncio
async def test_build_event_clusters_attaches_ambiguous_batch_candidate_when_llm_confirms(
    monkeypatch,
) -> None:
    item_1 = NormalizedNewsItem(
        id="news_1",
        title="Fed holds rates steady after June meeting",
        source_score=75,
        region="us",
        asset_classes=["rates"],
        processing_status="normalized",
    )
    item_2 = NormalizedNewsItem(
        id="news_2",
        title="Fed governor says rate stance remains restrictive",
        source_score=75,
        region="us",
        asset_classes=["rates"],
        processing_status="normalized",
    )
    session = FakeSession(scalars=[[item_1, item_2], []])

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["Federal Reserve"]

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    async def fake_resolve_llm_cluster_decision(**kwargs):
        assert kwargs["item"].id == "news_2"
        assert kwargs["cluster"].canonical_headline == item_1.title
        return True, True

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)
    monkeypatch.setattr(
        event_services,
        "resolve_llm_cluster_decision",
        fake_resolve_llm_cluster_decision,
    )

    stats = await services.build_event_clusters(
        session,
        llm_config=LLMConfig(enabled=True, api_key="key"),
    )

    assert stats.created_clusters == 1
    assert stats.llm_cluster_decisions == 1
    assert stats.llm_cluster_attaches == 1
    cluster_items = [value for value in session.added if isinstance(value, EventClusterItem)]
    assert [item.news_item_id for item in cluster_items] == ["news_1", "news_2"]


@pytest.mark.asyncio
async def test_build_event_clusters_splits_ambiguous_batch_candidate_when_llm_unavailable(
    monkeypatch,
) -> None:
    item_1 = NormalizedNewsItem(
        id="news_1",
        title="Fed holds rates steady after June meeting",
        source_score=75,
        region="us",
        asset_classes=["rates"],
        processing_status="normalized",
    )
    item_2 = NormalizedNewsItem(
        id="news_2",
        title="Fed governor says rate stance remains restrictive",
        source_score=75,
        region="us",
        asset_classes=["rates"],
        processing_status="normalized",
    )
    session = FakeSession(scalars=[[item_1, item_2], []])

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["Federal Reserve"]

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    async def fail_resolve_llm_cluster_decision(**_kwargs):
        raise AssertionError("LLM should not be called when disabled")

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)
    monkeypatch.setattr(
        event_services,
        "resolve_llm_cluster_decision",
        fail_resolve_llm_cluster_decision,
    )

    stats = await services.build_event_clusters(
        session,
        llm_config=LLMConfig(enabled=False, api_key=None),
    )

    assert stats.created_clusters == 2
    assert stats.llm_cluster_decisions == 0
    assert stats.llm_cluster_attaches == 0


@pytest.mark.asyncio
async def test_build_event_clusters_skips_llm_for_below_gray_zone_similarity(
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
    cluster = EventCluster(
        id="evt_1",
        canonical_headline="Fed cuts rates after emergency meeting",
        regions=["us"],
        asset_classes=["equity"],
        affected_entities=["fed"],
        source_count=1,
        top_source_score=90,
    )
    session = FakeSession(scalars=[[item], []], cluster=cluster)

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["fed"]

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    async def fake_vector_cluster_candidates_for_item(*_args, **_kwargs):
        return [
            VectorClusterCandidate(
                cluster_id="evt_1",
                similarity=0.77,
                regions=["us"],
                asset_classes=["equity"],
                affected_entities=["fed"],
            )
        ]

    async def fail_resolve_llm_cluster_decision(**_kwargs):
        raise AssertionError("LLM should not be called below gray-zone minimum")

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)
    monkeypatch.setattr(
        event_services,
        "vector_cluster_candidates_for_item",
        fake_vector_cluster_candidates_for_item,
    )
    monkeypatch.setattr(
        event_services,
        "resolve_llm_cluster_decision",
        fail_resolve_llm_cluster_decision,
    )

    stats = await services.build_event_clusters(
        session,
        embedding_config=EmbeddingConfig(provider="local"),
        llm_config=LLMConfig(enabled=True, api_key="key"),
    )

    assert stats.created_clusters == 1
    assert stats.llm_cluster_decisions == 0


@pytest.mark.asyncio
async def test_resolve_llm_cluster_decision_reuses_cached_successful_no_decision() -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Fed keeps rates unchanged",
        source_score=90,
        region="us",
        asset_classes=["equity"],
        processing_status="normalized",
    )
    cluster = EventCluster(
        id="evt_1",
        canonical_headline="Fed cuts rates after emergency meeting",
        regions=["us"],
        asset_classes=["equity"],
        affected_entities=["fed"],
    )
    session = FakeSession(scalars=[], cluster=cluster)
    session.scalar_results.append(
        LLMAnalysisRun(
            target_type="cluster_candidate",
            target_id="cached",
            provider="openrouter",
            model="openai/gpt-4.1-mini",
            prompt_version="cluster-decision-v1",
            prompt_hash="hash",
            input_snapshot={},
            result={
                "decision": "related_but_separate",
                "confidence": 88,
                "rationale": "Same central bank but different policy action.",
            },
            status="succeeded",
        )
    )

    attempted, should_attach = await event_services.resolve_llm_cluster_decision(
        session=session,
        item=item,
        cluster=cluster,
        similarity=0.87,
        config=LLMConfig(enabled=True, api_key="key"),
        entities=["fed"],
        tickers=[],
    )

    assert attempted
    assert not should_attach
    assert session.added == []


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
