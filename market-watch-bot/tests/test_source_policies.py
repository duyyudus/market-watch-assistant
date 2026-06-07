from __future__ import annotations

from common.source_policies import (
    article_fetch_headers,
    boilerplate_text_rules,
    html_drop_rules,
    source_fetch_request,
)


def test_source_fetch_request_returns_original_url_and_headers() -> None:
    request = source_fetch_request(
        "https://example.com/rss/news.rss",
        headers={"If-None-Match": "etag"},
    )

    assert request.url == "https://example.com/rss/news.rss"
    assert request.headers["If-None-Match"] == "etag"
    assert "Host" not in request.headers


def test_article_fetch_headers_are_shared_user_agent_headers() -> None:
    headers = article_fetch_headers()

    assert headers["User-Agent"].startswith("market-watch-assistant/")


def test_vietnambiz_policy_declares_promo_dom_and_text_rules() -> None:
    drop_rules = html_drop_rules("https://vietnambiz.vn/example.htm")
    text_rules = boilerplate_text_rules("https://vietnambiz.vn/example.htm")

    assert any("box-vif" in rule.class_tokens for rule in drop_rules)
    assert any("simpleimage" in rule.data_types for rule in drop_rules)
    assert any("Thời gian:" in rule.start_markers for rule in text_rules)
    assert all("2026" not in marker for rule in text_rules for marker in rule.start_markers)


def test_vneconomy_policy_declares_article_boilerplate_dom_rules() -> None:
    drop_rules = html_drop_rules("https://vneconomy.vn/example.htm")
    class_tokens = set().union(*(rule.class_tokens for rule in drop_rules))

    assert "list-detail-revert_item" in class_tokens
    assert "block-job-same" in class_tokens
    assert "news-general" in class_tokens
    assert "chatbot-askonomy-ai" in class_tokens


def test_vietnambiz_promo_text_rules_are_not_global() -> None:
    text_rules = boilerplate_text_rules("https://example.com/article")

    assert not text_rules


def test_vneconomy_policy_does_not_add_text_rules() -> None:
    text_rules = boilerplate_text_rules("https://vneconomy.vn/example.htm")

    assert not text_rules
