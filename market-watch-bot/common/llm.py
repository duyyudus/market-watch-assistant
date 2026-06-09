from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator

from common.db.models import EventCluster, NormalizedNewsItem
from common.normalize import content_hash, normalize_text

if TYPE_CHECKING:
    from common.config import Settings


PROMPT_VERSION = "event-v1"
CLASSIFY_PROMPT_VERSION = "classify-v1"
SCORE_PROMPT_VERSION = "score-v1"
SUMMARY_PROMPT_VERSION = "summarize-v1"
CLUSTER_DECISION_PROMPT_VERSION = "cluster-decision-v1"
INVESTIGATION_PROMPT_VERSION = "investigation-v1"


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    provider: str = "openrouter"
    api_base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-4.1-mini"
    service_tier: Literal["flex", "priority"] | None = None
    api_key_env: str = "OPENROUTER_API_KEY"
    api_key: str | None = None
    prompt_version: str = PROMPT_VERSION
    temperature: float = 0.1
    max_tokens: int = 700
    timeout_seconds: int = 45
    max_concurrency: int = 3
    high_score_threshold: int = 80
    single_source_score_threshold: int = 90
    market_move_score_threshold: int = 70
    relevance_score_threshold: int = 80
    min_modifier: int = -10
    max_modifier: int = 10
    cluster_decision_enabled: bool = True
    cluster_ambiguous_min_similarity: float = 0.78
    cluster_decision_min_confidence: int = 70
    cluster_decision_candidate_limit: int = 3

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMConfig:
        api_key = os.environ.get(settings.llm.api_key_env)
        if api_key is None and settings.llm.api_key_env == "OPENROUTER_API_KEY":
            api_key = settings.openrouter_api_key
        return cls(
            enabled=settings.llm.enabled,
            provider=settings.llm.provider,
            api_base_url=settings.llm.api_base_url,
            model=settings.llm.model,
            service_tier=getattr(settings.llm, "service_tier", None),
            api_key_env=settings.llm.api_key_env,
            api_key=api_key,
            prompt_version=settings.llm.prompt_version,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            timeout_seconds=settings.llm.timeout_seconds,
            max_concurrency=settings.llm.max_concurrency,
            high_score_threshold=settings.llm.high_score_threshold,
            single_source_score_threshold=settings.llm.single_source_score_threshold,
            market_move_score_threshold=settings.llm.market_move_score_threshold,
            relevance_score_threshold=settings.llm.relevance_score_threshold,
            min_modifier=settings.llm.min_modifier,
            max_modifier=settings.llm.max_modifier,
            cluster_decision_enabled=settings.llm.cluster_decision_enabled,
            cluster_ambiguous_min_similarity=settings.llm.cluster_ambiguous_min_similarity,
            cluster_decision_min_confidence=settings.llm.cluster_decision_min_confidence,
            cluster_decision_candidate_limit=settings.llm.cluster_decision_candidate_limit,
        )


def clamp_score_modifier(value: int, *, minimum: int = -10, maximum: int = 10) -> int:
    return max(minimum, min(maximum, int(value)))


class LLMAnalysis(BaseModel):
    summary: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    status_assessment: str = Field(min_length=1)
    confidence: int = Field(ge=0, le=100)
    impact_rationale: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    risk_flags: list[str] = Field(default_factory=list)
    score_modifier: int = Field(default=0)
    modifier_reason: str = Field(min_length=1)

    @field_validator("score_modifier")
    @classmethod
    def clamp_modifier(cls, value: int) -> int:
        return clamp_score_modifier(value)

    @field_validator("summary", "impact_rationale", "why_it_matters", "modifier_reason")
    @classmethod
    def normalize_strings(cls, value: str) -> str:
        return normalize_text(value)


class LLMClassification(BaseModel):
    item_type: str = Field(min_length=1)
    actionability: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    region: str = Field(min_length=1)
    asset_classes: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    duplicate_hint: str = Field(min_length=1)
    confidence: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def normalize_rationale(cls, value: str) -> str:
        return normalize_text(value)


