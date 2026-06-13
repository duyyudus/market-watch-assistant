from bot_worker.scoring import AlertThresholds, ScoreInput, decide_alert, score_event


def test_score_event_archives_low_source_unknown_event() -> None:
    score = score_event(
        ScoreInput(
            top_source_score=10,
            source_count=1,
            watchlist_tier=None,
            is_duplicate=False,
            is_stale=False,
        )
    )

    decision = decide_alert(score.final_score, AlertThresholds())

    assert score.relevance_score == 35
    assert score.final_score < AlertThresholds().digest
    assert decision.decision == "archive_only"


def test_score_event_keeps_high_source_unknown_event_in_digest() -> None:
    score = score_event(
        ScoreInput(
            top_source_score=80,
            source_count=1,
            watchlist_tier=None,
            is_duplicate=False,
            is_stale=False,
        )
    )

    decision = decide_alert(score.final_score, AlertThresholds())

    assert score.relevance_score == 35
    assert score.final_score >= AlertThresholds().digest
    assert score.final_score < AlertThresholds().watchlist
    assert decision.decision == "daily_digest"


def test_score_event_treats_unknown_watchlist_relevance_as_d() -> None:
    unknown = score_event(
        ScoreInput(
            top_source_score=80,
            source_count=2,
            watchlist_tier=None,
            is_duplicate=False,
            is_stale=False,
        )
    )
    d_tier = score_event(
        ScoreInput(
            top_source_score=80,
            source_count=2,
            watchlist_tier="D",
            is_duplicate=False,
            is_stale=False,
        )
    )
    s_tier = score_event(
        ScoreInput(
            top_source_score=80,
            source_count=2,
            watchlist_tier="S",
            is_duplicate=False,
            is_stale=False,
        )
    )

    assert unknown.relevance_score == 35
    assert d_tier.relevance_score == 35
    assert s_tier.relevance_score == 100
    assert unknown.final_score == d_tier.final_score
    assert d_tier.final_score < s_tier.final_score


def test_score_event_gives_confirmation_material_influence() -> None:
    single_source = score_event(
        ScoreInput(
            top_source_score=90,
            source_count=1,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
        )
    )
    confirmed_multi_source = score_event(
        ScoreInput(
            top_source_score=90,
            source_count=3,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=2,
            status="confirmed",
        )
    )

    assert confirmed_multi_source.confidence_score > single_source.confidence_score
    assert confirmed_multi_source.final_score - single_source.final_score >= 10


def test_score_event_allows_confirmed_high_quality_watched_event_to_alert_immediately() -> None:
    score = score_event(
        ScoreInput(
            top_source_score=95,
            source_count=2,
            watchlist_tier="S",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=2,
            status="official",
            market_move_score=60,
        )
    )

    decision = decide_alert(score.final_score, AlertThresholds())

    assert score.final_score >= AlertThresholds().immediate
    assert decision.decision == "immediate_alert"


def test_decide_alert_uses_thresholds_and_suppression() -> None:
    immediate = decide_alert(82, AlertThresholds())

    assert immediate.decision == "immediate_alert"


def test_score_event_uses_normalized_weights_without_market_move_override() -> None:
    score = score_event(
        ScoreInput(
            top_source_score=65,
            source_count=1,
            watchlist_tier=None,
            is_duplicate=False,
            is_stale=False,
            market_move_score=95,
        )
    )

    decision = decide_alert(score.final_score, AlertThresholds())

    assert score.market_move_score == 95
    assert score.final_score < AlertThresholds().immediate
    assert decision.decision != "immediate_alert"


def test_score_event_renormalizes_when_market_move_is_missing() -> None:
    missing_market = score_event(
        ScoreInput(
            top_source_score=80,
            source_count=2,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
            market_move_score=None,
        )
    )
    flat_market = score_event(
        ScoreInput(
            top_source_score=80,
            source_count=2,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
            market_move_score=0,
        )
    )

    assert missing_market.market_move_score == 0
    assert missing_market.final_score > flat_market.final_score


def test_score_event_applies_multiplicative_stale_and_duplicate_penalties() -> None:
    fresh = score_event(
        ScoreInput(
            top_source_score=90,
            source_count=2,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=2,
        )
    )
    stale_duplicate = score_event(
        ScoreInput(
            top_source_score=90,
            source_count=2,
            watchlist_tier="A",
            is_duplicate=True,
            is_stale=True,
            unique_high_quality_source_count=2,
        )
    )

    assert stale_duplicate.final_score < fresh.final_score
    assert stale_duplicate.final_score >= 0
    assert stale_duplicate.duplicate_penalty > 0
    assert stale_duplicate.stale_penalty > 0


def test_score_event_has_no_large_source_quality_cliff_at_75() -> None:
    source_74 = score_event(
        ScoreInput(
            top_source_score=74,
            source_count=1,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
        )
    )
    source_75 = score_event(
        ScoreInput(
            top_source_score=75,
            source_count=1,
            watchlist_tier="A",
            is_duplicate=False,
            is_stale=False,
        )
    )

    assert source_75.final_score - source_74.final_score <= 2


def test_score_event_smooths_noise_penalty_around_source_quality_50() -> None:
    source_49 = score_event(
        ScoreInput(
            top_source_score=49,
            source_count=2,
            watchlist_tier="S",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=2,
            status="confirmed",
        )
    )
    source_50 = score_event(
        ScoreInput(
            top_source_score=50,
            source_count=2,
            watchlist_tier="S",
            is_duplicate=False,
            is_stale=False,
            unique_high_quality_source_count=2,
            status="confirmed",
        )
    )

    assert source_49.noise_penalty > 0
    assert source_50.noise_penalty > 0
    assert source_50.final_score - source_49.final_score <= 3
