from types import SimpleNamespace

import httpx
import pytest

from bot_worker import crawler
from bot_worker.crawler import ParsedCrawlerArticle, discover_article_urls, parse_article_html
from bot_worker.db.models import NewsSource, SourceFetchLog
from bot_worker.services import sources as source_services

SECTION_HTML = """
<html>
  <body>
    <nav><a href="/business/">Business</a></nav>
    <a href="/business/energy/oil-rises-2026-06-02/">Oil rises on supply concerns</a>
    <a href="https://www.reuters.com/markets/us/stocks-advance-2026-06-02/">
      Stocks advance before jobs data
    </a>
    <a href="https://www.youtube.com/watch?v=abc">Video</a>
    <a href="https://other.example.com/business/story">Off domain</a>
    <a href="/business/energy/oil-rises-2026-06-02/?utm_source=front">Duplicate</a>
    <a href="/pictures/markets-gallery-2026-06-02/">Gallery</a>
  </body>
</html>
"""


ARTICLE_HTML = """
<html>
  <head>
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Oil rises on supply concerns",
        "description": "Brent crude climbs as traders weigh shipping disruptions.",
        "datePublished": "2026-06-02T03:15:00Z"
      }
    </script>
    <meta property="og:title" content="Fallback title">
    <meta name="description" content="Fallback snippet">
  </head>
  <body>
    <article>
      <h1>Oil rises on supply concerns</h1>
      <p>Brent crude climbed on Tuesday as traders weighed fresh shipping disruptions.</p>
      <p>Analysts said volatility remains elevated.</p>
    </article>
  </body>
</html>
"""


FALLBACK_ARTICLE_HTML = """
<html>
  <head>
    <meta property="og:title" content="Stocks advance before jobs data">
    <meta property="og:description" content="Investors look ahead to payrolls.">
  </head>
  <body>
    <time datetime="2026-06-02T09:00:00+00:00">June 2, 2026</time>
    <p>US stocks gained before employment data.</p>
  </body>
</html>
"""


def test_discover_article_urls_filters_and_deduplicates_section_links() -> None:
    urls = discover_article_urls(
        SECTION_HTML,
        section_url="https://www.reuters.com/business/",
    )

    assert urls == [
        "https://www.reuters.com/business/energy/oil-rises-2026-06-02/",
        "https://www.reuters.com/markets/us/stocks-advance-2026-06-02/",
    ]


def test_parse_article_html_prefers_json_ld_metadata_and_extracts_text() -> None:
    article = parse_article_html(
        ARTICLE_HTML,
        url="https://www.reuters.com/business/energy/oil-rises-2026-06-02/",
    )

    assert article.title == "Oil rises on supply concerns"
    assert article.description == "Brent crude climbs as traders weigh shipping disruptions."
    assert article.published == "2026-06-02T03:15:00Z"
    assert article.url == "https://www.reuters.com/business/energy/oil-rises-2026-06-02/"
    assert article.content is not None
    assert "Brent crude climbed on Tuesday" in article.content


def test_parse_article_html_falls_back_to_meta_and_time_tags() -> None:
    article = parse_article_html(
        FALLBACK_ARTICLE_HTML,
        url="https://www.cnbc.com/2026/06/02/stocks-advance-before-jobs-data.html",
    )

    assert article.title == "Stocks advance before jobs data"
    assert article.description == "Investors look ahead to payrolls."
    assert article.published == "2026-06-02T09:00:00+00:00"


