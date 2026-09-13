"""Semantic topic coverage across all reporting in a digest window."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.services.llm import _existing_llm_run, _prepare_llm_run
from common.db.models import EventClusterItem, NormalizedNewsItem, utcnow
from common.llm import LLMConfig, LLMWatchedTopics, llm_provider, prompt_hash

PROMPT_VERSION = "watched-topics-v2"
BATCH_SIZE = 50


async def _analyze(
    session: AsyncSession, *, snapshot: dict[str, object], topics: list[str],
    event_ids: set[str], config: LLMConfig,
) -> LLMWatchedTopics | None:
    prompt = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    target_id = prompt_hash(prompt)
    run = await _existing_llm_run(
        session, target_type="digest_topics", target_id=target_id,
        config=config, prompt_version=PROMPT_VERSION,
    )
    if run is not None and run.status == "succeeded":
        return LLMWatchedTopics.model_validate(run.result)
    run = await _prepare_llm_run(
        session, existing_run=run, target_type="digest_topics", target_id=target_id,
        config=config, prompt_version=PROMPT_VERSION, prompt=prompt, input_snapshot=snapshot,
    )
    await session.flush()
    try:
        result, usage = await llm_provider(config).summarize_watched_topics(prompt)
        run.usage = usage
        seen = set()
        for match in result.matches:
            if match.topic_index >= len(topics) or match.topic_index in seen:
                raise ValueError("Unknown or repeated watched topic index")
            if not set(match.event_ids) <= event_ids:
                raise ValueError("Unknown watched topic event ID")
            if not match.summary.strip():
                raise ValueError("Empty watched topic summary")
            if "supported_pairs" in snapshot:
                pairs = [list(pair) for pair in snapshot["supported_pairs"]]
                if any([match.topic_index, event_id] not in pairs for event_id in match.event_ids):
                    raise ValueError("Unsupported consolidated topic/event association")
            seen.add(match.topic_index)
        if "supported_pairs" in snapshot:
            expected = {pair[0] for pair in snapshot["supported_pairs"]}
            if seen != expected:
                raise ValueError("Consolidation omitted a matched topic")
        run.result = result.model_dump()
        run.status = "succeeded"
        run.updated_at = utcnow()
        return result
    except Exception as exc:  # noqa: BLE001 - preserve the ordinary digest on provider failure
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = utcnow()
        return None


async def build_watched_topics(
    session: AsyncSession, *, topics: list[str], since: datetime, until: datetime,
    config: LLMConfig | None,
) -> tuple[str | None, set[str]]:
    if not topics or config is None or not config.enabled or not config.api_key:
        return None, set()
    report_time = func.coalesce(
        NormalizedNewsItem.published_at,
        NormalizedNewsItem.fetched_at,
        NormalizedNewsItem.created_at,
    )
    rows = await session.execute(
        select(
            EventClusterItem.event_cluster_id, NormalizedNewsItem.id,
            NormalizedNewsItem.title, NormalizedNewsItem.snippet,
        )
        .join(NormalizedNewsItem, NormalizedNewsItem.id == EventClusterItem.news_item_id)
        .where(report_time >= since, report_time < until)
        .order_by(EventClusterItem.event_cluster_id, NormalizedNewsItem.id)
    )
    events: dict[str, list[dict[str, object]]] = {}
    for event_id, article_id, title, snippet in rows:
        events.setdefault(event_id, []).append(
            {"article_id": article_id, "headline": title, "description": snippet}
        )
    base = {
        "topics": topics,
        "window_start": since.astimezone(UTC).isoformat(),
        "window_end": until.astimezone(UTC).isoformat(),
    }
    ids = list(events)
    matches = []
    for offset in range(0, len(ids), BATCH_SIZE):
        batch = ids[offset:offset + BATCH_SIZE]
        result = await _analyze(
            session, topics=topics, event_ids=set(batch), config=config,
            snapshot={**base, "events": [
                {"event_id": event_id, "articles": events[event_id]} for event_id in batch
            ]},
        )
        if result is None:
            return None, set()
        matches.extend(result.matches)
    if not matches:
        return None, set()
    if len(ids) > BATCH_SIZE:
        result = await _analyze(
            session, topics=topics, event_ids=set(ids), config=config,
            snapshot={
                **base,
                "task": "Consolidate these findings into one concise summary per matched topic. "
                        "Retain all supported event IDs and topic associations; remove repetition.",
                "findings": [match.model_dump() for match in matches],
                "supported_pairs": sorted({
                    (match.topic_index, event_id)
                    for match in matches for event_id in match.event_ids
                }),
            },
        )
        if result is None:
            return None, set()
        # Keep evidence coverage even if the final prose omits a repeated event.
        summaries = {match.topic_index: match.summary for match in result.matches}
        if set(summaries) != {match.topic_index for match in matches}:
            return None, set()
    else:
        summaries = {match.topic_index: match.summary for match in matches}
    lines = ["Watched Topics"]
    lines.extend(
        f"{topics[index]}: {' '.join(summaries[index].split())}" for index in sorted(summaries)
    )
    return "\n".join(lines), {event_id for match in matches for event_id in match.event_ids}
