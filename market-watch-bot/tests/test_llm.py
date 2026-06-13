from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bot_worker.db.models import EventCluster, NormalizedNewsItem
from common.llm import (
    PROMPT_VERSION,
    LLMAnalysis,
    LLMClassification,
    LLMClusterDecision,
    LLMConfig,
    LLMEventScore,
    LLMEventSummary,
    OpenRouterChatProvider,
    build_cluster_decision_prompt,
    build_event_analysis_prompt,
    build_event_score_prompt,
    build_event_summary_prompt,
    build_news_classification_prompt,
    clamp_score_modifier,
    event_needs_llm_analysis,
    normalize_usage,
    parse_structured_response_content,
    strict_json_schema,
)


def test_bot_worker_llm_reexports_shared_config_for_compatibility() -> None:
    from bot_worker.llm import LLMConfig as WorkerLLMConfig

    assert WorkerLLMConfig is LLMConfig


def test_event_prompt_version_is_bumped_for_alert_message_schema() -> None:
    config = LLMConfig()

    assert PROMPT_VERSION == "event-v2"
    assert config.prompt_version == "event-v2"


def test_llm_trigger_policy_selects_high_value_events() -> None:
    high_score = EventCluster(
        canonical_headline="Fed announces surprise emergency liquidity facility",
        final_score=82,
        source_count=2,
        top_source_score=90,
    )
    single_source_official = EventCluster(
        canonical_headline="SEC issues new crypto exchange rule",
        final_score=61,
        source_count=1,
        top_source_score=95,
    )
    ordinary = EventCluster(
        canonical_headline="Minor market commentary",
        final_score=42,
        source_count=3,
        top_source_score=65,
    )
    config = LLMConfig(enabled=True)

    assert event_needs_llm_analysis(high_score, config=config, market_move_score=0)
    assert event_needs_llm_analysis(single_source_official, config=config, market_move_score=0)
    assert not event_needs_llm_analysis(ordinary, config=config, market_move_score=0)

    # market_move_score is None before the market-moves stage runs; it must not raise.
    assert event_needs_llm_analysis(high_score, config=config, market_move_score=None)
    assert not event_needs_llm_analysis(ordinary, config=config, market_move_score=None)


def test_llm_trigger_policy_uses_configured_analysis_min_score() -> None:
    market_move = EventCluster(
        canonical_headline="Oil futures move after shipping report",
        final_score=58,
        source_count=2,
        top_source_score=75,
    )
    relevance = EventCluster(
        canonical_headline="Watchlist company comments on demand",
        final_score=58,
        source_count=1,
        top_source_score=75,
        relevance_score=82,
    )
    config = LLMConfig(enabled=True, analysis_min_score_threshold=60)

    assert not event_needs_llm_analysis(market_move, config=config, market_move_score=75)
    assert not event_needs_llm_analysis(relevance, config=config, market_move_score=0)


def test_llm_prompt_uses_compact_event_context_and_excludes_secrets() -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Vietnam bank stocks rally after credit growth report",
        summary="Bank shares rose after an official update.",
        regions=["vietnam"],
        asset_classes=["equity"],
        affected_entities=["VCB", "TCB"],
        affected_tickers=["VCB"],
        source_count=2,
        top_source_score=85,
        final_score=78,
        status="reported",
        created_at=datetime(2026, 5, 27, 8, tzinfo=UTC),
    )

    prompt = build_event_analysis_prompt(
        event,
        score_breakdown={"final_score": 78},
        market_move_score=72,
    )

    assert "Vietnam bank stocks rally" in prompt
    assert "Market move score: 72" in prompt
    assert "alert_message" in prompt
    assert "OPENROUTER_API_KEY" not in prompt
    assert "secret" not in prompt.casefold()


def test_news_classification_prompt_is_item_scoped() -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Vietnam bank stocks rise after credit growth update",
        snippet="Bank shares gained after official lending data.",
        source_name="Vietstock",
        source_type="rss",
        source_score=75,
        region="vietnam",
        asset_classes=["equity"],
        language="en",
        url="https://example.test/news",
        title_hash="title",
        normalized_text_hash="text",
    )

    prompt = build_news_classification_prompt(item)

    assert "Classify this normalized market news item" in prompt
    assert "Vietnam bank stocks rise" in prompt
    assert "Event cluster" not in prompt


def test_news_classification_prompt_caps_full_text() -> None:
    raw_content = "A" * 8_500 + " SHouldNotAppear"
    item = NormalizedNewsItem(
        id="news_1",
        title="Vietnam bank stocks rise after credit growth update",
        snippet="Bank shares gained after official lending data.",
        raw_content=raw_content,
        source_name="Vietstock",
        source_type="rss",
        source_score=75,
        region="vietnam",
        asset_classes=["equity"],
        language="en",
        url="https://example.test/news",
        title_hash="title",
        normalized_text_hash="text",
    )

    prompt = build_news_classification_prompt(item)

    assert "Vietnam bank stocks rise after credit growth update" in prompt
    assert "Bank shares gained after official lending data." in prompt
    assert "A" * 8_000 in prompt
    assert "SHouldNotAppear" not in prompt


