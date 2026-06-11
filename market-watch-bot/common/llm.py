from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from common.db.models import EventCluster, NormalizedNewsItem
from common.normalize import content_hash, normalize_text

if TYPE_CHECKING:
    from common.config import Settings


PROMPT_VERSION = "event-v2"
CLASSIFY_PROMPT_VERSION = "classify-v1"
SCORE_PROMPT_VERSION = "score-v1"
SUMMARY_PROMPT_VERSION = "summarize-v1"
CLUSTER_DECISION_PROMPT_VERSION = "cluster-decision-v1"
INVESTIGATION_PROMPT_VERSION = "investigation-v1"
MAX_CLASSIFICATION_RAW_CONTENT_CHARS = 8_000

# ── Prompt vocabulary constants ──────────────────────────────────────────────

CLASSIFY_ITEM_TYPES: tuple[str, ...] = (
    "news", "opinion", "analysis", "data_release", "press_release", "regulatory",
)

CLASSIFY_ACTIONABILITY_LEVELS: tuple[str, ...] = (
    "actionable", "low", "none",
)

CLASSIFY_EVENT_TYPE_EXAMPLES: tuple[str, ...] = (
    "earnings", "ipo", "merger", "economic_policy", "geopolitical",
    "regulatory", "market_trend", "corporate_action", "macro_data",
)

CLASSIFY_REGION_EXAMPLES: tuple[str, ...] = (
    "united_states", "vietnam", "global", "china", "europe",
)

ASSET_CLASS_VOCABULARY: tuple[str, ...] = (
    "equity", "crypto", "commodity", "fixed_income", "forex", "macro",
)

RISK_FLAG_EXAMPLES: tuple[str, ...] = (
    "low_source_diversity", "regulatory_risk", "speculative_sentiment",
)

CONFIDENCE_SCALE_GUIDANCE = (
    "Confidence scale: 100 = confirmed by multiple official/primary sources; "
    "80-99 = high certainty from credible reporting; "
    "60-79 = probable but limited sourcing or unverified details; "
    "40-59 = speculative or single-source with ambiguous facts; "
    "below 40 = rumor or unsubstantiated."
)

CLASSIFY_CONFIDENCE_SCALE_GUIDANCE = (
    "Confidence measures how certain you are about YOUR CLASSIFICATION above "
    "(item_type, event_type, region, entities, tickers), NOT the reliability "
    "of the underlying news source or whether the reported event is true. "
    "Do NOT lower confidence because of missing details in the news, private status "
    "of companies, or lack of direct trading signals. If the correct classification labels "
    "are clear (e.g., classifying a macro article as macro/none/economic_policy, or a private "
    "company IPO as ipo/equity/none with no ticker), confidence should be 90-100. "
    "Use 90-100 as the default when classification is straightforward. Only use 80 or "
    "below if you are genuinely uncertain or guessing the labels due to extremely vague "
    "or contradictory inputs."
)

SCORE_MODIFIER_GUIDANCE = (
    "Score modifier guidance: use 0 for routine events that match their "
    "deterministic score; use +1 to +10 only when the event has clear, "
    "quantifiable market impact beyond what the deterministic score captures; "
    "use -1 to -10 only for speculative, stale, or over-scored events. "
    "Prefer small adjustments (-3 to +3) unless the gap is obvious."
)


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
    max_tokens: int = 1200
    timeout_seconds: int = 45
    max_concurrency: int = 3
    high_score_threshold: int = 80
    single_source_score_threshold: int = 90
    market_move_score_threshold: int = 70
    relevance_score_threshold: int = 80
    analysis_min_score_threshold: int = 55
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
        alert_settings = getattr(settings, "alerts", None)
        analysis_min_score_threshold = int(
            getattr(alert_settings, "watchlist_threshold", 55)
        )
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
            analysis_min_score_threshold=analysis_min_score_threshold,
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
    alert_message: str = Field(min_length=1)
    risk_flags: list[str] = Field(default_factory=list)
    score_modifier: int = Field(default=0)
    modifier_reason: str = Field(min_length=1)

    @field_validator(
        "summary",
        "impact_rationale",
        "why_it_matters",
        "alert_message",
        "modifier_reason",
    )
    @classmethod
    def normalize_strings(cls, value: str) -> str:
        return normalize_text(value)


class LLMClassification(BaseModel):
    item_type: str = Field(
        min_length=1,
        description="One of: news, opinion, analysis, data_release, press_release, regulatory",
    )
    actionability: str = Field(
        min_length=1,
        description="One of: actionable, low, none",
    )
    event_type: str = Field(
        min_length=1,
        description="Short snake_case label, e.g. earnings, ipo, merger, economic_policy, "
        "geopolitical, regulatory, market_trend",
    )
    region: str = Field(min_length=1)
    asset_classes: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
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


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    schema["required"] = list(schema.get("properties", {}).keys())
    return schema


def llm_analysis_schema() -> dict[str, Any]:
    return strict_json_schema(LLMAnalysis)