class LLMEventSummary(BaseModel):
    summary: str = Field(min_length=1)
    status: str = Field(min_length=1)
    affected_assets: list[str] = Field(default_factory=list)
    digest_bullets: list[str] = Field(default_factory=list)
    why_it_matters: str = Field(min_length=1)
    alert_message: str = Field(min_length=1)
    caveats: list[str] = Field(default_factory=list)

    @field_validator("summary", "why_it_matters", "alert_message")
    @classmethod
    def normalize_summary_strings(cls, value: str) -> str:
        return normalize_text(value)


class LLMEventScore(BaseModel):
    impact_score: int = Field(ge=0, le=100)
    relevance_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    risk_flags: list[str] = Field(default_factory=list)
    score_modifier: int = Field(default=0)
    modifier_reason: str = Field(min_length=1)

    @field_validator("score_modifier")
    @classmethod
    def clamp_modifier(cls, value: int) -> int:
        return clamp_score_modifier(value)

    @field_validator("modifier_reason")
    @classmethod
    def normalize_modifier_reason(cls, value: str) -> str:
        return normalize_text(value)


class LLMClusterDecision(BaseModel):
    decision: str = Field(pattern="^(same_event|related_but_separate|different_event)$")
    confidence: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def normalize_rationale(cls, value: str) -> str:
        return normalize_text(value)


class LLMInvestigationResult(BaseModel):
    summary: str = Field(min_length=1)
    confidence: int = Field(ge=0, le=100)
    official_confirmation: str = Field(min_length=1)
    risk_flags: list[str] = Field(default_factory=list)
    suggested_score_modifier: int = Field(default=0)
    suggested_alert_level: str = Field(min_length=1)
    caveats: list[str] = Field(default_factory=list)

    @field_validator("summary", "official_confirmation", "suggested_alert_level")
    @classmethod
    def normalize_strings(cls, value: str) -> str:
        return normalize_text(value)

    @field_validator("suggested_score_modifier")
    @classmethod
    def clamp_modifier(cls, value: int) -> int:
        return clamp_score_modifier(value)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    schema["required"] = list(schema.get("properties", {}).keys())
    return schema


def llm_analysis_schema() -> dict[str, Any]:
    return strict_json_schema(LLMAnalysis)


