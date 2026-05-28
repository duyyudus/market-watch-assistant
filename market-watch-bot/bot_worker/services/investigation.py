from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    AgentInvestigation,
    EventCluster,
    MarketMove,
    MissedCatalystReview,
    NormalizedNewsItem,
    utcnow,
)
from bot_worker.investigation import (
    BraveSearchClient,
    InvestigationConfig,
    should_queue_event_investigation,
)
from bot_worker.llm import (
    INVESTIGATION_PROMPT_VERSION,
    LLMConfig,
    build_investigation_prompt,
    prompt_hash,
)
from bot_worker.normalize import normalize_text
from bot_worker.services.llm import llm_provider

LOCAL_EVIDENCE_STOPWORDS = {
    "after",
    "and",
    "are",
    "for",
    "from",
    "into",
    "market",
    "markets",
    "news",
    "official",
    "reported",
    "source",
    "the",
    "with",
}


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _event_snapshot(event: EventCluster) -> dict[str, object]:
    return _json_safe({
        "event_cluster_id": event.id,
        "headline": event.canonical_headline,
        "summary": event.summary,
        "status": event.status,
        "regions": event.regions,
        "asset_classes": event.asset_classes,
        "affected_entities": event.affected_entities,
        "affected_tickers": event.affected_tickers,
        "source_count": event.source_count,
        "top_source_score": event.top_source_score,
        "final_score": event.final_score,
        "created_at": event.created_at,
    })


def _move_snapshot(move: MarketMove) -> dict[str, object]:
    return _json_safe({
        "market_move_id": move.id,
        "asset_symbol": move.asset_symbol,
        "asset_class": move.asset_class,
        "exchange": move.exchange,
        "timestamp": move.timestamp,
        "window": move.window,
        "price_change_pct": move.price_change_pct,
        "volume_change_pct": move.volume_change_pct,
        "value_traded_change_pct": move.value_traded_change_pct,
        "z_score": move.z_score,
    })


def _asset_snapshot(symbol: str, *, since: datetime) -> dict[str, object]:
    return _json_safe({
        "asset_symbol": symbol.upper(),
        "since": since,
    })


def _search_query_for_snapshot(snapshot: dict[str, object]) -> str:
    if "headline" in snapshot:
        return normalize_text(str(snapshot["headline"]))
    symbol = str(snapshot.get("asset_symbol") or "")
    window = str(snapshot.get("window") or "")
    return normalize_text(f"{symbol} market catalyst news official {window}")


def _search_queries_for_snapshot(snapshot: dict[str, object]) -> list[str]:
    primary = _search_query_for_snapshot(snapshot)
    if "headline" not in snapshot:
        return [primary]
    source_terms = [
        value
        for value in [
            *snapshot.get("affected_entities", []),
            *snapshot.get("affected_tickers", []),
        ]
        if isinstance(value, str) and value
    ]
    official_subject = source_terms[0] if source_terms else primary
    official_query = normalize_text(
        f"{official_subject} official regulator filing announcement"
    )
    if official_query == primary:
        return [primary]
    return [primary, official_query]


def _result_domain(evidence: dict[str, object]) -> str:
    url = str(evidence.get("url") or "")
    hostname = urlparse(url).hostname or ""
    return hostname.lower().removeprefix("www.")


def _ranked_unique_search_evidence(
    results: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    seen_urls: set[str] = set()
    seen_domains: set[str] = set()
    unique: list[tuple[int, dict[str, object]]] = []
    for index, item in enumerate(results):
        url = str(item.get("url") or "")
        domain = _result_domain(item)
        if url in seen_urls or (domain and domain in seen_domains):
            continue
        seen_urls.add(url)
        if domain:
            seen_domains.add(domain)
        unique.append((index, item))
    quality_rank = {"official": 0, "high_quality": 1, "media": 2, "unknown": 3}
    unique.sort(key=lambda row: (quality_rank.get(str(row[1].get("source_quality")), 3), row[0]))
    return [item for _, item in unique[:limit]]


def _local_context_terms(snapshot: dict[str, object]) -> set[str]:
    raw_parts: list[str] = []
    for key in ("headline", "summary"):
        value = snapshot.get(key)
        if isinstance(value, str):
            raw_parts.append(value)
    for key in ("affected_entities",):
        values = snapshot.get(key, [])
        if isinstance(values, list):
            raw_parts.extend(str(value) for value in values if value)
    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.-]{2,}", " ".join(raw_parts))
    }
    return {token for token in tokens if token not in LOCAL_EVIDENCE_STOPWORDS}


