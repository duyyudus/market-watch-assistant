import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot_worker.services import watched_topics as service
from bot_worker.services.digests import build_digest_record
from common.db.models import (
    AppSetting,
    Base,
    EventCluster,
    EventClusterItem,
    LLMAnalysisRun,
    NormalizedNewsItem,
)
from common.llm import LLMConfig, LLMTopicMatch, LLMWatchedTopics

SINCE = datetime(2026, 9, 12, tzinfo=UTC)
UNTIL = SINCE + timedelta(days=1)
CONFIG = LLMConfig(enabled=True, api_key="test")
TOPICS = ["rate decision next FOMC meeting", "Luật bất động sản"]


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def add_event(session, index, *, at=SINCE, score=1):
    event_id = f"evt_{index:03}"
    article_id = f"news_{index:03}"
    session.add(EventCluster(
        id=event_id, canonical_headline="Old cluster title must not be used",
        final_score=score,
    ))
    session.add(NormalizedNewsItem(
        id=article_id, source_id="source", title="US central bank prepares to ease borrowing costs",
        snippet="Officials will vote on monetary policy tomorrow.", url=f"https://test/{index}",
        source_name="Test", source_type="rss", source_score=80, published_at=at,
        region="us", title_hash=str(index), normalized_text_hash=str(index),
    ))
    session.add(EventClusterItem(event_cluster_id=event_id, news_item_id=article_id))
    await session.flush()
    return event_id


class Provider:
    def __init__(self, *, fail=False, invalid=False, empty=False):
        self.calls = []
        self.fail = fail
        self.invalid = invalid
        self.empty = empty

    async def summarize_watched_topics(self, prompt):
        data = json.loads(prompt)
        self.calls.append(data)
        if self.fail:
            raise RuntimeError("provider unavailable")
        if self.empty:
            return LLMWatchedTopics(matches=[]), {}
        if "findings" in data:
            ids = [event_id for match in data["findings"] for event_id in match["event_ids"]]
        else:
            ids = [event["event_id"] for event in data["events"]]
        return LLMWatchedTopics(matches=[LLMTopicMatch(
            topic_index=0, event_ids=["invented"] if self.invalid else ids,
            summary="The US central bank is preparing to ease monetary policy.",
        )]), {"total_tokens": 100}


@pytest.mark.asyncio
async def test_all_events_window_batches_and_cache(session, monkeypatch):
    for i in range(51):
        await add_event(session, i)
    await add_event(session, 100, at=UNTIL)
    await add_event(session, 101, at=SINCE - timedelta(seconds=1))
    provider = Provider()
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    args = dict(topics=TOPICS, since=SINCE, until=UNTIL, config=CONFIG)
    content, ids = await service.build_watched_topics(session, **args)
    assert len(ids) == 51
    assert "Watched Topics\nrate decision" in content
    assert TOPICS[1] not in content
    assert len(provider.calls) == 3
    assert [len(call["events"]) for call in provider.calls[:2]] == [50, 1]
    assert "Old cluster title" not in json.dumps(provider.calls)
    assert "borrowing costs" in json.dumps(provider.calls)
    assert await service.build_watched_topics(session, **args) == (content, ids)
    assert len(provider.calls) == 3
    article = await session.get(NormalizedNewsItem, "news_000")
    article.snippet = "Officials changed their outlook."
    await session.flush()
    await service.build_watched_topics(session, **args)
    # Changed evidence reruns its batch; identical findings reuse consolidation.
    assert len(provider.calls) == 4
    await service.build_watched_topics(session, **{**args, "topics": ["monetary policy"]})
    assert len(provider.calls) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fail", "invalid", "empty", "disabled"])
async def test_no_keyword_fallback(session, monkeypatch, mode):
    await add_event(session, 1)
    provider = Provider(**{mode: True}) if mode != "disabled" else Provider()
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    result = await service.build_watched_topics(
        session, topics=TOPICS, since=SINCE, until=UNTIL,
        config=LLMConfig(enabled=False) if mode == "disabled" else CONFIG,
    )
    assert result == (None, set())
    runs = list((await session.scalars(select(LLMAnalysisRun))).all())
    if mode in {"fail", "invalid"}:
        assert runs[0].status == "failed"
        assert runs[0].error_message
    elif mode == "disabled":
        assert not provider.calls