def test_event_summary_and_score_prompts_are_distinct() -> None:
    event = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after tanker incident near Hormuz",
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["Hormuz", "Brent"],
        source_count=2,
        top_source_score=85,
        final_score=82,
        status="reported",
    )

    summary_prompt = build_event_summary_prompt(event)
    score_prompt = build_event_score_prompt(
        event,
        score_breakdown={"final_score": 82},
        market_move_score=75,
    )

    assert "Summarize this market event cluster" in summary_prompt
    assert "1-3 digest bullets" in summary_prompt
    assert "Estimate scoring inputs" in score_prompt
    assert "Market move score: 75" in score_prompt


def test_cluster_decision_prompt_compares_news_item_to_candidate_cluster() -> None:
    item = NormalizedNewsItem(
        id="news_1",
        title="Brent rises as Hormuz shipping risks increase",
        snippet="Oil benchmarks gained after reports of shipping disruption.",
        source_name="MarketWatch",
        source_type="rss",
        source_score=75,
        region="global",
        asset_classes=["commodity"],
        language="en",
        url="https://example.test/oil",
        title_hash="title",
        normalized_text_hash="text",
    )
    cluster = EventCluster(
        id="evt_1",
        canonical_headline="Oil jumps after tanker incident near Hormuz",
        regions=["global"],
        asset_classes=["commodity"],
        affected_entities=["Hormuz", "Brent"],
        affected_tickers=["BZ"],
        source_count=2,
        top_source_score=85,
        status="reported",
    )

    prompt = build_cluster_decision_prompt(
        item,
        cluster,
        similarity=0.87,
        item_entities=["Hormuz", "Brent"],
        item_tickers=["BZ"],
    )

    assert "Decide whether this news item belongs to this existing event cluster" in prompt
    assert "Brent rises as Hormuz" in prompt
    assert "Oil jumps after tanker incident" in prompt
    assert "Embedding similarity: 0.8700" in prompt
    assert "OPENROUTER_API_KEY" not in prompt


def test_llm_analysis_validation_and_modifier_clamping() -> None:
    analysis = LLMAnalysis.model_validate(
        {
            "summary": "A material policy update may affect banks.",
            "event_type": "policy",
            "status_assessment": "reported",
            "confidence": 84,
            "impact_rationale": "Directly affects credit-sensitive equities.",
            "why_it_matters": "Bank earnings expectations may shift.",
            "alert_message": "Bank shares may move after a material policy update.",
            "risk_flags": ["single jurisdiction"],
            "score_modifier": 50,
            "modifier_reason": "Official source and market reaction.",
        }
    )

    assert analysis.score_modifier == 50
    assert analysis.alert_message == "Bank shares may move after a material policy update."
    assert clamp_score_modifier(-50, minimum=-5, maximum=7) == -5

    with pytest.raises(ValidationError):
        LLMAnalysis.model_validate({"summary": "missing required fields"})


def test_task_specific_llm_schemas_validate_expected_outputs() -> None:
    classification = LLMClassification.model_validate(
        {
            "item_type": "market_commentary",
            "actionability": "low",
            "event_type": "commentary",
            "region": "us",
            "asset_classes": ["equity", "macro"],
            "entities": ["S&P 500"],
            "tickers": ["SPY"],
            "confidence": 82,
            "rationale": "Opinion about equity supply, not a direct catalyst.",
        }
    )
    summary = LLMEventSummary.model_validate(
        {
            "summary": "Oil rose after a reported shipping incident.",
            "status": "reported",
            "affected_assets": ["Brent", "WTI"],
            "digest_bullets": ["Shipping risk lifted crude prices."],
            "why_it_matters": "Energy supply risk can affect inflation expectations.",
            "alert_message": "Oil jumps after reported tanker incident near Hormuz.",
            "caveats": ["Not official yet"],
        }
    )
    score = LLMEventScore.model_validate(
        {
            "impact_score": 86,
            "relevance_score": 75,
            "confidence_score": 80,
            "risk_flags": ["reported, not official"],
            "score_modifier": 99,
            "modifier_reason": "Market reaction confirms relevance.",
        }
    )
    cluster_decision = LLMClusterDecision.model_validate(
        {
            "decision": "same_event",
            "confidence": 84,
            "rationale": "Both items describe the same Hormuz shipping disruption.",
        }
    )

    assert classification.actionability == "low"
    assert summary.status == "reported"
    assert score.score_modifier == 99
    assert cluster_decision.decision == "same_event"