def _local_relevance_score(
    row: NormalizedNewsItem,
    *,
    symbols: list[str],
    entities: list[str],
    context_terms: set[str],
) -> int:
    text = f"{row.title} {row.snippet or ''}".lower()
    score = min(10, max(0, int(row.source_score or 0) // 10))
    for symbol in symbols:
        if symbol.lower() in text:
            score += 20
    for entity in entities:
        if entity.lower() in text:
            score += 25
    matched_terms = {term for term in context_terms if term in text}
    score += min(30, len(matched_terms) * 5)
    return score


async def _recent_news_evidence(
    session: AsyncSession,
    *,
    symbols: list[str],
    entities: list[str],
    context_terms: set[str],
    since: datetime,
    limit: int = 5,
) -> list[dict[str, object]]:
    if not symbols and not entities and not context_terms:
        return []
    rows = list(
        (
            await session.scalars(
                select(NormalizedNewsItem)
                .where(NormalizedNewsItem.created_at >= since)
                .order_by(NormalizedNewsItem.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    evidence: list[tuple[int, dict[str, object]]] = []
    min_score = 30 if context_terms or entities else 20
    for row in rows:
        relevance_score = _local_relevance_score(
            row,
            symbols=symbols,
            entities=entities,
            context_terms=context_terms,
        )
        if relevance_score < min_score:
            continue
        evidence.append(
            (
                relevance_score,
                {
                    "kind": "db_news",
                    "news_item_id": row.id,
                    "title": row.title,
                    "snippet": row.snippet,
                    "url": row.url,
                    "source_name": row.source_name,
                    "source_score": row.source_score,
                    "relevance_score": relevance_score,
                },
            )
        )
    evidence.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in evidence]


async def gather_investigation_evidence(
    session: AsyncSession,
    *,
    snapshot: dict[str, object],
    config: InvestigationConfig,
    search_client: object | None = None,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    symbols = [
        str(value)
        for value in snapshot.get("affected_tickers", [])
        if isinstance(value, str) and value
    ]
    entities = [
        str(value)
        for value in snapshot.get("affected_entities", [])
        if isinstance(value, str) and value
    ]
    if "asset_symbol" in snapshot:
        symbols.append(str(snapshot["asset_symbol"]))
    context_terms = _local_context_terms(snapshot)
    local_since = datetime.now(UTC) - timedelta(days=config.local_evidence_lookback_days)
    if hasattr(session, "begin_nested"):
        async with session.begin_nested():
            evidence.extend(
                await _recent_news_evidence(
                    session,
                    symbols=symbols,
                    entities=entities,
                    context_terms=context_terms,
                    since=local_since,
                    limit=config.local_evidence_limit,
                )
            )
    else:
        evidence.extend(
            await _recent_news_evidence(
                session,
                symbols=symbols,
                entities=entities,
                context_terms=context_terms,
                since=local_since,
                limit=config.local_evidence_limit,
            )
        )
    client = search_client
    if client is None and config.brave_search_api_key:
        client = BraveSearchClient(
            api_key=config.brave_search_api_key,
            timeout_seconds=config.timeout_seconds,
        )
    if client is None:
        return evidence
    search_evidence: list[dict[str, object]] = []
    for query in _search_queries_for_snapshot(snapshot):
        results = await client.search(query, count=config.max_search_results)
        search_evidence.extend(result.as_evidence() for result in results)
    remaining = max(0, config.max_evidence_items - len(evidence))
    evidence.extend(_ranked_unique_search_evidence(search_evidence, limit=remaining))
    return evidence[: config.max_evidence_items]


async def latest_successful_investigation(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: str,
) -> AgentInvestigation | None:
    return await session.scalar(
        select(AgentInvestigation)
        .where(AgentInvestigation.target_type == target_type)
        .where(AgentInvestigation.target_id == target_id)
        .where(AgentInvestigation.status == "succeeded")
        .order_by(AgentInvestigation.updated_at.desc())
        .limit(1)
    )


async def list_pending_investigations(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> list[AgentInvestigation]:
    return list(
        (
            await session.scalars(
                select(AgentInvestigation)
                .where(AgentInvestigation.status == "pending")
                .order_by(AgentInvestigation.created_at.asc())
                .limit(limit)
            )
        ).all()
    )


async def run_pending_investigations(
    session: AsyncSession,
    *,
    config: InvestigationConfig,
    llm_config: LLMConfig,
    limit: int = 20,
) -> dict[str, int]:
    rows = list(
        (
            await session.scalars(
                select(AgentInvestigation)
                .where(AgentInvestigation.status == "pending")
                .order_by(AgentInvestigation.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    counts = {"pending": len(rows), "completed": 0, "failed": 0}
    for run in rows:
        if run.target_type not in SUPPORTED_PENDING_TARGET_TYPES:
            run.status = "failed"
            run.error_message = f"Unsupported investigation target type: {run.target_type}"
            run.updated_at = utcnow()
            await session.flush()
            counts["failed"] += 1
            continue
        result = await run_existing_investigation(
            session,
            run,
            config=config,
            llm_config=llm_config,
        )
        if result.status == "succeeded":
            counts["completed"] += 1
        else:
            counts["failed"] += 1
    return counts


async def queue_investigation(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    trigger_reason: str,
    input_snapshot: dict[str, object],
) -> AgentInvestigation:
    run = AgentInvestigation(
        target_type=target_type,
        target_id=target_id,
        trigger_reason=trigger_reason,
        status="pending",
        input_snapshot=_json_safe(input_snapshot),
        evidence=[],
    )
    session.add(run)
    await session.flush()
    return run


async def _run_structured_investigation(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    trigger_reason: str,
    snapshot: dict[str, object],
    config: InvestigationConfig,
    llm_config: LLMConfig,
    search_client: object | None = None,
) -> AgentInvestigation:
    run = AgentInvestigation(
        target_type=target_type,
        target_id=target_id,
        trigger_reason=trigger_reason,
        status="pending",
        input_snapshot=_json_safe(snapshot),
        evidence=[],
    )
    session.add(run)
    return await _execute_investigation_run(
        session,
        run,
        snapshot=snapshot,
        config=config,
        llm_config=llm_config,
        search_client=search_client,
    )


async def _execute_investigation_run(
    session: AsyncSession,
    run: AgentInvestigation,
    *,
    snapshot: dict[str, object],
    config: InvestigationConfig,
    llm_config: LLMConfig,
    search_client: object | None = None,
) -> AgentInvestigation:
    run.status = "running"
    run.input_snapshot = _json_safe(snapshot)
    run.evidence = []
    run.result = None
    run.usage = None
    run.error_message = None
    run.provider = llm_config.provider
    run.model = llm_config.model
    run.prompt_version = INVESTIGATION_PROMPT_VERSION
    run.updated_at = utcnow()
    await session.flush()
    try:
        evidence = await gather_investigation_evidence(
            session,
            snapshot=snapshot,
            config=config,
            search_client=search_client,
        )
        prompt = build_investigation_prompt(
            target_type=run.target_type,
            input_snapshot=snapshot,
            evidence=evidence,
        )
        run.evidence = _json_safe(evidence)
        run.prompt_hash = prompt_hash(prompt)
        if not llm_config.enabled or not llm_config.api_key:
            raise ValueError(f"{llm_config.api_key_env} is required for investigation analysis")
        result, usage = await llm_provider(llm_config).investigate_event(prompt)
    except Exception as exc:  # noqa: BLE001 - investigation failures must be durable, not fatal
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = utcnow()
        return run
    result_data = result.model_dump()
    result_data["suggested_score_modifier"] = min(
        config.max_modifier,
        max(config.min_modifier, int(result_data["suggested_score_modifier"])),
    )
    run.status = "succeeded"
    run.result = result_data
    run.usage = usage
    run.updated_at = utcnow()
    return run


SUPPORTED_PENDING_TARGET_TYPES = {
    "event_cluster",
    "market_move",
    "asset",
    "missed_catalyst_review",
}


async def run_existing_investigation(
    session: AsyncSession,
    run: AgentInvestigation,
    *,
    config: InvestigationConfig,
    llm_config: LLMConfig,
    search_client: object | None = None,
) -> AgentInvestigation:
    if run.target_type not in SUPPORTED_PENDING_TARGET_TYPES:
        run.status = "failed"
        run.error_message = f"Unsupported investigation target type: {run.target_type}"
        run.updated_at = utcnow()
        await session.flush()
        return run
    return await _execute_investigation_run(
        session,
        run,
        snapshot=run.input_snapshot,
        config=config,
        llm_config=llm_config,
        search_client=search_client,
    )


async def run_event_investigation(
    session: AsyncSession,
    *,
    event_id: str,
    config: InvestigationConfig,
    llm_config: LLMConfig,
    search_client: object | None = None,
    trigger_reason: str = "manual",
) -> AgentInvestigation:
    event = await session.get(EventCluster, event_id)
    if event is None:
        raise ValueError(f"Event cluster not found: {event_id}")
    return await _run_structured_investigation(
        session,
        target_type="event_cluster",
        target_id=event_id,
        trigger_reason=trigger_reason,
        snapshot=_event_snapshot(event),
        config=config,
        llm_config=llm_config,
        search_client=search_client,
    )


async def run_move_investigation(
    session: AsyncSession,
    *,
    move_id: str,
    config: InvestigationConfig,
    llm_config: LLMConfig,
    search_client: object | None = None,
    trigger_reason: str = "manual",
) -> AgentInvestigation:
    move = await session.get(MarketMove, move_id)
    if move is None:
        raise ValueError(f"Market move not found: {move_id}")
    return await _run_structured_investigation(
        session,
        target_type="market_move",
        target_id=move_id,
        trigger_reason=trigger_reason,
        snapshot=_move_snapshot(move),
        config=config,
        llm_config=llm_config,
        search_client=search_client,
    )


async def run_asset_investigation(
    session: AsyncSession,
    *,
    symbol: str,
    since: datetime,
    config: InvestigationConfig,
    llm_config: LLMConfig,
    search_client: object | None = None,
    trigger_reason: str = "manual",
) -> AgentInvestigation:
    target_id = symbol.upper()
    return await _run_structured_investigation(
        session,
        target_type="asset",
        target_id=target_id,
        trigger_reason=trigger_reason,
        snapshot=_asset_snapshot(target_id, since=since),
        config=config,
        llm_config=llm_config,
        search_client=search_client,
    )


async def queue_investigations_for_missed_catalysts(
    session: AsyncSession,
    *,
    config: InvestigationConfig,
    limit: int = 20,
) -> int:
    rows = list(
        (
            await session.scalars(
                select(MissedCatalystReview)
                .where(MissedCatalystReview.status == "pending")
                .order_by(MissedCatalystReview.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    count = 0
    for review in rows:
        if review.detected_event_cluster_id is not None:
            continue
        existing = await session.scalar(
            select(AgentInvestigation)
            .where(AgentInvestigation.target_type == "missed_catalyst_review")
            .where(AgentInvestigation.target_id == review.id)
            .where(AgentInvestigation.status.in_(("pending", "running", "succeeded")))
            .limit(1)
        )
        if existing is not None:
            continue
        await queue_investigation(
            session,
            target_type="missed_catalyst_review",
            target_id=review.id,
            trigger_reason="auto_missed_catalyst",
            input_snapshot={
                "review_id": review.id,
                "asset_symbol": review.asset_symbol,
                "asset_class": review.asset_class,
                "move_window": review.move_window,
                "price_change_pct": review.price_change_pct,
                "volume_change_pct": review.volume_change_pct,
            },
        )
        count += 1
    return count


async def queue_investigations_for_events(
    session: AsyncSession,
    *,
    config: InvestigationConfig,
    limit: int = 50,
) -> int:
    return len(await queue_event_investigation_runs(session, config=config, limit=limit))


async def queue_event_investigation_runs(
    session: AsyncSession,
    *,
    config: InvestigationConfig,
    limit: int = 50,
) -> list[AgentInvestigation]:
    if not config.enabled:
        return []
    rows = list(
        (
            await session.scalars(
                select(EventCluster).order_by(EventCluster.created_at.desc()).limit(limit)
            )
        ).all()
    )
    runs: list[AgentInvestigation] = []
    for event in rows:
        if not should_queue_event_investigation(event, config=config):
            continue
        existing = await session.scalar(
            select(AgentInvestigation)
            .where(AgentInvestigation.target_type == "event_cluster")
            .where(AgentInvestigation.target_id == event.id)
            .where(AgentInvestigation.status.in_(("pending", "running", "succeeded")))
            .limit(1)
        )
        if existing is not None:
            continue
        run = await queue_investigation(
            session,
            target_type="event_cluster",
            target_id=event.id,
            trigger_reason="auto_event_uncertain",
            input_snapshot=_event_snapshot(event),
        )
        runs.append(run)
    return runs
