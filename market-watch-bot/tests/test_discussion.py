from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api_server.app.services.discussion import _rank_sqlite_articles
from common.db.models import Base, NewsItemEmbedding, NormalizedNewsItem
from common.embeddings import EmbeddingConfig


def _news(news_id: str, *, title: str, observed_at: datetime) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        id=news_id,
        source_id="source",
        title=title,
        snippet=f"{title} snippet",
        url=f"https://example.test/{news_id}",
        source_name="Test Wire",
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["macro"],
        processing_status="normalized",
        title_hash=f"title-{news_id}",
        normalized_text_hash=f"text-{news_id}",
        published_at=observed_at,
        fetched_at=observed_at,
        created_at=observed_at,
    )


@pytest.mark.asyncio
async def test_sqlite_discussion_retrieval_ranks_semantically_and_matches_config() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime.now(UTC) - timedelta(hours=1)
    dimensions = 1536
    relevant = _news("news_relevant", title="Rates fall", observed_at=observed_at)
    unrelated = _news("news_unrelated", title="Oil rises", observed_at=observed_at)
    wrong_config = _news("news_wrong_config", title="Rates rally", observed_at=observed_at)

    async with factory() as session:
        session.add_all(
            [
                relevant,
                unrelated,
                wrong_config,
                NewsItemEmbedding(
                    news_item_id=relevant.id,
                    provider="local",
                    embedding_model="test-model",
                    embedding_version="v1",
                    dimensions=dimensions,
                    embedding_text_hash="relevant",
                    vector=[1.0, 0.0] + [0.0] * (dimensions - 2),
                ),
                NewsItemEmbedding(
                    news_item_id=unrelated.id,
                    provider="local",
                    embedding_model="test-model",
                    embedding_version="v1",
                    dimensions=dimensions,
                    embedding_text_hash="unrelated",
                    vector=[0.0, 1.0] + [0.0] * (dimensions - 2),
                ),
                NewsItemEmbedding(
                    news_item_id=wrong_config.id,
                    provider="other",
                    embedding_model="test-model",
                    embedding_version="v1",
                    dimensions=dimensions,
                    embedding_text_hash="wrong-config",
                    vector=[1.0, 0.0] + [0.0] * (dimensions - 2),
                ),
            ]
        )
        await session.commit()

        rows = await _rank_sqlite_articles(
            session,
            config=EmbeddingConfig(
                provider="local",
                model="test-model",
                version="v1",
                dimensions=dimensions,
            ),
            cutoff=observed_at - timedelta(hours=1),
            query_vector=[1.0, 0.0] + [0.0] * (dimensions - 2),
        )

    await engine.dispose()

    assert [row.id for row in rows] == ["news_relevant", "news_unrelated"]
