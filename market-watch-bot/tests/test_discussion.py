from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.db.models import (
    Base,
    EventCluster,
    EventClusterItem,
    NewsItemEmbedding,
    NormalizedNewsItem,
)
from common.discussion import (
    _discussion_prompt,
    _group_story_rows,
    _load_stories,
    _rank_sqlite_story_rows,
)
from common.embeddings import EmbeddingConfig

DIMENSIONS = 1536
CONFIG = EmbeddingConfig(provider="local", model="test-model", version="v1", dimensions=DIMENSIONS)
QUERY = [1.0, 0.0] + [0.0] * (DIMENSIONS - 2)


def _news(
    news_id: str,
    *,
    title: str,
    observed_at: datetime,
    processing_status: str = "normalized",
    source_name: str = "Test Wire",
) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        id=news_id,
        source_id="source",
        title=title,
        snippet=f"{title} snippet",
        url=f"https://example.test/{news_id}",
        source_name=source_name,
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["macro"],
        processing_status=processing_status,
        title_hash=f"title-{news_id}",
        normalized_text_hash=f"text-{news_id}",
        published_at=observed_at,
        fetched_at=observed_at,
        created_at=observed_at,
    )


def _embedding(news_id: str, x: float, y: float, *, provider: str = "local") -> NewsItemEmbedding:
    return NewsItemEmbedding(
        news_item_id=news_id,
        provider=provider,
        embedding_model="test-model",
        embedding_version="v1",
        dimensions=DIMENSIONS,
        embedding_text_hash=news_id,
        vector=[x, y] + [0.0] * (DIMENSIONS - 2),
    )


async def _session_with(rows: list[object]):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session = factory()
    session.add_all(rows)
    await session.commit()
    return engine, session


@pytest.mark.asyncio
async def test_sqlite_discussion_retrieval_ranks_semantically_and_matches_config() -> None:
    observed_at = datetime.now(UTC) - timedelta(hours=1)
    engine, session = await _session_with(
        [
            _news("news_relevant", title="Rates fall", observed_at=observed_at),
            _news("news_unrelated", title="Oil rises", observed_at=observed_at),
            _news("news_wrong_config", title="Rates rally", observed_at=observed_at),
            _embedding("news_relevant", 1.0, 0.0),
            _embedding("news_unrelated", 0.0, 1.0),
            _embedding("news_wrong_config", 1.0, 0.0, provider="other"),
        ]
    )
    try:
        rows = await _rank_sqlite_story_rows(
            session, config=CONFIG, cutoff=observed_at - timedelta(hours=1), query_vector=QUERY
        )
    finally:
        await session.close()
        await engine.dispose()

    assert rows == [("news_relevant", None), ("news_unrelated", None)]


@pytest.mark.asyncio
async def test_discussion_retrieval_groups_heavily_covered_events_into_one_story() -> None:
    observed_at = datetime.now(UTC) - timedelta(hours=1)
    hot = EventCluster(id="evt_hot", canonical_headline="Fed cuts rates", summary="A cut.")
    other = EventCluster(id="evt_other", canonical_headline="Oil supply tightens")
    engine, session = await _session_with(
        [
            hot,
            other,
            # Four articles on one story, all close to the query: three updates from one
            # wire plus one other outlet, and an older piece outside the window.
            *[
                _news(
                    f"news_hot_{index}",
                    title=f"Fed cut {index}",
                    observed_at=observed_at,
                    source_name="Reuters" if index == 3 else "Test Wire",
                )
                for index in range(4)
            ],
            _news(
                "news_hot_old",
                title="Fed preview",
                observed_at=observed_at - timedelta(days=3),
                source_name="Bloomberg",
            ),
            _news("news_other", title="Oil supply", observed_at=observed_at),
            _news("news_loose", title="Not yet clustered", observed_at=observed_at),
            _news(
                "news_dup",
                title="Fed cut copy",
                observed_at=observed_at,
                processing_status="deduped",
            ),
            *[
                EventClusterItem(event_cluster_id="evt_hot", news_item_id=f"news_hot_{index}")
                for index in range(4)
            ],
            EventClusterItem(event_cluster_id="evt_hot", news_item_id="news_hot_old"),
            EventClusterItem(event_cluster_id="evt_other", news_item_id="news_other"),
            _embedding("news_hot_0", 1.0, 0.0),
            _embedding("news_hot_1", 0.99, 0.1),
            _embedding("news_hot_2", 0.98, 0.2),
            _embedding("news_hot_3", 0.97, 0.25),
            _embedding("news_hot_old", 1.0, 0.0),
            _embedding("news_other", 0.9, 0.45),
            _embedding("news_loose", 0.8, 0.6),
            _embedding("news_dup", 1.0, 0.0),
        ]
    )
    try:
        cutoff = observed_at - timedelta(hours=1)
        rows = await _rank_sqlite_story_rows(
            session, config=CONFIG, cutoff=cutoff, query_vector=QUERY
        )
        groups = _group_story_rows(rows, story_limit=3, articles_per_story=2)
        stories = await _load_stories(session, groups, cutoff=cutoff)
    finally:
        await session.close()
        await engine.dispose()

    # Deduped copies are excluded; the hot story takes one slot with its two closest
    # articles, leaving room for the other event and the unclustered article.
    assert groups == [
        ("evt_hot", ["news_hot_0", "news_hot_1"]),
        ("evt_other", ["news_other"]),
        (None, ["news_loose"]),
    ]
    assert [story.event.id if story.event else None for story in stories] == [
        "evt_hot",
        "evt_other",
        None,
    ]
    # Distinct outlets inside the window: repeated updates from one wire count once,
    # and the older Bloomberg piece outside the window is not counted.
    assert [story.outlet_count for story in stories] == [2, 1, 1]
    question = [{"role": "user", "content": "Fed?"}]
    prompt = _discussion_prompt(question, stories, text_chars=6_000)
    assert '"headline": "Fed cuts rates"' in prompt
    assert '"summary": "A cut."' in prompt
    assert '"outlets_in_period": 2' in prompt
    assert '"event": null' in prompt
    assert "Treat each story as one development" in prompt
    # A past period hides the event's current headline and summary.
    past_prompt = _discussion_prompt(
        question, stories, text_chars=6_000, current_event_details=False
    )
    assert "Fed cuts rates" not in past_prompt
    assert '"event": {"outlets_in_period": 2}' in past_prompt


def test_group_story_rows_caps_stories_and_articles_per_story() -> None:
    rows = [
        ("a1", "evt_a"),
        ("b1", "evt_b"),
        ("a2", "evt_a"),
        ("a3", "evt_a"),
        ("c1", "evt_c"),
        ("b2", "evt_b"),
        # One article can belong to two events; it counts for each.
        ("a2", "evt_b"),
    ]

    assert _group_story_rows(rows, story_limit=2, articles_per_story=2) == [
        ("evt_a", ["a1", "a2"]),
        ("evt_b", ["b1", "b2"]),
    ]
