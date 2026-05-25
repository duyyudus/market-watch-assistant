from __future__ import annotations

from dataclasses import dataclass

import feedparser


@dataclass(frozen=True)
class ParsedFeedItem:
    title: str
    url: str
    description: str
    published: object | None
    guid: str | None
    raw_payload: dict[str, object]


def parse_rss_items(content: str | bytes) -> list[ParsedFeedItem]:
    feed = feedparser.parse(content)
    items: list[ParsedFeedItem] = []
    for entry in feed.entries:
        title = entry.get("title", "")
        url = entry.get("link", "")
        if not title or not url:
            continue
        items.append(
            ParsedFeedItem(
                title=title,
                url=url,
                description=entry.get("summary", entry.get("description", "")),
                published=entry.get("published_parsed") or entry.get("updated_parsed"),
                guid=entry.get("id"),
                raw_payload=dict(entry),
            )
        )
    return items
