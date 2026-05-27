from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bot_worker.db.models import EventCluster, NormalizedNewsItem
from bot_worker.llm import (
    LLMAnalysis,
    LLMClassification,
    LLMConfig,
    LLMEventScore,
    LLMEventSummary,
    build_event_analysis_prompt,
    build_event_score_prompt,
    build_event_summary_prompt,
    build_news_classification_prompt,
    clamp_score_modifier,
    event_needs_llm_analysis,
    normalize_usage,
    strict_json_schema,
)


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


def test_llm_analysis_validation_and_modifier_clamping() -> None:
    analysis = LLMAnalysis.model_validate(
        {
            "summary": "A material policy update may affect banks.",
            "event_type": "policy",
            "status_assessment": "reported",
            "confidence": 84,
            "impact_rationale": "Directly affects credit-sensitive equities.",
            "why_it_matters": "Bank earnings expectations may shift.",
            "risk_flags": ["single jurisdiction"],
            "score_modifier": 50,
            "modifier_reason": "Official source and market reaction.",
        }
    )

    assert analysis.score_modifier == 10
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
            "duplicate_hint": "unknown",
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

    assert classification.actionability == "low"
    assert summary.status == "reported"
    assert score.score_modifier == 10


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
