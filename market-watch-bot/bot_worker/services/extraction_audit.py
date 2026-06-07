from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml
from sqlalchemy import select

from bot_worker.config import load_settings
from bot_worker.db.models import NewsSource
from bot_worker.db.session import make_session_factory
from common.source_preview import (
    ArticlePreviewResult,
    SourcePreviewResult,
    preview_article_url,
    preview_source_url,
)

SourcePreviewFn = Callable[..., Awaitable[SourcePreviewResult]]
ArticlePreviewFn = Callable[..., Awaitable[ArticlePreviewResult]]
DbSourcesLoader = Callable[[], Awaitable[list["AuditSource"]]]

_DEFAULT_DB_LOADER = object()

SUSPICIOUS_BOILERPLATE_PATTERNS = (
    "Diễn đàn Đầu tư Việt Nam",
    "Vietnam Investment Forum",
    "Tham gia khảo sát",
    "Đặt vé Early Bird",
)


@dataclass(frozen=True)
class AuditSource:
    name: str
    url: str
    source_type: str
    origin: str


@dataclass
class AuditArticleResult:
    title: str
    url: str
    status: str
    http_status: int | None = None
    text_length: int = 0
    suspicious_boilerplate_hits: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class AuditSourceResult:
    name: str
    url: str
    source_type: str
    origin: str
    status: str
    http_status: int | None = None
    item_count: int = 0
    suspicious_boilerplate_hits: list[str] = field(default_factory=list)
    error_message: str | None = None
    articles: list[AuditArticleResult] = field(default_factory=list)


@dataclass
class ExtractionAuditReport:
    generated_at: str
    starter_sources_path: str
    db_inventory_status: str
    source_count: int
    sources: list[AuditSourceResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def audit_source_extraction(
    *,
    starter_sources_path: Path = Path("starter-sources.yml"),
    sample_limit: int = 2,
    include_db: bool = True,
    db_sources_loader: DbSourcesLoader | None | object = _DEFAULT_DB_LOADER,
    source_preview: SourcePreviewFn = preview_source_url,
    article_preview: ArticlePreviewFn = preview_article_url,
) -> ExtractionAuditReport:
    sources = _load_starter_sources(starter_sources_path)
    db_inventory_status = "skipped"

    if include_db and db_sources_loader is not None:
        loader = (
            _load_enabled_db_sources
            if db_sources_loader is _DEFAULT_DB_LOADER
            else db_sources_loader
        )
        try:
            db_sources = await loader()
        except Exception:  # noqa: BLE001 - audit should remain useful without database access
            db_inventory_status = "unavailable"
        else:
            db_inventory_status = "loaded"
            sources.extend(db_sources)

    deduped = _dedupe_sources(sources)
    results = [
        await _audit_one_source(
            source,
            sample_limit=sample_limit,
            source_preview=source_preview,
            article_preview=article_preview,
        )
        for source in deduped
    ]
    return ExtractionAuditReport(
        generated_at=datetime.now(UTC).isoformat(),
        starter_sources_path=str(starter_sources_path),
        db_inventory_status=db_inventory_status,
        source_count=len(results),
        sources=results,
    )


def _load_starter_sources(path: Path) -> list[AuditSource]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("sources", [])
    if not isinstance(rows, list):
        return []
    sources: list[AuditSource] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("enabled") is False:
            continue
        name = str(row.get("name") or "").strip()
        url = str(row.get("url") or "").strip()
        source_type = str(row.get("type") or row.get("source_type") or "rss").strip()
        if not name or not url:
            continue
        sources.append(AuditSource(name=name, url=url, source_type=source_type, origin="starter"))
    return sources


async def _load_enabled_db_sources() -> list[AuditSource]:
    settings = load_settings()
    factory = make_session_factory(settings)
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(NewsSource).where(NewsSource.enabled.is_(True)).order_by(NewsSource.name)
                )
            ).all()
        )
    return [
        AuditSource(
            name=row.name,
            url=row.url,
            source_type=row.source_type,
            origin="db",
        )
        for row in rows
    ]


def _dedupe_sources(sources: list[AuditSource]) -> list[AuditSource]:
    deduped: list[AuditSource] = []
    seen: set[str] = set()
    for source in sources:
        key = _source_key(source.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


async def _audit_one_source(
    source: AuditSource,
    *,
    sample_limit: int,
    source_preview: SourcePreviewFn,
    article_preview: ArticlePreviewFn,
) -> AuditSourceResult:
    try:
        preview = await source_preview(
            url=source.url,
            source_type=source.source_type,
            limit=sample_limit,
        )
    except Exception as exc:  # noqa: BLE001 - one source should not abort the audit
        return AuditSourceResult(
            name=source.name,
            url=source.url,
            source_type=source.source_type,
            origin=source.origin,
            status="error",
            error_message=str(exc),
        )

    result = AuditSourceResult(
        name=source.name,
        url=source.url,
        source_type=source.source_type,
        origin=source.origin,
        status=preview.status,
        http_status=preview.http_status,
        item_count=preview.item_count,
        suspicious_boilerplate_hits=_suspicious_hits(
            " ".join(item.description for item in preview.items)
        ),
        error_message=preview.error_message,
    )
    for item in preview.items[:sample_limit]:
        result.articles.append(
            await _audit_one_article(item, article_preview=article_preview)
        )
    return result


async def _audit_one_article(
    item,
    *,
    article_preview: ArticlePreviewFn,
) -> AuditArticleResult:
    try:
        preview = await article_preview(
            url=item.url,
            fallback_snippet=item.description,
            fallback_title=item.title,
            max_chars=50_000,
        )
    except Exception as exc:  # noqa: BLE001 - one article should not abort the source audit
        return AuditArticleResult(
            title=item.title,
            url=item.url,
            status="error",
            error_message=str(exc),
        )
    return AuditArticleResult(
        title=item.title,
        url=item.url,
        status=preview.status,
        http_status=preview.http_status,
        text_length=preview.text_length,
        suspicious_boilerplate_hits=_suspicious_hits(preview.text),
        error_message=preview.error_message,
    )


def _suspicious_hits(text: str | None) -> list[str]:
    if not text:
        return []
    return [pattern for pattern in SUSPICIOUS_BOILERPLATE_PATTERNS if pattern in text]


def _source_key(url: str) -> str:
    parsed = urlsplit(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))
