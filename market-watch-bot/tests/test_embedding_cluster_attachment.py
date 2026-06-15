from datetime import UTC, datetime

import pytest

import bot_worker.services as services
import bot_worker.services.events as event_services
from bot_worker.db.models import (
    EventCluster,
    EventClusterEmbedding,
    EventClusterItem,
    LLMAnalysisRun,
    NewsItemEmbedding,
    NormalizedNewsItem,
)
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.events import EventCandidate, VectorClusterCandidate
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
            [
                EventClusterItem(event_cluster_id="evt_1", news_item_id="news_1"),
                EventClusterItem(event_cluster_id="evt_2", news_item_id="news_2"),
            ],
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
    # The attach mutated the cluster, so its embedding is recomputed in place rather than
    # deleted-and-deferred: exactly one delete (the swap) and a fresh embedding row, so the
    # cluster stays visible to vector attach for the rest of the batch.
    assert len(session.executed) == 1
    cluster_embeddings = [v for v in session.added if isinstance(v, EventClusterEmbedding)]
    assert len(cluster_embeddings) == 1
    assert cluster_embeddings[0].event_cluster_id == "evt_1"


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
async def test_build_event_clusters_prioritizes_newest_report_candidates() -> None:
    session = FakeSession(scalars=[[], []])

    await services.build_event_clusters(session)

    sql = str(session.scalars_statements[0]).lower()
    assert "order by coalesce(" in sql
    assert "normalized_news_items.published_at" in sql
    assert "normalized_news_items.fetched_at" in sql
    assert "normalized_news_items.created_at" in sql
    assert "desc" in sql


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
async def test_recluster_recent_event_clusters_reembeds_surviving_clusters(monkeypatch) -> None:
    session = FakeReclusterSession()
    vector_calls = 0

    async def fake_vector_item_neighbors(_session, _item_ids, *, config, min_similarity):
        nonlocal vector_calls
        vector_calls += 1
        return {}

    async def fake_news_item_entities(_session, news_item_id: str) -> list[str]:
        return ["Bitcoin"]

    async def fake_news_item_tickers(_session, news_item_id: str) -> list[str]:
        return ["BTC"]

    monkeypatch.setattr(event_services, "vector_item_neighbors", fake_vector_item_neighbors)
    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    result = await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=False,
        embedding_config=EmbeddingConfig(provider="local", dimensions=3),
        # No use_vector_signal: re-embed is lifecycle hygiene and must happen anyway.
    )

    # The two clusters merge into one surviving cluster, which must be re-embedded in place
    # so it is not left invisible to live vector attach until the next pipeline embed pass.
    assert result["status"] == "reclustered"
    assert result["new_clusters"] == 1
    assert result["event_cluster_embeddings_written"] == 1
    cluster_embeddings = [v for v in session.added if isinstance(v, EventClusterEmbedding)]
    assert len(cluster_embeddings) == 1
    assert cluster_embeddings[0].event_cluster_id == "evt_1"
    # Re-embed is decoupled from the grouping signal: no vector merge was requested.
    assert vector_calls == 0


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


