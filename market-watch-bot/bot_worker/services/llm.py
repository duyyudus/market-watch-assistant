from __future__ import annotations

import asyncio
from dataclasses import asdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    EventCluster,
    LLMAnalysisRun,
    NewsEntity,
    NormalizedNewsItem,
    utcnow,
)
from bot_worker.llm import (
    CLASSIFY_PROMPT_VERSION,
    CLUSTER_DECISION_PROMPT_VERSION,
    PROMPT_VERSION,
    SCORE_PROMPT_VERSION,
    SUMMARY_PROMPT_VERSION,
    LLMAnalysis,
    LLMClassification,
    LLMClusterDecision,
    LLMConfig,
    build_cluster_decision_prompt,
    build_event_analysis_prompt,
    build_event_score_prompt,
    build_event_summary_prompt,
    build_news_classification_prompt,
    event_input_snapshot,
    event_needs_llm_analysis,
    llm_provider,
    prompt_hash,
)
from bot_worker.scoring import ScoreInput, score_event
from bot_worker.services.market import market_move_score_for_cluster
from bot_worker.services.watchlists import tier_for_entities, watchlist_entries


async def latest_successful_llm_analysis(
    session: AsyncSession,
    event_cluster_id: str,
) -> LLMAnalysisRun | None:
    return await session.scalar(
        select(LLMAnalysisRun)
        .where(
            LLMAnalysisRun.target_type == "event_cluster",
            LLMAnalysisRun.target_id == event_cluster_id,
            LLMAnalysisRun.status == "succeeded",
            LLMAnalysisRun.prompt_version == PROMPT_VERSION,
        )
        .order_by(LLMAnalysisRun.created_at.desc())
        .limit(1)
    )
async def latest_llm_analysis(
    session: AsyncSession,
    event_cluster_id: str,
    *,
    prompt_version: str | None = None,
) -> LLMAnalysisRun | None:
    stmt = select(LLMAnalysisRun).where(
        LLMAnalysisRun.target_type == "event_cluster",
        LLMAnalysisRun.target_id == event_cluster_id,
    )
    if prompt_version is not None:
        stmt = stmt.where(LLMAnalysisRun.prompt_version == prompt_version)
    return await session.scalar(
        stmt.order_by(LLMAnalysisRun.updated_at.desc(), LLMAnalysisRun.created_at.desc()).limit(1)
    )
async def _existing_llm_run(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    config: LLMConfig,
    prompt_version: str,
) -> LLMAnalysisRun | None:
    return await session.scalar(
        select(LLMAnalysisRun).where(
            LLMAnalysisRun.target_type == target_type,
            LLMAnalysisRun.target_id == target_id,
            LLMAnalysisRun.provider == config.provider,
            LLMAnalysisRun.model == config.model,
            LLMAnalysisRun.prompt_version == prompt_version,
        )
    )
async def _prepare_llm_run(
    session: AsyncSession,
    *,
    existing_run: LLMAnalysisRun | None,
    target_type: str,
    target_id: str,
    config: LLMConfig,
    prompt_version: str,
    prompt: str,
    input_snapshot: dict[str, object],
) -> LLMAnalysisRun:
    if existing_run is None:
        run = LLMAnalysisRun(
            target_type=target_type,
            target_id=target_id,
            provider=config.provider,
            model=config.model,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash(prompt),
            input_snapshot=input_snapshot,
            status="running",
        )
        session.add(run)
        return run
    existing_run.prompt_hash = prompt_hash(prompt)
    existing_run.input_snapshot = input_snapshot
    existing_run.status = "running"
    existing_run.error_message = None
    existing_run.result = None
    existing_run.usage = None
    existing_run.updated_at = utcnow()
    return existing_run


def _news_classification_snapshot(item: NormalizedNewsItem) -> dict[str, object]:
    return {
        "news_item_id": item.id,
        "title": item.title,
        "snippet": item.snippet,
        "source_name": item.source_name,
        "source_score": item.source_score,
        "region": item.region,
        "asset_classes": item.asset_classes,
        "language": item.language,
        "raw_content_available": bool(getattr(item, "raw_content", None)),
    }