@pytest.mark.asyncio
async def test_digest_includes_low_score_matches_and_unique_count(session, monkeypatch):
    await add_event(session, 1, score=80)
    await add_event(session, 2, score=1)
    session.add(AppSetting(key="watched_topics", value={"topics": TOPICS}))
    await session.flush()
    provider = Provider()
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    from bot_worker.services import llm

    async def normal_narrative(*args, **kwargs):
        return "Normal market narrative."

    async def edit_narrative(*args, **kwargs):
        return kwargs["general_content"]

    monkeypatch.setattr(llm, "build_digest_narrative", normal_narrative)
    monkeypatch.setattr(llm, "remove_watched_topic_overlap", edit_narrative)
    digest = await build_digest_record(
        session, since=SINCE, until=UNTIL, threshold=30, config=CONFIG,
    )
    assert digest.event_count == 2
    assert digest.content.startswith("Normal market narrative.\n\nWatched Topics\n")
    digest = await build_digest_record(
        session, since=SINCE, until=UNTIL, threshold=100, config=CONFIG,
    )
    assert digest.event_count == 2
    assert "Watched Topics" in digest.content


@pytest.mark.asyncio
async def test_empty_topics_skips_provider(session, monkeypatch):
    await add_event(session, 1)
    provider = Provider()
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    digest = await build_digest_record(
        session, since=SINCE, until=UNTIL, threshold=30, config=None,
    )
    assert "Watched Topics" not in digest.content
    assert not provider.calls


@pytest.mark.asyncio
async def test_multiple_topics_preserve_order_and_deduplicate_event_count(session, monkeypatch):
    event_id = await add_event(session, 1)

    class MultipleProvider:
        async def summarize_watched_topics(self, prompt):
            return LLMWatchedTopics(matches=[
                LLMTopicMatch(topic_index=1, event_ids=[event_id], summary="Property law changed."),
                LLMTopicMatch(
                    topic_index=0, event_ids=[event_id], summary="Monetary policy changed.",
                ),
            ]), {}

    monkeypatch.setattr(service, "llm_provider", lambda _: MultipleProvider())
    content, ids = await service.build_watched_topics(
        session, topics=TOPICS, since=SINCE, until=UNTIL, config=CONFIG,
    )
    assert content.index(TOPICS[0]) < content.index(TOPICS[1])
    assert ids == {event_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["second_batch", "consolidation"])
async def test_partial_failure_discards_all_topic_content(session, monkeypatch, failure_stage):
    for i in range(51):
        await add_event(session, i)

    class PartialProvider(Provider):
        async def summarize_watched_topics(self, prompt):
            data = json.loads(prompt)
            if (failure_stage == "second_batch" and len(self.calls) == 1) or (
                failure_stage == "consolidation" and "findings" in data
            ):
                raise RuntimeError("temporary failure")
            return await super().summarize_watched_topics(prompt)

    provider = PartialProvider()
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    assert await service.build_watched_topics(
        session, topics=TOPICS, since=SINCE, until=UNTIL, config=CONFIG,
    ) == (None, set())
    runs = list((await session.scalars(select(LLMAnalysisRun))).all())
    assert any(run.status == "succeeded" for run in runs)
    assert any(run.status == "failed" for run in runs)


@pytest.mark.asyncio
async def test_no_events_skips_provider(session, monkeypatch):
    provider = Provider()
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    assert await service.build_watched_topics(
        session, topics=TOPICS, since=SINCE, until=UNTIL, config=CONFIG,
    ) == (None, set())
    assert not provider.calls


@pytest.mark.asyncio
async def test_topic_languages_survive_batch_consolidation(session, monkeypatch):
    from common.llm import OpenRouterChatProvider

    await add_event(session, 1)
    await add_event(session, 2)
    monkeypatch.setattr(service, "BATCH_SIZE", 1)
    provider = OpenRouterChatProvider(CONFIG)
    calls = []
    vietnamese = "Việt Nam nhập siêu hơn 20 tỉ USD trong tám tháng."
    english = "The central bank is preparing to ease monetary policy."

    async def complete_structured(**kwargs):
        data = json.loads(kwargs["prompt"])
        calls.append(data)
        instructions = kwargs["system_message"]
        assert "For each topic independently" in instructions
        assert "same language, including during consolidation" in instructions
        assert "regardless of article or finding language" in instructions
        if "events" in data:
            ids = [event["event_id"] for event in data["events"]]
        else:
            ids = sorted({eid for finding in data["findings"] for eid in finding["event_ids"]})
        return {"matches": [
            {"topic_index": 0, "event_ids": ids, "summary": vietnamese},
            {"topic_index": 1, "event_ids": ids, "summary": english},
        ]}, {}

    monkeypatch.setattr(provider, "complete_structured", complete_structured)
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    content, ids = await service.build_watched_topics(
        session, topics=["tình hình nhập siêu", TOPICS[0]],
        since=SINCE, until=UNTIL, config=CONFIG,
    )
    assert len(calls) == 3
    assert "findings" in calls[-1]
    assert f"tình hình nhập siêu: {vietnamese}" in content
    assert f"{TOPICS[0]}: {english}" in content
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_language_change_does_not_reuse_v1_cache(session, monkeypatch):
    await add_event(session, 1)
    provider = Provider()
    monkeypatch.setattr(service, "llm_provider", lambda _: provider)
    current_version = service.PROMPT_VERSION
    args = dict(topics=TOPICS, since=SINCE, until=UNTIL, config=CONFIG)
    monkeypatch.setattr(service, "PROMPT_VERSION", "watched-topics-v1")
    await service.build_watched_topics(session, **args)
    monkeypatch.setattr(service, "PROMPT_VERSION", current_version)
    await service.build_watched_topics(session, **args)
    assert len(provider.calls) == 2
    runs = list((await session.scalars(select(LLMAnalysisRun))).all())
    assert {run.prompt_version for run in runs} == {"watched-topics-v1", current_version}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mixed", "fully_covered", "failure", "no_match"])