class RecordingClusterSelectSession:
    """Captures the cluster-selection statement and returns an empty window."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def scalars(self, stmt):
        self.statements.append(stmt)
        return ScalarRows([])


@pytest.mark.asyncio
async def test_recluster_excludes_stale_clusters_and_is_unbounded_by_default() -> None:
    session = RecordingClusterSelectSession()

    result = await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=True,
    )

    assert result["affected_clusters"] == 0
    compiled = str(session.statements[0]).lower()
    # Emptied stale husks are excluded so they don't ride along in every window forever.
    assert "status !=" in compiled
    # --limit is unbounded by default: no LIMIT clause is emitted, --since alone scopes it.
    assert "limit" not in compiled


@pytest.mark.asyncio
async def test_recluster_applies_limit_when_provided() -> None:
    session = RecordingClusterSelectSession()

    await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=True,
        limit=100,
    )

    assert "limit" in str(session.statements[0]).lower()


class FakeReclusterSplitSession:
    """A single cluster that wrongly merged two unrelated events."""

    def __init__(self) -> None:
        self.cluster_1 = EventCluster(
            id="evt_1",
            canonical_headline="Bitcoin options are coming to Nasdaq",
            status="reported",
            regions=["crypto"],
            asset_classes=["crypto"],
            affected_entities=["Bitcoin", "Apple"],
            source_count=2,
            top_source_score=75,
        )
        self.item_1 = NormalizedNewsItem(
            id="news_1",
            title="Bitcoin options are coming to Nasdaq",
            source_score=75,
            region="crypto",
            asset_classes=["crypto"],
            processing_status="normalized",
            created_at=datetime(2026, 5, 25, 3, tzinfo=UTC),
        )
        self.item_2 = NormalizedNewsItem(
            id="news_2",
            title="Apple unveils new iPhone lineup in Cupertino",
            source_score=70,
            region="us",
            asset_classes=["equity"],
            processing_status="normalized",
            created_at=datetime(2026, 5, 25, 4, tzinfo=UTC),
        )
        self.scalars_results = [
            ["evt_1"],
            [self.cluster_1],
            [self.item_1, self.item_2],
            [],
            [
                EventClusterItem(event_cluster_id="evt_1", news_item_id="news_1"),
                EventClusterItem(event_cluster_id="evt_1", news_item_id="news_2"),
            ],
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


@pytest.mark.asyncio
async def test_recluster_recent_event_clusters_splits_false_merge_without_orphans(
    monkeypatch,
) -> None:
    session = FakeReclusterSplitSession()

    entity_map = {"news_1": ["Bitcoin"], "news_2": ["Apple"]}

    async def fake_news_item_entities(_session, news_item_id: str) -> list[str]:
        return entity_map[news_item_id]

    async def fake_news_item_tickers(_session, news_item_id: str) -> list[str]:
        return []

    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    result = await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=False,
    )

    cluster_items = [value for value in session.added if isinstance(value, EventClusterItem)]
    new_clusters = [value for value in session.added if isinstance(value, EventCluster)]

    # One bad cluster regroups into two events: evt_1 is reused, a fresh cluster is
    # created for the second event, and every news item keeps a home (no orphans).
    assert result["status"] == "reclustered"
    assert result["new_clusters"] == 2
    assert result["created_clusters"] == 1
    assert result["reused_clusters"] == 1
    assert result["stale_clusters"] == 0
    assert len(new_clusters) == 1
    assert len(cluster_items) == 2
    assert {item.news_item_id for item in cluster_items} == {"news_1", "news_2"}
    assert session.cluster_1.status == "reported"


@pytest.mark.asyncio
async def test_recluster_threads_llm_config_into_arbitration(monkeypatch) -> None:
    session = FakeReclusterSession()
    captured: dict[str, object] = {}

    async def fake_arbitration(_session, _candidates, *, llm_config, vector_neighbors=None):
        captured["llm_config"] = llm_config
        return [], 0, 0

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return []

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return []

    monkeypatch.setattr(
        event_services, "_cluster_candidates_with_llm_arbitration", fake_arbitration
    )
    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    config = LLMConfig(enabled=True, api_key="secret")
    result = await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=True,
        llm_config=config,
    )

    # The shared arbitration engine receives the operator's config (not the hardcoded
    # None recluster used to pass), which is what enables gray-zone LLM decisions.
    assert captured["llm_config"] is config
    assert result["status"] == "dry_run"


def _vector_candidate(
    news_id: str,
    title: str,
    *,
    entities: list[str],
    region: str = "crypto",
    assets: tuple[str, ...] = ("crypto",),
) -> EventCandidate:
    return EventCandidate(
        news_id=news_id,
        title=title,
        source_score=70,
        entities=entities,
        region=region,
        asset_classes=list(assets),
        published_at=None,
    )


@pytest.mark.asyncio
async def test_arbitration_vector_merges_lexically_different_items() -> None:
    a = _vector_candidate("news_1", "Acme options launch on Nasdaq", entities=["Acme"])
    b = _vector_candidate("news_2", "Derivatives debut at the exchange", entities=["Acme"])
    neighbors = {"news_1": {"news_2"}, "news_2": {"news_1"}}

    drafts, _, _ = await event_services._cluster_candidates_with_llm_arbitration(
        object(),
        [a, b],
        llm_config=None,
        vector_neighbors=neighbors,
    )

    # No shared words -> lexical alone would make two clusters; the vector edge plus a
    # shared entity and compatible context merges the two drafts into one.
    assert len(drafts) == 1
    assert set(drafts[0].news_ids) == {"news_1", "news_2"}


@pytest.mark.asyncio
async def test_arbitration_vector_respects_context_gate() -> None:
    a = _vector_candidate("news_1", "Acme options launch on Nasdaq", entities=["Acme"])
    b = _vector_candidate(
        "news_2",
        "Acme quarterly results beat",
        entities=["Acme"],
        region="us",
        assets=("equity",),
    )
    neighbors = {"news_1": {"news_2"}, "news_2": {"news_1"}}

    drafts, _, _ = await event_services._cluster_candidates_with_llm_arbitration(
        object(),
        [a, b],
        llm_config=None,
        vector_neighbors=neighbors,
    )

    # A vector edge alone must not merge across incompatible region/asset context.
    assert len(drafts) == 2


@pytest.mark.asyncio
async def test_arbitration_vector_merges_two_coherent_drafts() -> None:
    # Two internally-coherent groups that share no words across groups: lexical builds
    # two drafts, and a single cross-draft vector edge must merge them (the real
    # recluster case, where every item already has a lexical home).
    a1 = _vector_candidate(
        "a1", "Bitcoin ETF approval imminent says regulator", entities=["Acme"]
    )
    a2 = _vector_candidate(
        "a2", "Bitcoin ETF approval expected imminent today", entities=["Acme"]
    )
    b1 = _vector_candidate(
        "b1", "Crypto fund greenlight nears final clearance", entities=["Acme"]
    )
    b2 = _vector_candidate(
        "b2", "Crypto fund greenlight clearance coming soon", entities=["Solana"]
    )
    neighbors = {"a1": {"b1"}, "b1": {"a1"}}

    drafts, _, _ = await event_services._cluster_candidates_with_llm_arbitration(
        object(),
        [a1, a2, b1, b2],
        llm_config=None,
        vector_neighbors=neighbors,
    )

    assert len(drafts) == 1
    assert set(drafts[0].news_ids) == {"a1", "a2", "b1", "b2"}


@pytest.mark.asyncio
async def test_arbitration_without_vector_keeps_two_drafts() -> None:
    a1 = _vector_candidate(
        "a1", "Bitcoin ETF approval imminent says regulator", entities=["Acme"]
    )
    a2 = _vector_candidate(
        "a2", "Bitcoin ETF approval expected imminent today", entities=["Acme"]
    )
    b1 = _vector_candidate(
        "b1", "Crypto fund greenlight nears final clearance", entities=["Acme"]
    )
    b2 = _vector_candidate(
        "b2", "Crypto fund greenlight clearance coming soon", entities=["Acme"]
    )

    drafts, _, _ = await event_services._cluster_candidates_with_llm_arbitration(
        object(),
        [a1, a2, b1, b2],
        llm_config=None,
        vector_neighbors=None,
    )

    # Sanity: the two groups are genuinely distinct to lexical matching.
    assert len(drafts) == 2


class FakeNeighborSession:
    def __init__(self, pairs: list[tuple[str, str]]) -> None:
        self.pairs = pairs
        self.executed_params: dict[str, object] | None = None

    async def execute(self, _stmt, params: dict[str, object]):
        self.executed_params = params
        return QueryRows([MappingRow(a_id=a, b_id=b) for a, b in self.pairs])


@pytest.mark.asyncio
async def test_vector_item_neighbors_builds_symmetric_graph() -> None:
    session = FakeNeighborSession([("news_1", "news_2")])

    neighbors = await event_services.vector_item_neighbors(
        session,
        ["news_1", "news_2", "news_3"],
        config=EmbeddingConfig(provider="local", model="m", version="v1", dimensions=3),
        min_similarity=0.9,
    )

    assert neighbors == {"news_1": {"news_2"}, "news_2": {"news_1"}}
    assert session.executed_params is not None
    # cosine distance threshold is 1 - min_similarity
    assert session.executed_params["max_distance"] == pytest.approx(0.1)
    assert session.executed_params["item_ids"] == ["news_1", "news_2", "news_3"]


@pytest.mark.asyncio
async def test_recluster_builds_vector_neighbors_when_vector_signal_requested(monkeypatch) -> None:
    session = FakeReclusterSession()
    captured: dict[str, object] = {}

    async def fake_vector_item_neighbors(_session, item_ids, *, config, min_similarity):
        captured["item_ids"] = list(item_ids)
        captured["min_similarity"] = min_similarity
        return {}

    async def fake_news_item_entities(_session, _news_item_id: str) -> list[str]:
        return ["Bitcoin"]

    async def fake_news_item_tickers(_session, _news_item_id: str) -> list[str]:
        return ["BTC"]

    monkeypatch.setattr(event_services, "vector_item_neighbors", fake_vector_item_neighbors)
    monkeypatch.setattr(event_services, "news_item_entities", fake_news_item_entities)
    monkeypatch.setattr(event_services, "news_item_tickers", fake_news_item_tickers)

    await services.recluster_recent_event_clusters(
        session,
        since=datetime(2026, 5, 25, 0, tzinfo=UTC),
        dry_run=True,
        embedding_config=EmbeddingConfig(provider="local", dimensions=3),
        use_vector_signal=True,
    )

    assert captured["item_ids"] == ["news_1", "news_2"]
    assert captured["min_similarity"] >= 0.9