@pytest.mark.asyncio
async def test_fetch_source_routes_crawler_items_into_raw_news(monkeypatch) -> None:
    source = NewsSource(
        id="src_1",
        name="Reuters Business",
        url="https://www.reuters.com/business/",
        source_type="crawler",
        region="global",
        category="global_macro",
        language="en",
        source_score=85,
        polling_interval_seconds=600,
        asset_classes=["global_macro"],
    )
    added = []
    executed_values = []

    class FetchSession:
        def add(self, obj):
            added.append(obj)

        async def execute(self, stmt):
            executed_values.append(stmt.compile().params)
            return SimpleNamespace(rowcount=1)

    async def fake_fetch_source_content(_source):
        return 200, SECTION_HTML, {
            "etag": "etag-1",
            "last-modified": "Tue, 02 Jun 2026 00:00:00 GMT",
        }

    async def fake_crawl_section_articles(*, section_url, section_html, fetch_html):
        assert section_url == "https://www.reuters.com/business/"
        assert section_html == SECTION_HTML
        assert fetch_html is not None
        return [
            ParsedCrawlerArticle(
                title="Oil rises on supply concerns",
                url="https://www.reuters.com/business/energy/oil-rises-2026-06-02/",
                description="Brent crude climbs as traders weigh shipping disruptions.",
                published="2026-06-02T03:15:00Z",
                content="Brent crude climbed on Tuesday.",
                raw_payload={"source": "crawler"},
            )
        ]

    monkeypatch.setattr(source_services, "fetch_source_content", fake_fetch_source_content)
    monkeypatch.setattr(crawler, "crawl_section_articles", fake_crawl_section_articles)
    monkeypatch.setattr(source_services, "crawl_section_articles", fake_crawl_section_articles)

    result = await source_services.fetch_source(FetchSession(), source)

    assert result == {"status": "success", "items": 1, "inserted": 1}
    assert source.etag == "etag-1"
    assert source.last_modified == "Tue, 02 Jun 2026 00:00:00 GMT"
    assert any(isinstance(obj, SourceFetchLog) and obj.status == "success" for obj in added)
    inserted = executed_values[0]
    assert inserted["raw_title"] == "Oil rises on supply concerns"
    assert (
        inserted["raw_description"]
        == "Brent crude climbs as traders weigh shipping disruptions."
    )
    assert inserted["raw_content"] == "Brent crude climbed on Tuesday."
    assert inserted["raw_published_at"] == "2026-06-02T03:15:00+00:00"
    assert inserted["raw_url"] == "https://www.reuters.com/business/energy/oil-rises-2026-06-02/"


@pytest.mark.asyncio
async def test_fetch_source_records_crawler_not_modified_without_parsing(monkeypatch) -> None:
    source = NewsSource(
        id="src_1",
        name="Reuters Business",
        url="https://www.reuters.com/business/",
        source_type="crawler",
        region="global",
        category="global_macro",
        language="en",
        source_score=85,
        polling_interval_seconds=600,
        asset_classes=["global_macro"],
    )
    added = []

    class FetchSession:
        def add(self, obj):
            added.append(obj)

    async def fake_fetch_source_content(_source):
        return 304, "", {}

    async def fail_crawl_section_articles(**_kwargs):
        raise AssertionError("not-modified sources should not be parsed")

    monkeypatch.setattr(source_services, "fetch_source_content", fake_fetch_source_content)
    monkeypatch.setattr(source_services, "crawl_section_articles", fail_crawl_section_articles)

    result = await source_services.fetch_source(FetchSession(), source)

    assert result == {"status": "not_modified", "items": 0, "inserted": 0}
    assert any(isinstance(obj, SourceFetchLog) and obj.http_status == 304 for obj in added)


@pytest.mark.asyncio
async def test_fetch_source_skips_crawler_access_denied_without_failure(monkeypatch) -> None:
    source = NewsSource(
        id="src_1",
        name="Reuters Business",
        url="https://www.reuters.com/business/",
        source_type="crawler",
        region="global",
        category="global_macro",
        language="en",
        source_score=85,
        polling_interval_seconds=600,
        asset_classes=["global_macro"],
    )
    added = []

    class FetchSession:
        def add(self, obj):
            added.append(obj)

    async def fake_fetch_source_content(_source):
        request = httpx.Request("GET", "https://www.reuters.com/business/")
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError("403 Forbidden", request=request, response=response)

    async def fail_crawl_section_articles(**_kwargs):
        raise AssertionError("access-denied sources should not be parsed")

    monkeypatch.setattr(source_services, "fetch_source_content", fake_fetch_source_content)
    monkeypatch.setattr(source_services, "crawl_section_articles", fail_crawl_section_articles)

    result = await source_services.fetch_source(FetchSession(), source)

    assert result == {"status": "skipped", "reason": "access_denied", "http_status": 403}
    assert source.consecutive_failure_count == 0
    assert any(
        isinstance(obj, SourceFetchLog)
        and obj.status == "skipped"
        and obj.http_status == 403
        and obj.error_message == "crawler access denied"
        for obj in added
    )