def cluster_candidate_target_id(news_item_id: str, event_cluster_id: str) -> str:
    return prompt_hash(f"{news_item_id}:{event_cluster_id}")


def _cluster_decision_snapshot(
    item: NormalizedNewsItem,
    cluster: EventCluster,
    *,
    similarity: float,
    entities: list[str],
    tickers: list[str],
) -> dict[str, object]:
    return {
        "news_item_id": item.id,
        "event_cluster_id": cluster.id,
        "similarity": similarity,
        "title": item.title,
        "snippet": item.snippet,
        "item_region": item.region,
        "item_asset_classes": item.asset_classes,
        "item_entities": entities,
        "item_tickers": tickers,
        "cluster_headline": cluster.canonical_headline,
        "cluster_regions": cluster.regions,
        "cluster_asset_classes": cluster.asset_classes,
        "cluster_entities": cluster.affected_entities,
        "cluster_tickers": cluster.affected_tickers,
    }


def _cluster_decision_should_attach(
    result: dict[str, object] | None,
    *,
    config: LLMConfig,
) -> bool:
    if not result:
        return False
    decision = str(result.get("decision") or "")
    confidence = int(result.get("confidence") or 0)
    return (
        decision == "same_event"
        and confidence >= config.cluster_decision_min_confidence
    )


async def resolve_llm_cluster_decision(
    *,
    session: AsyncSession,
    item: NormalizedNewsItem,
    cluster: EventCluster,
    similarity: float,
    config: LLMConfig,
    entities: list[str],
    tickers: list[str],
) -> tuple[bool, bool]:
    if not config.enabled or not config.api_key or not config.cluster_decision_enabled:
        return False, False

    target_id = cluster_candidate_target_id(item.id, cluster.id)
    run = await _existing_llm_run(
        session,
        target_type="cluster_candidate",
        target_id=target_id,
        config=config,
        prompt_version=CLUSTER_DECISION_PROMPT_VERSION,
    )
    if run is not None and run.status == "succeeded":
        return True, _cluster_decision_should_attach(run.result, config=config)

    prompt = build_cluster_decision_prompt(
        item,
        cluster,
        similarity=similarity,
        item_entities=entities,
        item_tickers=tickers,
    )
    run = await _prepare_llm_run(
        session,
        existing_run=run,
        target_type="cluster_candidate",
        target_id=target_id,
        config=config,
        prompt_version=CLUSTER_DECISION_PROMPT_VERSION,
        prompt=prompt,
        input_snapshot=_cluster_decision_snapshot(
            item,
            cluster,
            similarity=similarity,
            entities=entities,
            tickers=tickers,
        ),
    )
    await session.flush()
    try:
        result, usage = await llm_provider(config).decide_cluster_match(prompt)
    except Exception as exc:  # noqa: BLE001 - LLM clustering must fail open
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = utcnow()
        return True, False
    run.status = "succeeded"
    decision = LLMClusterDecision.model_validate(result)
    run.result = decision.model_dump()
    run.usage = usage
    run.updated_at = utcnow()
    return True, _cluster_decision_should_attach(run.result, config=config)


async def classify_news_item_with_llm(
    session: AsyncSession,
    *,
    item_id: str,
    config: LLMConfig,
    force: bool = False,
) -> LLMAnalysisRun | None:
    if not config.enabled or not config.api_key:
        return None
    item = await session.get(NormalizedNewsItem, item_id)
    if item is None:
        return None
    run = await _existing_llm_run(
        session,
        target_type="news_item",
        target_id=item_id,
        config=config,
        prompt_version=CLASSIFY_PROMPT_VERSION,
    )
    if run is not None and run.status == "succeeded" and not force:
        return run
    prompt = build_news_classification_prompt(item)
    run = await _prepare_llm_run(
        session,
        existing_run=run,
        target_type="news_item",
        target_id=item_id,
        config=config,
        prompt_version=CLASSIFY_PROMPT_VERSION,
        prompt=prompt,
        input_snapshot=_news_classification_snapshot(item),
    )
    await session.flush()
    try:
        result, usage = await llm_provider(config).classify_news_item(prompt)
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = utcnow()
        return run
    run.status = "succeeded"
    run.result = result.model_dump()
    run.usage = usage
    run.updated_at = utcnow()
    return run


