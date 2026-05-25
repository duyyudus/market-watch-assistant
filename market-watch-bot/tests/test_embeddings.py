import os

import pytest

from bot_worker.config import load_settings
from bot_worker.embeddings import (
    EmbeddingConfig,
    OpenRouterEmbeddingProvider,
    build_embedding_text,
    cosine_similarity,
    embedding_text_hash,
    local_embedding,
)


def test_load_settings_uses_openrouter_embedding_defaults(tmp_path) -> None:
    settings = load_settings(
        env_file=tmp_path / "missing.env", settings_file=tmp_path / "missing.yml"
    )

    assert settings.embeddings.provider == "openrouter"
    assert settings.embeddings.api_base_url == "https://openrouter.ai/api/v1"
    assert settings.embeddings.model == "openai/text-embedding-3-large"
    assert settings.embeddings.dimensions == 1536
    assert settings.embeddings.api_key_env == "OPENROUTER_API_KEY"


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

    assert EmbeddingConfig.from_settings(load_settings()).api_key == "from-env"
