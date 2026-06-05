from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import mktime, perf_counter

import httpx

from common.article_text import extract_article_text
from common.config import validate_source_type
from common.crawler import ParsedCrawlerArticle, crawl_section_articles
from common.rss import ParsedFeedItem, parse_rss_items

PREVIEW_SUPPORTED_SOURCE_TYPES = {"rss", "google-rss", "crawler"}
DEFAULT_ARTICLE_MAX_CHARS = 20_000


@dataclass(frozen=True)
class SourcePreviewItem:
    title: str
    url: str
    description: str
    published_at: str | None
    guid: str | None


@dataclass(frozen=True)
class SourcePreviewResult:
    status: str
    url: str
    source_type: str
    http_status: int | None
    duration_ms: int
    item_count: int
    items: list[SourcePreviewItem]
    error_message: str | None = None

    @classmethod
    def from_rss(
        cls,
        *,
        url: str,
        source_type: str,
        http_status: int,
        duration_ms: int,
        body: str,
        limit: int,
    ) -> SourcePreviewResult:
        items = [_preview_item(item) for item in parse_rss_items(body)[:limit]]
        return cls(
            status="success",
            url=url,
            source_type=source_type,
            http_status=http_status,
            duration_ms=duration_ms,
            item_count=len(items),
            items=items,
        )


@dataclass(frozen=True)
class ArticlePreviewResult:
    status: str
    url: str
    http_status: int | None
    duration_ms: int
    text: str
    text_length: int
    truncated: bool
    error_message: str | None = None

    @classmethod
    def from_text(
        cls,
        *,
        url: str,
        http_status: int,
        duration_ms: int,
        text: str,
        max_chars: int,
    ) -> ArticlePreviewResult:
        text_length = len(text)
        return cls(
            status="success",
            url=url,
            http_status=http_status,
            duration_ms=duration_ms,
            text=text[:max_chars],
            text_length=text_length,
            truncated=text_length > max_chars,
        )


async def preview_source_url(
    *,
    url: str,
    source_type: str,
    limit: int = 10,
) -> SourcePreviewResult:
    started = perf_counter()
    try:
        validate_source_type(source_type)
    except ValueError as exc:
        return _source_error(
            url=url,
            source_type=source_type,
            duration_ms=_duration_ms(started),
            message=str(exc),
        )
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(str(url))
            response.raise_for_status()
            if source_type == "crawler":
                articles = await crawl_section_articles(
                    section_url=url,
                    section_html=response.text,
                    fetch_html=lambda article_url: _fetch_text(client, article_url),
                    limit=limit,
                )
                items = [_crawler_preview_item(article) for article in articles[:limit]]
                return SourcePreviewResult(
                    status="success",
                    url=url,
                    source_type=source_type,
                    http_status=response.status_code,
                    duration_ms=_duration_ms(started),
                    item_count=len(items),
                    items=items,
                )
    except httpx.HTTPStatusError as exc:
        return _source_error(
            url=url,
            source_type=source_type,
            duration_ms=_duration_ms(started),
            message=_format_fetch_error(exc),
            http_status=exc.response.status_code,
        )
    except Exception as exc:  # noqa: BLE001 - preview should report provider boundary failures
        return _source_error(
            url=url,
            source_type=source_type,
            duration_ms=_duration_ms(started),
            message=_format_fetch_error(exc),
        )

    return SourcePreviewResult.from_rss(
        url=url,
        source_type=source_type,
        http_status=response.status_code,
        duration_ms=_duration_ms(started),
        body=response.text,
        limit=limit,
    )


async def preview_article_url(
    *,
    url: str,
    fallback_snippet: str | None = None,
    max_chars: int = DEFAULT_ARTICLE_MAX_CHARS,
) -> ArticlePreviewResult:
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(str(url))
            response.raise_for_status()
        text = extract_article_text(response.text)
        if not text and fallback_snippet:
            text = fallback_snippet.strip()
        if not text:
            return _article_error(
                url=url,
                duration_ms=_duration_ms(started),
                message="no_text_extracted",
                http_status=response.status_code,
            )
        return ArticlePreviewResult.from_text(
            url=url,
            http_status=response.status_code,
            duration_ms=_duration_ms(started),
            text=text,
            max_chars=max_chars,
        )
    except httpx.HTTPStatusError as exc:
        text = (fallback_snippet or "").strip()
        if text:
            return ArticlePreviewResult(
                status="fallback",
                url=url,
                http_status=exc.response.status_code,
                duration_ms=_duration_ms(started),
                text=text[:max_chars],
                text_length=len(text),
                truncated=len(text) > max_chars,
                error_message=_format_fetch_error(exc),
            )
        return _article_error(
            url=url,
            duration_ms=_duration_ms(started),
            message=_format_fetch_error(exc),
            http_status=exc.response.status_code,
        )
    except Exception as exc:  # noqa: BLE001 - preview should report provider boundary failures
        text = (fallback_snippet or "").strip()
        if text:
            return ArticlePreviewResult(
                status="fallback",
                url=url,
                http_status=None,
                duration_ms=_duration_ms(started),
                text=text[:max_chars],
                text_length=len(text),
                truncated=len(text) > max_chars,
                error_message=_format_fetch_error(exc),
            )
        return _article_error(
            url=url,
            duration_ms=_duration_ms(started),
            message=_format_fetch_error(exc),
        )


def _preview_item(item: ParsedFeedItem) -> SourcePreviewItem:
    return SourcePreviewItem(
        title=item.title,
        url=item.url,
        description=item.description,
        published_at=_published_to_iso(item.published),
        guid=item.guid,
    )


def _crawler_preview_item(item: ParsedCrawlerArticle) -> SourcePreviewItem:
    return SourcePreviewItem(
        title=item.title,
        url=item.url,
        description=item.description or item.content or "",
        published_at=_published_to_iso(item.published),
        guid=None,
    )


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(str(url))
    response.raise_for_status()
    return response.text


def _published_to_iso(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return datetime.fromtimestamp(mktime(value), tz=UTC).isoformat()
    except Exception:  # noqa: BLE001 - malformed feed dates are not fatal to preview
        return None


def _source_error(
    *,
    url: str,
    source_type: str,
    duration_ms: int,
    message: str,
    http_status: int | None = None,
) -> SourcePreviewResult:
    return SourcePreviewResult(
        status="error",
        url=url,
        source_type=source_type,
        http_status=http_status,
        duration_ms=duration_ms,
        item_count=0,
        items=[],
        error_message=message,
    )


def _article_error(
    *,
    url: str,
    duration_ms: int,
    message: str,
    http_status: int | None = None,
) -> ArticlePreviewResult:
    return ArticlePreviewResult(
        status="error",
        url=url,
        http_status=http_status,
        duration_ms=duration_ms,
        text="",
        text_length=0,
        truncated=False,
        error_message=message,
    )


def _format_fetch_error(exc: Exception) -> str:
    message = str(exc)
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _duration_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