def _classification_entities(
    *,
    item_id: str,
    result: dict[str, object],
) -> list[NewsEntity]:
    confidence = int(result.get("confidence") or 0)
    entities: list[NewsEntity] = []
    seen: set[tuple[str, str | None]] = set()
    for value in result.get("entities") or []:
        name = str(value).strip()
        if not name:
            continue
        key = (name.casefold(), None)
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            NewsEntity(
                news_item_id=item_id,
                entity_type="market_entity",
                raw_text=name,
                normalized_name=name,
                confidence=confidence,
            )
        )
    for value in result.get("tickers") or []:
        ticker = str(value).strip().upper()
        if not ticker:
            continue
        key = (ticker.casefold(), ticker)
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            NewsEntity(
                news_item_id=item_id,
                entity_type="ticker",
                raw_text=ticker,
                normalized_name=ticker,
                ticker=ticker,
                confidence=confidence,
            )
        )
    return entities


async def extract_entities_with_llm(
    session: AsyncSession,
    *,
    config: LLMConfig,
    limit: int = 500,
    force: bool = False,
) -> int:
    if not config.enabled or not config.api_key:
        return 0
    stmt = (
        select(NormalizedNewsItem)
        .where(NormalizedNewsItem.processing_status.in_(["normalized", "deduped"]))
        .order_by(NormalizedNewsItem.created_at.desc())
        .limit(limit)
    )
    items = list((await session.scalars(stmt)).all())
    provider = llm_provider(config)
    completed_runs: list[tuple[str, LLMAnalysisRun]] = []
    work_items: list[tuple[str, LLMAnalysisRun, str]] = []
    for item in items:
        existing_entities = list(
            (
                await session.scalars(
                    select(NewsEntity).where(NewsEntity.news_item_id == item.id).limit(1)
                )
            ).all()
        )
        if existing_entities and not force:
            continue
        if force and existing_entities:
            await session.execute(delete(NewsEntity).where(NewsEntity.news_item_id == item.id))

        run = await _existing_llm_run(
            session,
            target_type="news_item",
            target_id=item.id,
            config=config,
            prompt_version=CLASSIFY_PROMPT_VERSION,
        )
        if run is not None and run.status == "succeeded" and not force:
            completed_runs.append((item.id, run))
            continue

        prompt = build_news_classification_prompt(item)
        run = await _prepare_llm_run(
            session,
            existing_run=run,
            target_type="news_item",
            target_id=item.id,
            config=config,
            prompt_version=CLASSIFY_PROMPT_VERSION,
            prompt=prompt,
            input_snapshot=_news_classification_snapshot(item),
        )
        await session.flush()
        work_items.append((item.id, run, prompt))

    semaphore = asyncio.Semaphore(max(1, config.max_concurrency))

    async def classify_with_limit(
        item_id: str,
        run: LLMAnalysisRun,
        prompt: str,
    ) -> tuple[
        str,
        LLMAnalysisRun,
        LLMClassification | None,
        dict[str, object] | None,
        Exception | None,
    ]:
        async with semaphore:
            try:
                result, usage = await provider.classify_news_item(prompt)
            except Exception as exc:  # noqa: BLE001 - LLM failures must not block extraction
                return item_id, run, None, None, exc
            return item_id, run, result, usage, None

    results = await asyncio.gather(
        *(classify_with_limit(item_id, run, prompt) for item_id, run, prompt in work_items)
    )

    extracted = 0
    for item_id, run in completed_runs:
        if not run.result:
            continue
        entities = _classification_entities(item_id=item_id, result=run.result)
        if not entities:
            continue
        for entity in entities:
            session.add(entity)
        extracted += 1
    for item_id, run, result, usage, error in results:
        if error is not None:
            run.status = "failed"
            run.error_message = str(error)
            run.updated_at = utcnow()
            continue
        if result is None:
            run.status = "failed"
            run.error_message = "LLM classification returned no result"
            run.updated_at = utcnow()
            continue
        run.status = "succeeded"
        run.result = result.model_dump()
        run.usage = usage
        run.updated_at = utcnow()
        entities = _classification_entities(item_id=item_id, result=run.result)
        if not entities:
            continue
        for entity in entities:
            session.add(entity)
        extracted += 1
    return extracted


