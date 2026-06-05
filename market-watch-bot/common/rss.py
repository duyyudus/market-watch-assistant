from __future__ import annotations

import html
import re
import unicodedata
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
    if not feed.entries:
        feed = feedparser.parse(_repair_mislabeled_utf16(content))
    items: list[ParsedFeedItem] = []
    for entry in feed.entries:
        title = _clean_feed_text(entry.get("title", ""))
        url = entry.get("link", "")
        if not title or not url:
            continue
        items.append(
            ParsedFeedItem(
                title=title,
                url=url,
                description=_clean_feed_text(
                    entry.get("summary", entry.get("description", "")),
                ),
                published=entry.get("published_parsed") or entry.get("updated_parsed"),
                guid=entry.get("id"),
                raw_payload=dict(entry),
            )
        )
    return items


def _repair_mislabeled_utf16(content: str | bytes) -> str | bytes:
    if isinstance(content, bytes):
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            return content
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return content
    else:
        text = content
    if not re.search(r"<\?xml[^>]+encoding=[\"']utf-16[\"']", text[:120], re.IGNORECASE):
        return content
    return re.sub(
        r"(<\?xml[^>]+encoding=)[\"']utf-16[\"']",
        r'\1"utf-8"',
        text,
        count=1,
        flags=re.IGNORECASE,
    )


def _clean_feed_text(value: object) -> str:
    if not value:
        return ""
    text = str(value)
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