def test_tolerant_structured_response_parser_accepts_fenced_json() -> None:
    content = """Here is the JSON:
```json
{
  "summary": "Markets reacted to the policy update.",
  "event_type": "economic_policy",
  "status_assessment": "reported",
  "confidence": 82,
  "impact_rationale": "The report affects rate expectations.",
  "why_it_matters": "Rate expectations can move equities and FX.",
  "alert_message": "Markets react to reported policy update.",
  "risk_flags": ["reported"],
  "score_modifier": 2,
  "modifier_reason": "The deterministic score slightly understates impact."
}
```
"""

    analysis = parse_structured_response_content(content, LLMAnalysis)

    assert analysis.alert_message == "Markets react to reported policy update."


def test_tolerant_structured_response_parser_rejects_invalid_prose() -> None:
    with pytest.raises(ValueError, match="Failed to parse structured LLM response"):
        parse_structured_response_content("I cannot produce JSON for this.", LLMAnalysis)


def test_llm_schema_marks_all_properties_required_for_strict_openrouter_mode() -> None:
    schema = strict_json_schema(LLMAnalysis)

    assert set(schema["required"]) == set(schema["properties"])
    assert "risk_flags" in schema["required"]
    assert schema["additionalProperties"] is False


def test_normalize_usage_preserves_nested_openrouter_usage_fields() -> None:
    usage = normalize_usage(
        {
            "prompt_tokens": 120,
            "completion_tokens": 80.0,
            "total_tokens": "200",
            "cost_details": {"upstream_inference_cost": 0.001},
        }
    )

    assert usage["prompt_tokens"] == 120
    assert usage["completion_tokens"] == 80
    assert usage["total_tokens"] == 200
    assert usage["cost_details"] == {"upstream_inference_cost": 0.001}


@pytest.mark.asyncio
async def test_openrouter_structured_completion_omits_service_tier_by_default(
    monkeypatch,
) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": LLMAnalysis(
                                summary="Checked.",
                                event_type="policy",
                                status_assessment="reported",
                                confidence=70,
                                impact_rationale="Relevant.",
                                why_it_matters="Markets may react.",
                                alert_message="Markets may react to the policy update.",
                                risk_flags=[],
                                score_modifier=0,
                                modifier_reason="No change.",
                            ).model_dump_json()
                        }
                    }
                ],
                "usage": {"total_tokens": 10},
            }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, headers, json):
            requests.append(deepcopy(json))
            return FakeResponse()

    monkeypatch.setattr("common.llm.httpx.AsyncClient", FakeClient)
    provider = OpenRouterChatProvider(LLMConfig(enabled=True, api_key="key"))

    _result, usage = await provider.complete_structured(
        prompt="prompt",
        schema_name="schema",
        schema_model=LLMAnalysis,
        system_message="system",
    )

    assert "service_tier" not in requests[0]
    assert usage["total_tokens"] == 10


@pytest.mark.asyncio
async def test_openrouter_structured_completion_retries_without_strict_schema_on_400(
    monkeypatch,
) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object] | None = None) -> None:
            self.status_code = status_code
            self._payload = payload or {}
            self.text = "strict schema unsupported"
            self.request = None

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                import httpx

                raise httpx.HTTPStatusError(
                    "bad request",
                    request=self.request,
                    response=self,
                )

        def json(self) -> dict[str, object]:
            return self._payload

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, headers, json):
            requests.append(deepcopy(json))
            if len(requests) == 1:
                return FakeResponse(400)
            return FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": LLMAnalysis(
                                    summary="Checked.",
                                    event_type="policy",
                                    status_assessment="reported",
                                    confidence=70,
                                    impact_rationale="Relevant.",
                                    why_it_matters="Markets may react.",
                                    alert_message="Markets may react to the policy update.",
                                    risk_flags=[],
                                    score_modifier=0,
                                    modifier_reason="No change.",
                                ).model_dump_json()
                            }
                        }
                    ],
                    "usage": {"total_tokens": 10},
                    "service_tier": "flex",
                },
            )

    monkeypatch.setattr("common.llm.httpx.AsyncClient", FakeClient)
    provider = OpenRouterChatProvider(
        LLMConfig(enabled=True, api_key="key", service_tier="flex")
    )

    result, usage = await provider.complete_structured(
        prompt="prompt",
        schema_name="schema",
        schema_model=LLMAnalysis,
        system_message="system",
    )

    assert isinstance(result, LLMAnalysis)
    assert usage["total_tokens"] == 10
    assert usage["service_tier"] == "flex"
    assert requests[0]["service_tier"] == "flex"
    assert requests[1]["service_tier"] == "flex"
    assert requests[0]["response_format"]["json_schema"]["strict"] is True
    assert "strict" not in requests[1]["response_format"]["json_schema"]