async def summarize_event_with_llm(
    session: AsyncSession,
    *,
    event_cluster_id: str,
    config: LLMConfig,
    force: bool = False,
) -> LLMAnalysisRun | None:
    if not config.enabled or not config.api_key:
        return None
    event = await session.get(EventCluster, event_cluster_id)
    if event is None:
        return None
    run = await _existing_llm_run(
        session,
        target_type="event_cluster",
        target_id=event_cluster_id,
        config=config,
        prompt_version=SUMMARY_PROMPT_VERSION,
    )
    if run is not None and run.status == "succeeded" and not force:
        return run
    prompt = build_event_summary_prompt(event)
    snapshot = event_input_snapshot(event, score_breakdown={}, market_move_score=0)
    run = await _prepare_llm_run(
        session,
        existing_run=run,
        target_type="event_cluster",
        target_id=event_cluster_id,
        config=config,
        prompt_version=SUMMARY_PROMPT_VERSION,
        prompt=prompt,
        input_snapshot=snapshot,
    )
    await session.flush()
    try:
        result, usage = await llm_provider(config).summarize_event(prompt)
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = utcnow()
        return run
    run.status = "succeeded"
    run.result = result.model_dump()
    run.usage = usage
    run.updated_at = utcnow()
    return run
async def score_event_with_llm(
    session: AsyncSession,
    *,
    event_cluster_id: str,
    config: LLMConfig,
    force: bool = False,
) -> LLMAnalysisRun | None:
    if not config.enabled or not config.api_key:
        return None
    event = await session.get(EventCluster, event_cluster_id)
    if event is None:
        return None
    run = await _existing_llm_run(
        session,
        target_type="event_cluster",
        target_id=event_cluster_id,
        config=config,
        prompt_version=SCORE_PROMPT_VERSION,
    )
    if run is not None and run.status == "succeeded" and not force:
        return run
    move_score = await market_move_score_for_cluster(session, event)
    watch_entries = await watchlist_entries(session)
    base_score = score_event(
        ScoreInput(
            top_source_score=event.top_source_score,
            source_count=event.source_count,
            watchlist_tier=tier_for_entities(
                entities=event.affected_entities or [],
                tickers=event.affected_tickers or [],
                entries=watch_entries,
            ),
            is_duplicate=False,
            is_stale=event.status == "stale",
            unique_high_quality_source_count=int(event.high_quality_source_count or 0),
            status=event.status,
            market_move_score=move_score,
        )
    )
    score_breakdown = asdict(base_score)
    prompt = build_event_score_prompt(
        event,
        score_breakdown=score_breakdown,
        market_move_score=move_score,
    )
    snapshot = event_input_snapshot(
        event,
        score_breakdown=score_breakdown,
        market_move_score=move_score,
    )
    run = await _prepare_llm_run(
        session,
        existing_run=run,
        target_type="event_cluster",
        target_id=event_cluster_id,
        config=config,
        prompt_version=SCORE_PROMPT_VERSION,
        prompt=prompt,
        input_snapshot=snapshot,
    )
    await session.flush()
    try:
        result, usage = await llm_provider(config).score_event(prompt)
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error_message = str(exc)
        run.updated_at = utcnow()
        return run
    run.status = "succeeded"
    score_result = result.model_dump()
    score_result["score_modifier"] = min(
        config.max_modifier,
        max(config.min_modifier, int(score_result["score_modifier"])),
    )
    run.result = score_result
    run.usage = usage
    run.updated_at = utcnow()
    return run
