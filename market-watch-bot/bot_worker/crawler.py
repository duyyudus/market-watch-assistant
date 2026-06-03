from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from bot_worker.normalize import normalize_text


@dataclass(frozen=True)
class ParsedCrawlerArticle:
    title: str
    url: str
    description: str
    published: object | None
    content: str | None
    raw_payload: dict[str, object]


class _CrawlerHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self.times: list[str] = []
        self.h1_values: list[str] = []
        self._script_type: str | None = None
        self._script_chunks: list[str] = []
        self._capture_h1 = False
        self._h1_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag == "a" and attrs_dict.get("href"):
            self.links.append(attrs_dict["href"])
        elif tag == "meta":
            key = attrs_dict.get("property") or attrs_dict.get("name")
            value = attrs_dict.get("content")
            if key and value:
                self.meta[key.lower()] = value
        elif tag == "script":
            self._script_type = attrs_dict.get("type", "").lower()
            self._script_chunks = []
        elif tag == "time" and attrs_dict.get("datetime"):
            self.times.append(attrs_dict["datetime"])
        elif tag == "h1":
            self._capture_h1 = True
            self._h1_chunks = []

    def handle_data(self, data: str) -> None:
        if self._script_type == "application/ld+json":
            self._script_chunks.append(data)
        if self._capture_h1:
            self._h1_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            if self._script_type == "application/ld+json":
                script = "".join(self._script_chunks).strip()
                if script:
                    self.json_ld.append(script)
            self._script_type = None
            self._script_chunks = []
        elif tag == "h1":
            h1 = normalize_text(" ".join(self._h1_chunks))
            if h1:
                self.h1_values.append(h1)
            self._capture_h1 = False
            self._h1_chunks = []


ARTICLE_TYPES = {"article", "newsarticle", "reportagenewsarticle", "analysisnewsarticle"}
BLOCKED_PATH_PARTS = {
    "about",
    "advertising",
    "careers",
    "contact",
    "cookies",
    "gallery",
    "live-tv",
    "newsletters",
    "pictures",
    "podcasts",
    "privacy",
    "search",
    "signin",
    "subscribe",
    "terms",
    "video",
    "videos",
}
BLOCKED_EXTENSIONS = (
    ".avi",
    ".gif",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webp",
)


def discover_article_urls(
    html: str,
    *,
    section_url: str,
    limit: int = 30,
) -> list[str]:
    parser = _parse(html)
    section = urlsplit(section_url)
    section_origin = section.netloc.lower()
    section_path = section.path.rstrip("/")
    discovered: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        url = _canonicalize_discovered_url(urljoin(section_url, href))
        if not url:
            continue
        parsed = urlsplit(url)
        if not _same_site(parsed.netloc.lower(), section_origin):
            continue
        if parsed.path.rstrip("/") == section_path:
            continue
        if not _looks_like_article_path(parsed.path):
            continue
        if url in seen:
            continue
        seen.add(url)
        discovered.append(url)
        if len(discovered) >= limit:
            break
    return discovered


def parse_article_html(html: str, *, url: str) -> ParsedCrawlerArticle:
    parser = _parse(html)
    metadata = _article_metadata_from_json_ld(parser.json_ld)
    title = (
        _first_string(metadata.get("headline"))
        or _meta_first(parser.meta, "og:title", "twitter:title", "title")
        or (parser.h1_values[0] if parser.h1_values else "")
    )
    description = (
        _first_string(metadata.get("description"))
        or _meta_first(parser.meta, "og:description", "twitter:description", "description")
        or ""
    )
    published = (
        _first_string(metadata.get("datePublished"))
        or _first_string(metadata.get("dateModified"))
        or _meta_first(
            parser.meta,
            "article:published_time",
            "article:modified_time",
            "date",
            "pubdate",
        )
        or (parser.times[0] if parser.times else None)
    )
    content = extract_readable_text(html)
    return ParsedCrawlerArticle(
        title=normalize_text(title),
        url=url,
        description=normalize_text(description),
        published=published,
        content=content,
        raw_payload={
            "url": url,
            "metadata": metadata,
            "meta": parser.meta,
            "content_extracted": bool(content),
        },
    )


async def crawl_section_articles(
    *,
    section_url: str,
    section_html: str,
    fetch_html,
    limit: int = 20,
    ignored_urls: set[str] | None = None,
) -> list[ParsedCrawlerArticle]:
    articles: list[ParsedCrawlerArticle] = []
    discovered = discover_article_urls(section_html, section_url=section_url, limit=limit)
    if ignored_urls:
        discovered = [url for url in discovered if url not in ignored_urls]
    for url in discovered:
        try:
            article_html = await fetch_html(url)
        except Exception:  # noqa: BLE001 - one article fetch should not fail the source
            continue
        article = parse_article_html(article_html, url=url)
        if article.title:
            articles.append(article)
    return articles


def extract_readable_text(html: str) -> str | None:
    try:
        import trafilatura  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - parser fallback keeps crawler usable
        trafilatura = None
    if trafilatura is not None:
        text = trafilatura.extract(html)
        if text:
            return normalize_text(text)
    text = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_text(text) or None


def _parse(html: str) -> _CrawlerHTMLParser:
    parser = _CrawlerHTMLParser()
    parser.feed(html)
    return parser


def _canonicalize_discovered_url(url: str) -> str | None:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    path = parsed.path or "/"
    if path.lower().endswith(BLOCKED_EXTENSIONS):
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _same_site(candidate: str, origin: str) -> bool:
    if candidate == origin:
        return True
    return candidate.endswith(f".{origin}")


def _looks_like_article_path(path: str) -> bool:
    normalized = path.strip("/").lower()
    if not normalized:
        return False
    parts = [part for part in normalized.split("/") if part]
    if any(part in BLOCKED_PATH_PARTS for part in parts):
        return False
    if re.search(r"\b20\d{2}[-/]\d{2}[-/]\d{2}\b", normalized):
        return True
    if normalized.endswith(".html") and len(parts) >= 2:
        return True
    if len(parts) >= 2 and parts[0] in {"article", "content"}:
        return True
    if len(parts) >= 3 and any(part.startswith("20") for part in parts):
        return True
    return len(parts) >= 3 and "-" in parts[-1]


def _article_metadata_from_json_ld(scripts: list[str]) -> dict[str, object]:
    for script in scripts:
        try:
            value = json.loads(script)
        except json.JSONDecodeError:
            continue
        article = _find_article_schema(value)
        if article is not None:
            return article
    return {}


def _find_article_schema(value: object) -> dict[str, object] | None:
    if isinstance(value, list):
        for item in value:
            found = _find_article_schema(item)
            if found is not None:
                return found
        return None
    if not isinstance(value, dict):
        return None
    graph = value.get("@graph")
    if isinstance(graph, list):
        found = _find_article_schema(graph)
        if found is not None:
            return found
    raw_type = value.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    normalized_types = {str(item).lower() for item in types if item}
    if normalized_types & ARTICLE_TYPES:
        return value
    return None


def _meta_first(meta: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = normalize_text(meta.get(key))
        if value:
            return value
    return ""


def _first_string(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _first_string(value.get("name") or value.get("@value"))
    if isinstance(value, list):
        for item in value:
            result = _first_string(item)
            if result:
                return result
    return ""
