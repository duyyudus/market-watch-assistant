from __future__ import annotations

import re

from common.rss import ParsedFeedItem, parse_rss_items


def parse_source_items(
    body: str,
    *,
    source_type: str,
) -> list[ParsedFeedItem]:
    if source_type == "google-rss":
        return [_google_rss_feed_item(item) for item in parse_rss_items(body)]
    if source_type == "rss":
        return parse_rss_items(body)
    return []


async def parse_source_items_async(
    body: str,
    *,
    source_type: str,
) -> list[ParsedFeedItem]:
    if source_type == "google-rss":
        return [_google_rss_feed_item(item) for item in parse_rss_items(body)]
    return parse_source_items(body, source_type=source_type)


def _google_rss_feed_item(item: ParsedFeedItem) -> ParsedFeedItem:
    raw_payload = dict(item.raw_payload)
    raw_payload["google_news_url"] = item.url
    return _feed_item_with(
        item,
        url=item.url,
        description=google_rss_description(item),
        raw_payload=raw_payload,
    )


def google_rss_description(item: ParsedFeedItem) -> str:
    if _same_google_rss_text(item.description, item.title):
        return ""
    if not _looks_like_true_summary(item.description):
        return ""
    return item.description


def _looks_like_true_summary(value: str) -> bool:
    return len(re.findall(r"[.!?](?=\s|$)", value)) >= 2


def _same_google_rss_text(left: str, right: str) -> bool:
    return _google_rss_text_key(left) == _google_rss_text_key(right)


def _google_rss_text_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def _feed_item_with(
    item: ParsedFeedItem,
    *,
    url: str,
    description: str | None = None,
    raw_payload: dict[str, object],
) -> ParsedFeedItem:
    return ParsedFeedItem(
        title=item.title,
        url=url,
        description=item.description if description is None else description,
        published=item.published,
        guid=item.guid,
        raw_payload=raw_payload,
    )