def normalize_usage(usage: dict[str, Any]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in usage.items():
        if isinstance(value, bool):
            normalized[str(key)] = value
        elif isinstance(value, int | float):
            normalized[str(key)] = int(value)
        elif isinstance(value, str):
            try:
                normalized[str(key)] = int(value)
            except ValueError:
                normalized[str(key)] = value
        else:
            normalized[str(key)] = value
    return normalized


def event_input_snapshot(
    event: EventCluster,
    *,
    score_breakdown: dict[str, object],
    market_move_score: int,
) -> dict[str, object]:
    return {
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
        "score_breakdown": score_breakdown,
        "market_move_score": market_move_score,
    }


def build_event_analysis_prompt(
    event: EventCluster,
    *,
    score_breakdown: dict[str, object],
    market_move_score: int,
) -> str:
    snapshot = event_input_snapshot(
        event,
        score_breakdown=score_breakdown,
        market_move_score=market_move_score,
    )
    return "\n".join(
        [
            "Analyze this market event for a personal market watch bot.",
            "Return only JSON matching the requested schema.",
            "Do not recommend sending alerts directly; provide only policy input.",
            "",
            f"Headline: {normalize_text(event.canonical_headline)}",
            f"Summary: {normalize_text(event.summary) if event.summary else ''}",
            f"Status: {event.status}",
            f"Regions: {', '.join(event.regions or [])}",
            f"Asset classes: {', '.join(event.asset_classes or [])}",
            f"Affected entities: {', '.join(event.affected_entities or [])}",
            f"Affected tickers: {', '.join(event.affected_tickers or [])}",
            f"Source count: {event.source_count}",
            f"Top source score: {event.top_source_score}",
            f"Deterministic final score: {event.final_score}",
            f"Market move score: {market_move_score}",
            f"Score breakdown: {json.dumps(score_breakdown, sort_keys=True)}",
            f"Input snapshot: {json.dumps(snapshot, sort_keys=True, default=str)}",
        ]
    )


def build_news_classification_prompt(item: NormalizedNewsItem) -> str:
    language_guidance = (
        "Vietnamese-language guidance: preserve Vietnamese company/entity names, "
        "map common Vietnamese market terms to tickers only when explicit, and treat "
        "VN-Index/HOSE/HNX/UPCoM as market entities."
        if item.language.lower().startswith("vi")
        else "Use the source language as context for entity extraction."
    )
    return "\n".join(
        [
            "Classify this normalized market news item for a market watch bot.",
            "Return only JSON matching the requested schema.",
            "Focus on market type, actionability, actual region/assets, affected "
            "entities, and ambiguity.",
            language_guidance,
            "",
            f"News item id: {item.id}",
            f"Title: {normalize_text(item.title)}",
            f"Snippet: {normalize_text(item.snippet) if item.snippet else ''}",
            (
                "Full text: "
                f"{normalize_text(item.raw_content) if getattr(item, 'raw_content', None) else ''}"
            ),
            f"Source: {normalize_text(item.source_name)}",
            f"Source type: {item.source_type}",
            f"Source score: {item.source_score}",
            f"Current region: {item.region}",
            f"Current asset classes: {', '.join(item.asset_classes or [])}",
            f"Language: {item.language}",
        ]
    )


def build_cluster_decision_prompt(
    item: NormalizedNewsItem,
    cluster: EventCluster,
    *,
    similarity: float,
    item_entities: list[str],
    item_tickers: list[str],
) -> str:
    return "\n".join(
        [
            "Decide whether this news item belongs to this existing event cluster.",
            "Return only JSON matching the requested schema.",
            "Use same_event only when both inputs describe the same real-world market event.",
            "Use related_but_separate for same topic/theme but a different event or update.",
            "Use different_event for unrelated catalysts.",
            "",
            "News item:",
            f"News item id: {item.id}",
            f"Title: {normalize_text(item.title)}",
            f"Snippet: {normalize_text(item.snippet) if item.snippet else ''}",
            f"Source: {normalize_text(item.source_name)}",
            f"Source score: {item.source_score}",
            f"Region: {item.region}",
            f"Asset classes: {', '.join(item.asset_classes or [])}",
            f"Entities: {', '.join(item_entities)}",
            f"Tickers: {', '.join(item_tickers)}",
            "",
            "Existing event cluster:",
            f"Event cluster id: {cluster.id}",
            f"Headline: {normalize_text(cluster.canonical_headline)}",
            f"Summary: {normalize_text(cluster.summary) if cluster.summary else ''}",
            f"Status: {cluster.status}",
            f"Regions: {', '.join(cluster.regions or [])}",
            f"Asset classes: {', '.join(cluster.asset_classes or [])}",
            f"Affected entities: {', '.join(cluster.affected_entities or [])}",
            f"Affected tickers: {', '.join(cluster.affected_tickers or [])}",
            f"Source count: {cluster.source_count}",
            f"Top source score: {cluster.top_source_score}",
            f"Embedding similarity: {similarity:.4f}",
        ]
    )


def build_event_summary_prompt(event: EventCluster) -> str:
    return "\n".join(
        [
            "Summarize this market event cluster for alerts and digests.",
            "Return only JSON matching the requested schema.",
            "Avoid long summaries. Include 1-3 digest bullets and a concise alert message.",
            "",
            f"Event cluster id: {event.id}",
            f"Headline: {normalize_text(event.canonical_headline)}",
            f"Existing summary: {normalize_text(event.summary) if event.summary else ''}",
            f"Status: {event.status}",
            f"Regions: {', '.join(event.regions or [])}",
            f"Asset classes: {', '.join(event.asset_classes or [])}",
            f"Affected entities: {', '.join(event.affected_entities or [])}",
            f"Affected tickers: {', '.join(event.affected_tickers or [])}",
            f"Source count: {event.source_count}",
            f"Top source score: {event.top_source_score}",
            f"Final score: {event.final_score}",
        ]
    )


def build_event_score_prompt(
    event: EventCluster,
    *,
    score_breakdown: dict[str, object],
    market_move_score: int,
) -> str:
    return "\n".join(
        [
            "Estimate scoring inputs for this market event cluster.",
            "Return only JSON matching the requested schema.",
            "Do not replace deterministic scoring; provide bounded judgment inputs only.",
            "",
            f"Event cluster id: {event.id}",
            f"Headline: {normalize_text(event.canonical_headline)}",
            f"Status: {event.status}",
            f"Regions: {', '.join(event.regions or [])}",
            f"Asset classes: {', '.join(event.asset_classes or [])}",
            f"Affected entities: {', '.join(event.affected_entities or [])}",
            f"Affected tickers: {', '.join(event.affected_tickers or [])}",
            f"Source count: {event.source_count}",
            f"Top source score: {event.top_source_score}",
            f"Deterministic final score: {event.final_score}",
            f"Market move score: {market_move_score}",
            f"Score breakdown: {json.dumps(score_breakdown, sort_keys=True)}",
        ]
    )


def build_investigation_prompt(
    *,
    target_type: str,
    input_snapshot: dict[str, object],
    evidence: list[dict[str, object]],
) -> str:
    return "\n".join(
        [
            "Investigate this market-watch target using only the supplied evidence.",
            "Return only JSON matching the requested schema.",
            "Do not send alerts or mutate event fields; provide advisory policy input only.",
            "Treat search snippets as unverified unless the source is clearly official.",
            "",
            f"Target type: {target_type}",
            f"Input snapshot: {json.dumps(input_snapshot, sort_keys=True, default=str)}",
            f"Evidence: {json.dumps(evidence, sort_keys=True, default=str)}",
        ]
    )


def prompt_hash(prompt: str) -> str:
    return content_hash(prompt)


def event_needs_llm_analysis(
    event: EventCluster,
    *,
    config: LLMConfig,
    market_move_score: int,
) -> bool:
    if not config.enabled:
        return False
    if event.final_score >= config.high_score_threshold:
        return True
    if event.source_count == 1 and event.top_source_score >= config.single_source_score_threshold:
        return True
    if market_move_score >= config.market_move_score_threshold and event.final_score >= 55:
        return True
    relevance_score = int(event.relevance_score or 0)
    return bool(
        relevance_score >= config.relevance_score_threshold
        and event.source_count <= 1
        and event.final_score >= 55
    )


class OpenRouterChatProvider:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    async def complete_structured(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema_model: type[BaseModel],
        system_message: str,
    ) -> tuple[BaseModel, dict[str, object]]:
        if not self.config.api_key:
            raise ValueError(f"{self.config.api_key_env} is required for OpenRouter LLM analysis")
        json_schema = {
            "name": schema_name,
            "strict": True,
            "schema": strict_json_schema(schema_model),
        }
        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_message,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": json_schema,
            },
        }
        if self.config.service_tier is not None:
            payload["service_tier"] = self.config.service_tier
        url = f"{self.config.api_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        from common.external_providers import (
            PROVIDER_RETRY_POLICIES,
            request_with_retry,
        )

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            try:
                response = await request_with_retry(
                    provider="openrouter_chat",
                    method="POST",
                    url=url,
                    retry_policy=PROVIDER_RETRY_POLICIES["openrouter_chat"],
                    client=client,
                    headers=headers,
                    json=payload,
                )
            except httpx.HTTPStatusError as exc:
                response = exc.response
                if response.status_code == 400:
                    fallback_schema = {
                        "name": schema_name,
                        "schema": strict_json_schema(schema_model),
                    }
                    payload["response_format"] = {
                        "type": "json_schema",
                        "json_schema": fallback_schema,
                    }
                    response = await request_with_retry(
                        provider="openrouter_chat",
                        method="POST",
                        url=url,
                        retry_policy=PROVIDER_RETRY_POLICIES["openrouter_chat"],
                        client=client,
                        headers=headers,
                        json=payload,
                    )
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as retry_exc:
                        body = response.text[:1000]
                        raise ValueError(
                            "OpenRouter chat completion failed with "
                            f"HTTP {response.status_code}: {body}"
                        ) from retry_exc
                else:
                    body = response.text[:1000]
                    raise ValueError(
                        "OpenRouter chat completion failed with "
                        f"HTTP {response.status_code}: {body}"
                    ) from exc
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        analysis = schema_model.model_validate_json(content)
        usage = data.get("usage") or {}
        normalized_usage = normalize_usage(usage)
        if "service_tier" in data:
            normalized_usage["service_tier"] = data["service_tier"]
        return analysis, normalized_usage

    async def analyze_event(self, prompt: str) -> tuple[LLMAnalysis, dict[str, object]]:
        analysis, usage = await self.complete_structured(
            prompt=prompt,
            schema_name="market_event_analysis",
            schema_model=LLMAnalysis,
            system_message=(
                "You are a market event analyst. Return concise, factual structured "
                "analysis. Do not invent facts not present in the input."
            ),
        )
        return LLMAnalysis.model_validate(analysis), usage

    async def classify_news_item(
        self, prompt: str
    ) -> tuple[LLMClassification, dict[str, object]]:
        result, usage = await self.complete_structured(
            prompt=prompt,
            schema_name="market_news_classification",
            schema_model=LLMClassification,
            system_message=(
                "You classify market news items. Return concise structured labels and "
                "do not invent unavailable tickers or facts."
            ),
        )
        return LLMClassification.model_validate(result), usage

    async def summarize_event(self, prompt: str) -> tuple[LLMEventSummary, dict[str, object]]:
        result, usage = await self.complete_structured(
            prompt=prompt,
            schema_name="market_event_summary",
            schema_model=LLMEventSummary,
            system_message=(
                "You summarize market event clusters for alerts and digests. Keep output "
                "concise, factual, and caveated."
            ),
        )
        return LLMEventSummary.model_validate(result), usage

    async def score_event(self, prompt: str) -> tuple[LLMEventScore, dict[str, object]]:
        result, usage = await self.complete_structured(
            prompt=prompt,
            schema_name="market_event_score",
            schema_model=LLMEventScore,
            system_message=(
                "You provide bounded scoring judgment for a deterministic market watch "
                "policy engine. Do not recommend delivery directly."
            ),
        )
        return LLMEventScore.model_validate(result), usage

    async def decide_cluster_match(
        self, prompt: str
    ) -> tuple[LLMClusterDecision, dict[str, object]]:
        result, usage = await self.complete_structured(
            prompt=prompt,
            schema_name="market_cluster_decision",
            schema_model=LLMClusterDecision,
            system_message=(
                "You decide whether a market news item belongs to an existing event "
                "cluster. Be conservative: only choose same_event for the same specific "
                "real-world event, not just a related theme."
            ),
        )
        return LLMClusterDecision.model_validate(result), usage

    async def investigate_event(
        self, prompt: str
    ) -> tuple[LLMInvestigationResult, dict[str, object]]:
        result, usage = await self.complete_structured(
            prompt=prompt,
            schema_name="market_agent_investigation",
            schema_model=LLMInvestigationResult,
            system_message=(
                "You are a constrained market investigator. Use only supplied evidence. "
                "Return concise, caveated recommendations for a deterministic policy engine."
            ),
        )
        return LLMInvestigationResult.model_validate(result), usage


def llm_provider(config: LLMConfig) -> OpenRouterChatProvider:
    return OpenRouterChatProvider(config)
