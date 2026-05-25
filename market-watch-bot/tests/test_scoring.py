from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event


def test_score_event_combines_source_relevance_novelty_confidence_and_penalties() -> None:
    score = score_event(
        ScoreInput(
            top_source_score=90,
            source_count=2,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
            status="reported",
        )
    )

    assert score.source_score == 90
    assert score.relevance_score == 95
    assert score.confidence_score == 75
    assert score.final_score >= 80


def test_decide_alert_uses_thresholds_and_suppression() -> None:
    immediate = decide_alert(82, AlertThresholds())
    suppressed = decide_alert(82, AlertThresholds(), suppression_reason="cooldown")

    assert immediate.decision == "immediate_alert"
    assert suppressed.decision == "suppressed"
    assert suppressed.reason == "cooldown"
