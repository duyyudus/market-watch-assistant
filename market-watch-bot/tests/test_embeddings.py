import asyncio
import os

import pytest

import bot_worker.services.embeddings as embedding_services
from bot_worker.config import load_settings
from bot_worker.db.models import (
    EventCluster,
    EventClusterEmbedding,
    NewsItemEmbedding,
    NormalizedNewsItem,
)
from bot_worker.embeddings import (
    EmbeddingConfig,
    OpenRouterEmbeddingProvider,
    build_embedding_text,
    cosine_similarity,
    embedding_text_hash,
    local_embedding,
)
from bot_worker.services.embeddings import validate_embedding_dimensions


class ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class FakeEmbeddingSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.added: list[object] = []
        self.scalars_calls = 0

    async def scalars(self, _stmt):
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            return ScalarRows(self.rows)
        return ScalarRows([])

    def add(self, value: object) -> None:
        self.added.append(value)


def test_load_settings_uses_openrouter_embedding_defaults(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=sqlite+aiosqlite:///:memory:\n", encoding="utf-8")
    settings = load_settings(env_file=env_file, settings_file=tmp_path / "missing.yml")

    assert settings.embeddings.provider == "openrouter"
    assert settings.embeddings.api_base_url == "https://openrouter.ai/api/v1"
    assert settings.embeddings.model == "openai/text-embedding-3-large"
    assert settings.embeddings.dimensions == 1536
    assert settings.embeddings.api_key_env == "OPENROUTER_API_KEY"
    assert settings.embeddings.cluster_attach_enabled is True
    assert settings.embeddings.cluster_attach_lookback_days == 7
    assert settings.embeddings.cluster_attach_min_similarity == 0.88
    assert settings.embeddings.cluster_attach_candidate_limit == 20
    assert settings.embeddings.max_concurrency == 3


@pytest.mark.asyncio
async def test_openrouter_embedding_provider_sends_dimensions_and_batches(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {"embedding": [1.0, 0.0, 0.0]},
                    {"embedding": [0.0, 1.0, 0.0]},
                ]
            }

    class DummyClient:
        def __init__(self, **_kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]):
            calls.append({"url": url, "headers": headers, "json": json})
            return DummyResponse()

    monkeypatch.setattr("bot_worker.embeddings.httpx.AsyncClient", DummyClient)
    config = EmbeddingConfig(api_key="secret")

    vectors = await OpenRouterEmbeddingProvider(config).embed(["alpha", "beta"])

    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert calls == [
        {
            "url": "https://openrouter.ai/api/v1/embeddings",
            "headers": {
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
            "json": {
                "model": "openai/text-embedding-3-large",
                "input": ["alpha", "beta"],
                "dimensions": 1536,
            },
        }
    ]


def test_embedding_text_hash_and_local_embedding_are_stable() -> None:
    text = build_embedding_text(
        title="BTC jumps after ETF flows",
        snippet="Bitcoin rallies as inflows accelerate",
        source_name="CoinDesk",
        entities=["BTC", "Bitcoin"],
        region="crypto",
        asset_classes=["crypto"],
    )

    assert "Title: BTC jumps after ETF flows" in text
    assert embedding_text_hash(text) == embedding_text_hash(text)
    assert local_embedding(text, dimensions=8) == local_embedding(text, dimensions=8)
    assert len(local_embedding(text, dimensions=8)) == 8


def test_cosine_similarity_orders_related_vectors() -> None:
    assert cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)


def test_embedding_config_reads_api_key_from_env(monkeypatch) -> None:
    monkeypatch.setitem(os.environ, "OPENROUTER_API_KEY", "from-env")

    config = EmbeddingConfig.from_settings(load_settings())

    assert config.api_key == "from-env"
    assert config.max_concurrency == 3


def test_validate_embedding_dimensions_rejects_unsupported_vector_column_size() -> None:
    with pytest.raises(ValueError, match="configured embedding dimensions 768 do not match"):
        validate_embedding_dimensions(EmbeddingConfig(dimensions=768))


@pytest.mark.asyncio
async def test_embed_pending_news_items_limits_concurrent_provider_batches(monkeypatch) -> None:
    items = [
        NormalizedNewsItem(
            id=f"news_{index}",
            title=f"Market news {index}",
            snippet=f"Snippet {index}",
            source_name="MarketWatch",
            source_type="rss",
            source_score=75,
            region="crypto",
            asset_classes=["crypto"],
            language="en",
            url=f"https://example.test/news/{index}",
            title_hash=f"title-{index}",
            normalized_text_hash=f"text-{index}",
            processing_status="normalized",
        )
        for index in range(4)
    ]
    session = FakeEmbeddingSession(items)

    class FakeProvider:
        def __init__(self) -> None:
            self.active_calls = 0
            self.max_active_calls = 0

        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            await asyncio.sleep(0.01)
            self.active_calls -= 1
            return [[float(index), 0.0] for index, _text in enumerate(texts)]

    provider = FakeProvider()
    monkeypatch.setattr(embedding_services, "embedding_provider", lambda _config: provider)

    count = await embedding_services.embed_pending_news_items(
        session,
        config=EmbeddingConfig(provider="local", dimensions=2, max_concurrency=2),
    )

    embeddings = [value for value in session.added if isinstance(value, NewsItemEmbedding)]
    assert count == 4
    assert provider.max_active_calls == 2
    assert len(embeddings) == 4
    assert {embedding.news_item_id for embedding in embeddings} == {
        "news_0",
        "news_1",
        "news_2",
        "news_3",
    }


@pytest.mark.asyncio
async def test_embed_pending_event_clusters_limits_concurrent_provider_batches(monkeypatch) -> None:
    clusters = [
        EventCluster(
            id=f"evt_{index}",
            canonical_headline=f"High value event {index}",
            summary=f"Summary {index}",
            source_count=1,
            top_source_score=90,
            affected_entities=[],
            regions=["global"],
            asset_classes=["equity"],
        )
        for index in range(4)
    ]
    session = FakeEmbeddingSession(clusters)

    class FakeProvider:
        def __init__(self) -> None:
            self.active_calls = 0
            self.max_active_calls = 0

        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            await asyncio.sleep(0.01)
            self.active_calls -= 1
            return [[float(index), 1.0] for index, _text in enumerate(texts)]

    provider = FakeProvider()
    monkeypatch.setattr(embedding_services, "embedding_provider", lambda _config: provider)

    count = await embedding_services.embed_pending_event_clusters(
        session,
        config=EmbeddingConfig(provider="local", dimensions=2, max_concurrency=2),
    )

    embeddings = [value for value in session.added if isinstance(value, EventClusterEmbedding)]
    assert count == 4
    assert provider.max_active_calls == 2
    assert len(embeddings) == 4
    assert {embedding.event_cluster_id for embedding in embeddings} == {
        "evt_0",
        "evt_1",
        "evt_2",
        "evt_3",
    }
