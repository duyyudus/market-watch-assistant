from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "fbclid",
    "gclid",
    "ref",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_disclosure_noise_title(
    title: str | None, patterns: list[str] | tuple[str, ...] | None
) -> bool:
    """True when ``title`` contains any routine-disclosure marker in ``patterns``.

    Patterns are operator-configured (settings.ingestion.disclosure_noise_patterns) and
    matched as case-insensitive substrings; an empty or missing list disables filtering.
    Routine regulatory/fund disclosures (e.g. RNS-style "Net Asset Value" filings) are
    republished in bulk by aggregator feeds and cluster/embed together as false merges
    without being real events, so they are dropped before clustering.
    """
    if not title or not patterns:
        return False
    haystack = title.casefold()
    return any(pattern.casefold() in haystack for pattern in patterns if pattern)


def canonicalize_url(url: str, tracking_params: set[str] | None = None) -> str:
    parsed = urlsplit(url.strip())
    params = tracking_params if tracking_params is not None else TRACKING_PARAMS
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in params
    ]
    return urlunsplit(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            parsed.path or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def title_hash(title: str) -> str:
    return _digest(normalize_text(title).casefold())


def content_hash(text: str) -> str:
    return _digest(normalize_text(text).casefold())


def normalize_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
        return normalize_datetime(parsed)
    if isinstance(value, struct_time | tuple):
        try:
            return datetime(*tuple(value)[:6], tzinfo=UTC)
        except (TypeError, ValueError):
            return None
    return None