async def test_watched_coverage_takes_priority_in_general_digest(session, monkeypatch, mode):
    from bot_worker.services import llm
    from common.llm import OpenRouterChatProvider

    await add_event(session, 1, score=80)
    await add_event(session, 2, score=1)
    general = (
        "Vietnam's trade deficit widened as equities gained.\n\n"
        "Vietnam Economy\nThe trade deficit exceeded $20 billion. Equities gained 2%.\n\n"
        "Trade\nImports exceeded exports by more than $20 billion."
    )
    watched = "Watched Topics\ntình hình nhập siêu: Việt Nam nhập siêu hơn 20 tỉ USD."

    async def normal_narrative(*args, **kwargs):
        return general

    async def watched_narrative(*args, **kwargs):
        return (None, set()) if mode == "no_match" else (watched, {"evt_001", "evt_002"})

    provider = OpenRouterChatProvider(CONFIG)
    calls = []

    async def complete_structured(**kwargs):
        payload = json.loads(kwargs["prompt"])
        calls.append(payload)
        assert payload["general_content"] == general
        assert payload["watched_content"] == watched
        instructions = kwargs["system_message"]
        assert "Compare meaning across languages" in instructions
        assert "preserve unrelated facts and caveats" in instructions
        assert "Do not reproduce, translate, or edit Watched Topics" in instructions
        assert "shared broad category alone is not duplication" in instructions
        if mode == "failure":
            raise RuntimeError("Editing service unavailable")
        return {
            "lead": "Equities gained." if mode == "mixed" else "",
            "sections": [{"topic": "Vietnam Equities", "body": "Equities gained 2%."}]
            if mode == "mixed" else [],
        }, {"total_tokens": 42}

    monkeypatch.setattr(llm, "build_digest_narrative", normal_narrative)
    monkeypatch.setattr(service, "build_watched_topics", watched_narrative)
    monkeypatch.setattr(llm, "llm_provider", lambda _: provider)
    monkeypatch.setattr(provider, "complete_structured", complete_structured)
    digest = await build_digest_record(
        session, since=SINCE, until=UNTIL, threshold=30, config=CONFIG,
    )
    if mode in {"failure", "no_match"}:
        assert digest.content == general
        assert digest.event_count == 1
    else:
        assert digest.content.endswith(watched)
        assert "trade deficit" not in digest.content
        assert "Imports exceeded exports" not in digest.content
        assert digest.event_count == 2
        if mode == "mixed":
            assert "Equities gained 2%." in digest.content
        else:
            assert digest.content == watched
    runs = list((await session.scalars(select(LLMAnalysisRun))).all())
    if mode == "no_match":
        assert not calls
        assert not runs
    else:
        assert runs[0].target_type == "digest_edit"
        assert runs[0].status == ("failed" if mode == "failure" else "succeeded")


@pytest.mark.asyncio
async def test_overlap_edit_cache_tracks_both_texts_and_empty_results(session, monkeypatch):
    from bot_worker.services import llm
    from common.llm import LLMEditedDigest

    calls = []

    class EditingProvider:
        async def remove_digest_overlap(self, prompt):
            calls.append(json.loads(prompt))
            return LLMEditedDigest(lead="", sections=[]), {}

    monkeypatch.setattr(llm, "llm_provider", lambda _: EditingProvider())
    args = dict(
        general_content="Trade deficit widened.", watched_content="Nhập siêu tăng.",
        since=SINCE, until=UNTIL, config=CONFIG,
    )
    assert await llm.remove_watched_topic_overlap(session, **args) == ""
    assert await llm.remove_watched_topic_overlap(session, **args) == ""
    assert len(calls) == 1
    await llm.remove_watched_topic_overlap(
        session, **{**args, "watched_content": "Nhập siêu hơn 20 tỉ USD."},
    )
    await llm.remove_watched_topic_overlap(
        session, **{**args, "general_content": "Exports declined."},
    )
    assert len(calls) == 3
