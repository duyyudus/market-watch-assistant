from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from bot_worker.normalize import content_hash, normalize_text

if TYPE_CHECKING:
    from bot_worker.config import Settings


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "openrouter"
    api_base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/text-embedding-3-large"
    dimensions: int = 1536
    api_key_env: str = "OPENROUTER_API_KEY"
    api_key: str | None = None
    version: str = "v1"

    @classmethod
    def from_settings(cls, settings: Settings) -> EmbeddingConfig:
        api_key = os.environ.get(settings.embeddings.api_key_env)
        if api_key is None and settings.embeddings.api_key_env == "OPENROUTER_API_KEY":
            api_key = settings.openrouter_api_key
        return cls(
            provider=settings.embeddings.provider,
            api_base_url=settings.embeddings.api_base_url,
            model=settings.embeddings.model,
            dimensions=settings.embeddings.dimensions,
            api_key_env=settings.embeddings.api_key_env,
            api_key=api_key,
            version=settings.embeddings.version,
        )


def build_embedding_text(
    *,
    title: str,
    snippet: str | None,
    source_name: str,
    entities: list[str],
    region: str,
    asset_classes: list[str],
) -> str:
    parts = [
        f"Title: {normalize_text(title)}",
        f"Snippet: {normalize_text(snippet) if snippet else ''}",
        f"Source: {normalize_text(source_name)}",
        f"Entities: {', '.join(sorted({normalize_text(entity) for entity in entities if entity}))}",
        f"Region: {region}",
        f"Asset classes: {', '.join(sorted(asset_classes))}",
    ]
    return "\n".join(parts)


def embedding_text_hash(text: str) -> str:
    return content_hash(text)


def local_embedding(text: str, *, dimensions: int = 1536) -> list[float]:
    vector = [0.0] * dimensions
    tokens = normalize_text(text).casefold().split()
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    return dot / (left_norm * right_norm)


class OpenRouterEmbeddingProvider:
    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.config.api_key:
            raise ValueError(f"{self.config.api_key_env} is required for OpenRouter embeddings")
        payload: dict[str, object] = {
            "model": self.config.model,
            "input": texts,
            "dimensions": self.config.dimensions,
        }
        url = f"{self.config.api_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        data = response.json().get("data", [])
        return [[float(value) for value in item["embedding"]] for item in data]


class LocalEmbeddingProvider:
    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [local_embedding(text, dimensions=self.config.dimensions) for text in texts]


def embedding_provider(
    config: EmbeddingConfig,
) -> OpenRouterEmbeddingProvider | LocalEmbeddingProvider:
    if config.provider == "local":
        return LocalEmbeddingProvider(config)
    return OpenRouterEmbeddingProvider(config)
