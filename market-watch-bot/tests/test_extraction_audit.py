from __future__ import annotations

from pathlib import Path

import pytest

from bot_worker.services.extraction_audit import (
    AuditSource,
    audit_source_extraction,
)
from common.source_preview import (
    ArticlePreviewResult,
    SourcePreviewItem,
    SourcePreviewResult,
)


def _write_starter_sources(path: Path) -> Path:
    source_path = path / "starter-sources.yml"
    source_path.write_text(
        """
sources:
- name: Starter RSS
  url: https://example.com/feed.xml
  type: rss
  region: global
  category: global_macro
  enabled: true
- name: Disabled RSS
  url: https://example.com/disabled.xml
  type: rss
  enabled: false
""",
        encoding="utf-8",
    )
    return source_path


@pytest.mark.asyncio
async def test_audit_source_extraction_uses_starter_sources_when_db_unavailable(
    tmp_path: Path,
) -> None:
    starter_path = _write_starter_sources(tmp_path)

    async def fail_db_loader() -> list[AuditSource]:
        raise RuntimeError("database unavailable")

    async def fake_preview_source(*, url: str, source_type: str, limit: int) -> SourcePreviewResult:
        assert url == "https://example.com/feed.xml"
        assert source_type == "rss"
        assert limit == 2
        return SourcePreviewResult(
            status="success",
            url=url,
            source_type=source_type,
            http_status=200,
            duration_ms=5,
            item_count=1,
            items=[
                SourcePreviewItem(
                    title="VN-Index rises",
                    url="https://example.com/article",
                    description="Market summary",
                    published_at=None,
                    guid=None,
                )
            ],
        )

    async def fake_preview_article(
        *, url: str, fallback_snippet: str | None, fallback_title: str | None, max_chars: int
    ) -> ArticlePreviewResult:
        assert url == "https://example.com/article"
        assert fallback_snippet == "Market summary"
        assert fallback_title == "VN-Index rises"
        return ArticlePreviewResult.from_text(
            url=url,
            http_status=200,
            duration_ms=4,
            text="Useful article text",
            max_chars=max_chars,
        )

    report = await audit_source_extraction(
        starter_sources_path=starter_path,
        sample_limit=2,
        db_sources_loader=fail_db_loader,
        source_preview=fake_preview_source,
        article_preview=fake_preview_article,
    )

    assert report.db_inventory_status == "unavailable"
    assert len(report.sources) == 1
    assert report.sources[0].name == "Starter RSS"
    assert report.sources[0].articles[0].status == "success"
    assert report.sources[0].articles[0].text_length == len("Useful article text")


@pytest.mark.asyncio
async def test_audit_source_extraction_dedupes_starter_and_db_sources(tmp_path: Path) -> None:
    starter_path = _write_starter_sources(tmp_path)
    previewed_urls: list[str] = []

    async def db_loader() -> list[AuditSource]:
        return [
            AuditSource(
                name="DB duplicate",
                url="https://example.com/feed.xml",
                source_type="rss",
                origin="db",
            ),
            AuditSource(
                name="DB crawler",
                url="https://example.com/markets/",
                source_type="crawler",
                origin="db",
            ),
        ]

    async def fake_preview_source(*, url: str, source_type: str, limit: int) -> SourcePreviewResult:
        previewed_urls.append(url)
        return SourcePreviewResult(
            status="success",
            url=url,
            source_type=source_type,
            http_status=200,
            duration_ms=5,
            item_count=0,
            items=[],
        )

    report = await audit_source_extraction(
        starter_sources_path=starter_path,
        db_sources_loader=db_loader,
        source_preview=fake_preview_source,
    )

    assert report.db_inventory_status == "loaded"
    assert previewed_urls == ["https://example.com/feed.xml", "https://example.com/markets/"]
    assert [source.name for source in report.sources] == ["Starter RSS", "DB crawler"]


@pytest.mark.asyncio
async def test_audit_source_extraction_reports_failures_per_source(tmp_path: Path) -> None:
    starter_path = _write_starter_sources(tmp_path)

    async def fake_preview_source(*, url: str, source_type: str, limit: int) -> SourcePreviewResult:
        raise RuntimeError("provider timeout")

    report = await audit_source_extraction(
        starter_sources_path=starter_path,
        db_sources_loader=None,
        source_preview=fake_preview_source,
    )

    assert len(report.sources) == 1
    assert report.sources[0].status == "error"
    assert "provider timeout" in (report.sources[0].error_message or "")
