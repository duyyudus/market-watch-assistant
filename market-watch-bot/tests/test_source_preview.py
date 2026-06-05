from __future__ import annotations

import httpx
import pytest

from common.article_text import extract_article_text
from common.source_preview import preview_article_url, preview_source_url


class FakeAsyncClient:
    response: httpx.Response
    responses: dict[str, httpx.Response] = {}

    def __init__(self, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def get(self, url: str) -> httpx.Response:
        if self.responses:
            return self.responses[url]
        return self.response


@pytest.mark.asyncio
async def test_preview_source_url_parses_rss_items(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAsyncClient.response = httpx.Response(
        200,
        text="""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>Oil jumps on shipping disruption</title>
          <link>https://example.com/oil</link>
          <description>Brent rises after a tanker incident.</description>
          <guid>oil-1</guid>
        </item></channel></rss>""",
        request=httpx.Request("GET", "https://example.com/feed.xml"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(
        url="https://example.com/feed.xml",
        source_type="rss",
        limit=10,
    )

    assert result.status == "success"
    assert result.http_status == 200
    assert result.item_count == 1
    assert result.items[0].title == "Oil jumps on shipping disruption"
    assert result.items[0].url == "https://example.com/oil"


@pytest.mark.asyncio
async def test_preview_source_url_reports_blocked_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.response = httpx.Response(
        403,
        text="blocked",
        request=httpx.Request("GET", "https://example.com/feed.xml"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(
        url="https://example.com/feed.xml",
        source_type="rss",
        limit=10,
    )

    assert result.status == "error"
    assert result.http_status == 403
    assert result.items == []
    assert "403" in (result.error_message or "")


@pytest.mark.asyncio
async def test_preview_article_url_extracts_and_caps_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.response = httpx.Response(
        200,
        text="<html><body><article>Readable article text from publisher</article></body></html>",
        request=httpx.Request("GET", "https://example.com/article"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_article_url(
        url="https://example.com/article",
        fallback_snippet=None,
        max_chars=16,
    )

    assert result.status == "success"
    assert result.text == "Readable article"
    assert result.truncated is True


def test_extract_article_text_strips_html() -> None:
    text = extract_article_text("<html><body><h1>Headline</h1><p>Body text</p></body></html>")

    assert text is not None
    assert "Body text" in text


@pytest.mark.asyncio
async def test_preview_source_url_crawls_section_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section_url = "https://example.com/markets/"
    article_url = "https://example.com/markets/banks-rally-2026-06-05/"
    FakeAsyncClient.responses = {
        section_url: httpx.Response(
            200,
            text=f'<html><body><a href="{article_url}">Banks rally</a></body></html>',
            request=httpx.Request("GET", section_url),
        ),
        article_url: httpx.Response(
            200,
            text="""<html><head>
            <meta property="og:title" content="Banks rally on policy easing">
            <meta property="og:description" content="Bank shares rose after policy easing.">
            <meta property="article:published_time" content="2026-06-05T08:00:00+00:00">
            </head><body><article>Bank shares rose after policy easing.</article></body></html>""",
            request=httpx.Request("GET", article_url),
        ),
    }
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(
        url=section_url,
        source_type="crawler",
        limit=10,
    )

    FakeAsyncClient.responses = {}
    assert result.status == "success"
    assert result.http_status == 200
    assert result.item_count == 1
    assert result.items[0].title == "Banks rally on policy easing"
    assert result.items[0].url == article_url
    assert result.items[0].description == "Bank shares rose after policy easing."