def capped_prompt_text(value: str | None, *, max_chars: int) -> str:
    if not value:
        return ""
    return normalize_text(value)[:max_chars]


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _first_balanced_json_object(content: str) -> str | None:
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(content[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return None


def parse_structured_response_content[SchemaModel: BaseModel](
    content: str,
    schema_model: type[SchemaModel],
) -> SchemaModel:
    attempts = [content, _strip_json_fence(content)]
    extracted = _first_balanced_json_object(content)
    if extracted is not None:
        attempts.append(extracted)

    first_error: ValidationError | ValueError | None = None
    for candidate in attempts:
        try:
            return schema_model.model_validate_json(candidate)
        except (ValidationError, ValueError) as exc:
            if first_error is None:
                first_error = exc

    preview = normalize_text(content)[:500]
    raise ValueError(
        f"Failed to parse structured LLM response for {schema_model.__name__}: {preview}"
    ) from first_error


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
            "alert_message: one concise sentence suitable for an immediate alert title.",
            "",
            CONFIDENCE_SCALE_GUIDANCE,
            "",
            SCORE_MODIFIER_GUIDANCE,
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
    full_text = capped_prompt_text(
        getattr(item, "raw_content", None),
        max_chars=MAX_CLASSIFICATION_RAW_CONTENT_CHARS,
    )
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
            "Field definitions:",
            f"- item_type: one of {', '.join(repr(v) for v in CLASSIFY_ITEM_TYPES)}. "
            "Use exactly one value.",
            "- actionability: one of "
            f"{', '.join(repr(v) for v in CLASSIFY_ACTIONABILITY_LEVELS)}. "
            "'actionable' = clear near-term trading signal, "
            "'low' = indirect or sentiment-only impact, "
            "'none' = no trading signal.",
            "- event_type: short snake_case label such as "
            f"{', '.join(repr(v) for v in CLASSIFY_EVENT_TYPE_EXAMPLES)}. "
            "Use a single concise label.",
            "- region: lowercase region code such as "
            f"{', '.join(repr(v) for v in CLASSIFY_REGION_EXAMPLES)}. "
            "Use the region of the event, not the publication source.",
            f"- asset_classes: use only values from this set: "
            f"{', '.join(repr(v) for v in ASSET_CLASS_VOCABULARY)}. "
            "Do not invent labels like 'technology' or 'ai'.",
            "- entities: company and organization names only. Do not include "
            "people, product names, news agencies, or generic terms.",
            "- tickers: only include tickers for companies that are the PRIMARY "
            "SUBJECT of this news (e.g. the company making an announcement, "
            "reporting earnings, or being acquired). Do not include tickers of "
            "investors, partners, supply-chain peers, or companies mentioned "
            "for context or comparison. If the primary subject is not publicly "
            "listed, return an empty list.",
            "",
            CLASSIFY_CONFIDENCE_SCALE_GUIDANCE,
            "",
            f"News item id: {item.id}",
            f"Title: {normalize_text(item.title)}",
            f"Snippet: {normalize_text(item.snippet) if item.snippet else ''}",
            f"Full text: {full_text}",
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
            "affected_assets: list specific ticker symbols (e.g. AAPL, 9988.HK) that "
            "are directly affected. Do not list broad asset class names like "
            "'vietnam_equity'. If no specific tickers apply, return an empty list.",
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
            CONFIDENCE_SCALE_GUIDANCE,
            "",
            SCORE_MODIFIER_GUIDANCE,
            "",
            "risk_flags: use short snake_case labels (e.g. "
            f"{', '.join(RISK_FLAG_EXAMPLES)}). Do not write full sentences.",
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
    if (
        market_move_score >= config.market_move_score_threshold
        and event.final_score >= config.analysis_min_score_threshold
    ):
        return True
    relevance_score = int(event.relevance_score or 0)
    return bool(
        relevance_score >= config.relevance_score_threshold
        and event.source_count <= 1
        and event.final_score >= config.analysis_min_score_threshold
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
        analysis = parse_structured_response_content(content, schema_model)
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
                "You are a market event analyst. Always respond in English regardless "
                "of the input language. Return concise, factual structured analysis. "
                "Do not invent facts not present in the input."
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
                "You classify market news items. Always respond in English regardless "
                "of the input language. Return concise structured labels and "
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
                "You summarize market event clusters for alerts and digests. Always "
                "respond in English regardless of the input language. Keep output "
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
                "policy engine. Always respond in English regardless of the input "
                "language. Do not recommend delivery directly."
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
                "cluster. Always respond in English regardless of the input language. "
                "Be conservative: only choose same_event for the same specific "
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
                "You are a constrained market investigator. Always respond in English "
                "regardless of the input language. Use only supplied evidence. "
                "Return concise, caveated recommendations for a deterministic policy "
                "engine."
            ),
        )
        return LLMInvestigationResult.model_validate(result), usage


def llm_provider(config: LLMConfig) -> OpenRouterChatProvider:
    return OpenRouterChatProvider(config)