async def enrich_event_clusters_with_llm(
    session: AsyncSession,
    *,
    config: LLMConfig,
    limit: int = 50,
    event_cluster_id: str | None = None,
    force: bool = False,
) -> int:
    if not config.enabled or not config.api_key:
        return 0
    stmt = select(EventCluster).order_by(EventCluster.created_at.desc()).limit(limit)
    if event_cluster_id is not None:
        stmt = select(EventCluster).where(EventCluster.id == event_cluster_id)
    clusters = list((await session.scalars(stmt)).all())
    watch_entries = await watchlist_entries(session)
    provider = llm_provider(config)
    work_items: list[tuple[LLMAnalysisRun, str]] = []
    for cluster in clusters:
        run = await _existing_llm_run(
            session,
            target_type="event_cluster",
            target_id=cluster.id,
            config=config,
            prompt_version=config.prompt_version,
        )
        if run is not None and run.status == "succeeded":
            continue
        move_score = await market_move_score_for_cluster(session, cluster)
        base_score = score_event(
            ScoreInput(
                top_source_score=cluster.top_source_score,
                source_count=cluster.source_count,
                watchlist_tier=tier_for_entities(
                    entities=cluster.affected_entities or [],
                    tickers=cluster.affected_tickers or [],
                    entries=watch_entries,
                ),
                is_duplicate=False,
                is_stale=cluster.status == "stale",
                unique_high_quality_source_count=int(cluster.high_quality_source_count or 0),
                status=cluster.status,
                market_move_score=move_score,
            )
        )
        cluster.relevance_score = base_score.relevance_score
        cluster.final_score = base_score.final_score
        if not force and not event_needs_llm_analysis(
            cluster,
            config=config,
            market_move_score=move_score,
        ):
            continue
        score_breakdown = asdict(base_score)
        prompt = build_event_analysis_prompt(
            cluster,
            score_breakdown=score_breakdown,
            market_move_score=move_score,
        )
        snapshot = event_input_snapshot(
            cluster,
            score_breakdown=score_breakdown,
            market_move_score=move_score,
        )
        if run is None:
            run = LLMAnalysisRun(
                target_type="event_cluster",
                target_id=cluster.id,
                provider=config.provider,
                model=config.model,
                prompt_version=config.prompt_version,
                prompt_hash=prompt_hash(prompt),
                input_snapshot=snapshot,
                status="running",
            )
            session.add(run)
        else:
            run.prompt_hash = prompt_hash(prompt)
            run.input_snapshot = snapshot
            run.status = "running"
            run.error_message = None
            run.result = None
            run.usage = None
            run.updated_at = utcnow()
        await session.flush()
        work_items.append((run, prompt))

    semaphore = asyncio.Semaphore(max(1, config.max_concurrency))

    async def analyze_with_limit(
        run: LLMAnalysisRun,
        prompt: str,
    ) -> tuple[LLMAnalysisRun, LLMAnalysis | None, dict[str, object] | None, Exception | None]:
        async with semaphore:
            try:
                analysis, usage = await provider.analyze_event(prompt)
            except Exception as exc:  # noqa: BLE001 - LLM failures must not block pipeline scoring
                return run, None, None, exc
            return run, analysis, usage, None

    results = await asyncio.gather(
        *(analyze_with_limit(run, prompt) for run, prompt in work_items)
    )

    count = 0
    for run, analysis, usage, error in results:
        if error is not None:
            run.status = "failed"
            run.error_message = str(error)
            run.updated_at = utcnow()
            continue
        if analysis is None:
            run.status = "failed"
            run.error_message = "LLM analysis returned no result"
            run.updated_at = utcnow()
            continue
        result = analysis.model_dump()
        result["score_modifier"] = min(
            config.max_modifier,
            max(config.min_modifier, int(result["score_modifier"])),
        )
        run.status = "succeeded"
        run.result = result
        run.usage = usage
        run.updated_at = utcnow()
        count += 1
    return count
