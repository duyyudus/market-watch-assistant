from datetime import UTC, datetime

from bot_worker.normalize import (
    canonicalize_url,
    content_hash,
    normalize_datetime,
    normalize_text,
    title_hash,
)


def test_canonicalize_url_removes_tracking_and_normalizes_host() -> None:
    url = "HTTPS://Example.com/News/Item?utm_source=x&b=2&fbclid=abc&a=1#section"

    assert canonicalize_url(url) == "https://example.com/News/Item?a=1&b=2"


def test_text_and_title_hash_are_stable_for_whitespace_and_case() -> None:
    assert normalize_text("  Fed&nbsp; cuts\n rates  ") == "Fed cuts rates"
    assert title_hash("Fed cuts rates") == title_hash("  fed   cuts RATES ")
    assert content_hash("Fed cuts rates") == content_hash("Fed   cuts rates")


def test_normalize_datetime_handles_rss_struct_and_iso_string() -> None:
    assert normalize_datetime("2026-05-25T03:00:00+00:00") == datetime(
        2026, 5, 25, 3, 0, tzinfo=UTC
    )
    assert normalize_datetime((2026, 5, 25, 10, 0, 0, 0, 145, 0)) == datetime(
        2026, 5, 25, 10, 0, tzinfo=UTC
    )


def test_canonicalize_url_supports_custom_tracking_params() -> None:
    url = "https://example.com/News/Item?custom_click_id=xyz&b=2&a=1"

    # Without custom tracking params, custom_click_id is NOT removed:
    assert canonicalize_url(url) == "https://example.com/News/Item?a=1&b=2&custom_click_id=xyz"

    # With custom tracking params, custom_click_id IS removed:
    assert (
        canonicalize_url(url, tracking_params={"custom_click_id"})
        == "https://example.com/News/Item?a=1&b=2"
    )
