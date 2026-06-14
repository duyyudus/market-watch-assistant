from datetime import UTC, datetime

from bot_worker.db.models import NewsSource, RawNewsItem
from bot_worker.normalize import (
    canonicalize_url,
    content_hash,
    is_disclosure_noise_title,
    normalize_datetime,
    normalize_text,
    title_hash,
)
from bot_worker.services.ingestion import mark_exact_duplicates, normalize_pending_raw_items


def test_canonicalize_url_removes_tracking_and_normalizes_host() -> None:
    url = "HTTPS://Example.com/News/Item?utm_source=x&b=2&fbclid=abc&a=1#section"

    assert canonicalize_url(url) == "https://example.com/News/Item?a=1&b=2"


def test_text_and_title_hash_are_stable_for_whitespace_and_case() -> None:
    assert normalize_text("  Fed&nbsp; cuts\n rates  ") == "Fed cuts rates"
    assert title_hash("Fed cuts rates") == title_hash("  fed   cuts RATES ")
    assert content_hash("Fed cuts rates") == content_hash("Fed   cuts rates")


def test_normalize_datetime_handles_rss_struct_and_iso_string() -> None:
    assert normalize_datetime("2026-05-25T03:00:00+00:00") == datetime(
        2026, 5, 25, 3, 0, tzinfo=UTC
    )
    assert normalize_datetime((2026, 5, 25, 10, 0, 0, 0, 145, 0)) == datetime(
        2026, 5, 25, 10, 0, tzinfo=UTC
    )


def test_canonicalize_url_supports_custom_tracking_params() -> None:
    url = "https://example.com/News/Item?custom_click_id=xyz&b=2&a=1"

    # Without custom tracking params, custom_click_id is NOT removed:
    assert canonicalize_url(url) == "https://example.com/News/Item?a=1&b=2&custom_click_id=xyz"

    # With custom tracking params, custom_click_id IS removed:
    assert (
        canonicalize_url(url, tracking_params={"custom_click_id"})
        == "https://example.com/News/Item?a=1&b=2"
    )


async def test_mark_exact_duplicates_uses_database_update_without_loading_items() -> None:
    class DedupSession:
        def __init__(self) -> None:
            self.executed: list[object] = []

        async def execute(self, stmt):
            self.executed.append(stmt)

            class Result:
                rowcount = 3

            return Result()

        async def scalars(self, _stmt):  # pragma: no cover - should not be called
            raise AssertionError("deduplication must not load all normalized news rows")

    session = DedupSession()

    count = await mark_exact_duplicates(session)

    assert count == 3
    assert len(session.executed) == 1
    assert "row_number()" in str(session.executed[0]).lower()


async def test_mark_exact_duplicates_uses_title_and_snippet_for_google_rss() -> None:
    class DedupSession:
        def __init__(self) -> None:
            self.executed: list[object] = []

        async def execute(self, stmt):
            self.executed.append(stmt)

            class Result:
                rowcount = 2

            return Result()

    session = DedupSession()

    count = await mark_exact_duplicates(session)
    sql = str(session.executed[0]).lower()

    assert count == 2
    assert "source_type = :source_type_1" in sql
    assert "normalized_news_items.snippet is not null" in sql
    assert "normalized_news_items.normalized_text_hash" in sql


async def test_mark_exact_duplicates_uses_url_fallback_for_google_rss_without_snippet() -> None:
    class DedupSession:
        def __init__(self) -> None:
            self.executed: list[object] = []

        async def execute(self, stmt):
            self.executed.append(stmt)

            class Result:
                rowcount = 1

            return Result()

    session = DedupSession()

    await mark_exact_duplicates(session)
    sql = str(session.executed[0]).lower()

    assert "normalized_news_items.source_type = :source_type_1" in sql
    assert "normalized_news_items.snippet is not null" in sql
    assert "else normalized_news_items.canonical_url_hash" in sql


async def test_normalize_google_rss_items_marks_full_text_skipped() -> None:
    source = NewsSource(
        id="src_google",
        name="Google RSS",
        source_type="google-rss",
        source_score=60,
        language="en",
        region="global",
        asset_classes=["global_macro"],
    )
    raw = RawNewsItem(
        id="raw_1",
        source_id=source.id,
        raw_title="Oil rises",
        raw_description="Crude climbs.",
        raw_url="https://news.google.com/rss/articles/encoded?oc=5",
        raw_published_at="2026-06-02T09:00:00+00:00",
        raw_payload={"google_news_url": "https://news.google.com/rss/articles/encoded?oc=5"},
        content_hash="hash",
        fetched_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
    )

    class NormalizeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.execute_count = 0

        async def execute(self, _stmt):
            self.execute_count += 1

            class Result:
                def all(self_inner):
                    if self.execute_count == 1:
                        return [(raw, source)]
                    return []

            return Result()

        def add(self, item: object) -> None:
            self.added.append(item)

    session = NormalizeSession()

    inserted = await normalize_pending_raw_items(session, freshness_hours=24 * 365)
    item = session.added[0]

    assert inserted == 1
    assert item.source_type == "google-rss"
    assert item.full_text_available is False
    assert item.full_text_extraction_status == "skipped"
    assert item.full_text_last_error == "google_rss_feed_only"


def test_is_disclosure_noise_title_matches_configured_patterns() -> None:
    patterns = ["net asset value", "total voting rights"]
    assert is_disclosure_noise_title(
        "Amundi US Treasury Bond 1-3Y UCITS ETF Dist: Net Asset Value(s) – Company Announcement",
        patterns,
    )
    assert is_disclosure_noise_title("ACME plc: Total Voting Rights", patterns)
    # Genuine market headlines (incl. PR tagged "Company Announcement") are kept.
    assert not is_disclosure_noise_title(
        "ERock Sees $5.9 Billion Market Cap after IPO Prices", patterns
    )
    assert not is_disclosure_noise_title("Fed holds rates steady", patterns)
    assert not is_disclosure_noise_title(None, patterns)
    # No configured patterns (None or empty) disables filtering entirely.
    assert not is_disclosure_noise_title("Net Asset Value(s)", None)
    assert not is_disclosure_noise_title("Net Asset Value(s)", [])


async def test_normalize_marks_nav_disclosure_boilerplate_as_ignored() -> None:
    source = NewsSource(
        id="src_ft",
        name="Financial Times Google News Markets",
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["global_macro"],
    )
    raw = RawNewsItem(
        id="raw_nav",
        source_id=source.id,
        raw_title=(
            "Amundi US Treasury Bond 1-3Y UCITS ETF Dist: Net Asset Value(s) – Company Announcement"
        ),
        raw_description="Daily NAV disclosure.",
        raw_url="https://example.com/nav",
        raw_published_at="2026-06-02T09:00:00+00:00",
        raw_payload={},
        content_hash="hash_nav",
        fetched_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
    )

    class NormalizeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.execute_count = 0

        async def execute(self, _stmt):
            self.execute_count += 1

            class Result:
                def all(self_inner):
                    if self.execute_count == 1:
                        return [(raw, source)]
                    return []

            return Result()

        def add(self, item: object) -> None:
            self.added.append(item)

    session = NormalizeSession()

    inserted = await normalize_pending_raw_items(
        session, freshness_hours=24 * 365, disclosure_noise_patterns=["net asset value"]
    )

    assert inserted == 1
    assert session.added[0].processing_status == "ignored"


async def test_normalize_marks_second_duplicate_in_same_batch_as_deduped() -> None:
    source = NewsSource(
        id="src_rss",
        name="Market RSS",
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["global_macro"],
    )
    raws = [
        RawNewsItem(
            id="raw_1",
            source_id=source.id,
            raw_title="Fed holds rates",
            raw_description="Policy unchanged.",
            raw_url="https://example.com/news?utm_source=x",
            raw_published_at="2026-06-02T09:00:00+00:00",
            raw_payload={},
            content_hash="hash_1",
            fetched_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
        ),
        RawNewsItem(
            id="raw_2",
            source_id=source.id,
            raw_title="  fed   holds RATES ",
            raw_description="Policy unchanged.",
            raw_url="https://example.com/news",
            raw_published_at="2026-06-02T09:01:00+00:00",
            raw_payload={},
            content_hash="hash_2",
            fetched_at=datetime(2026, 6, 2, 9, 2, tzinfo=UTC),
        ),
    ]

    class NormalizeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.execute_count = 0

        async def execute(self, _stmt):
            self.execute_count += 1

            class Result:
                def all(self_inner):
                    if self.execute_count == 1:
                        return [(raw, source) for raw in raws]
                    return []

            return Result()

        def add(self, item: object) -> None:
            self.added.append(item)

    session = NormalizeSession()

    inserted = await normalize_pending_raw_items(session, freshness_hours=24 * 365)

    assert inserted == 2
    assert [item.processing_status for item in session.added] == ["normalized", "deduped"]


async def test_normalize_marks_same_url_with_different_title_as_deduped() -> None:
    source = NewsSource(
        id="src_rss",
        name="Market RSS",
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["global_macro"],
    )
    raws = [
        RawNewsItem(
            id="raw_1",
            source_id=source.id,
            raw_title="Asian shares skid after Wall St tech selloff",
            raw_description="Markets fall.",
            raw_url="https://apnews.com/article/markets-tech-selloff?utm_source=feed",
            raw_published_at="2026-06-02T09:00:00+00:00",
            raw_payload={},
            content_hash="hash_1",
            fetched_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
        ),
        RawNewsItem(
            id="raw_2",
            source_id=source.id,
            raw_title="Asian shares slide after big tech losses on Wall Street",
            raw_description="Markets fall.",
            raw_url="https://apnews.com/article/markets-tech-selloff",
            raw_published_at="2026-06-02T09:01:00+00:00",
            raw_payload={},
            content_hash="hash_2",
            fetched_at=datetime(2026, 6, 2, 9, 2, tzinfo=UTC),
        ),
    ]

    class NormalizeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.execute_count = 0

        async def execute(self, _stmt):
            self.execute_count += 1

            class Result:
                def all(self_inner):
                    if self.execute_count == 1:
                        return [(raw, source) for raw in raws]
                    return []

            return Result()

        def add(self, item: object) -> None:
            self.added.append(item)

    session = NormalizeSession()

    inserted = await normalize_pending_raw_items(session, freshness_hours=24 * 365)

    assert inserted == 2
    assert [item.processing_status for item in session.added] == ["normalized", "deduped"]


async def test_normalize_marks_existing_active_signature_as_deduped() -> None:
    source = NewsSource(
        id="src_rss",
        name="Market RSS",
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["global_macro"],
    )
    raw = RawNewsItem(
        id="raw_1",
        source_id=source.id,
        raw_title="Oil rises",
        raw_description="Crude climbs.",
        raw_url="https://example.com/oil",
        raw_published_at="2026-06-02T09:00:00+00:00",
        raw_payload={},
        content_hash="hash",
        fetched_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
    )
    existing_row = (
        "rss",
        None,
        content_hash("https://example.com/oil"),
        title_hash("Earlier oil title"),
        content_hash("Earlier oil title Earlier snippet "),
    )

    class NormalizeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.execute_count = 0

        async def execute(self, _stmt):
            self.execute_count += 1

            class Result:
                def all(self_inner):
                    if self.execute_count == 1:
                        return [(raw, source)]
                    return [existing_row]

            return Result()

        def add(self, item: object) -> None:
            self.added.append(item)

    session = NormalizeSession()

    inserted = await normalize_pending_raw_items(session, freshness_hours=24 * 365)

    assert inserted == 1
    assert session.added[0].processing_status == "deduped"


async def test_normalize_marks_existing_active_same_url_as_deduped() -> None:
    source = NewsSource(
        id="src_rss",
        name="Market RSS",
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["global_macro"],
    )
    raw = RawNewsItem(
        id="raw_1",
        source_id=source.id,
        raw_title="Updated AP market wrap",
        raw_description="Markets fall.",
        raw_url="https://apnews.com/article/markets-tech-selloff",
        raw_published_at="2026-06-02T09:00:00+00:00",
        raw_payload={},
        content_hash="hash",
        fetched_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
    )
    existing_row = (
        "rss",
        None,
        content_hash("https://apnews.com/article/markets-tech-selloff"),
        title_hash("Earlier AP title"),
        content_hash("Earlier AP title Earlier snippet "),
    )

    class NormalizeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.execute_count = 0

        async def execute(self, _stmt):
            self.execute_count += 1

            class Result:
                def all(self_inner):
                    if self.execute_count == 1:
                        return [(raw, source)]
                    return [existing_row]

            return Result()

        def add(self, item: object) -> None:
            self.added.append(item)

    session = NormalizeSession()

    inserted = await normalize_pending_raw_items(session, freshness_hours=24 * 365)

    assert inserted == 1
    assert session.added[0].processing_status == "deduped"


async def test_normalize_ignores_existing_deduped_signature_for_active_status() -> None:
    source = NewsSource(
        id="src_rss",
        name="Market RSS",
        source_type="rss",
        source_score=80,
        language="en",
        region="global",
        asset_classes=["global_macro"],
    )
    raw = RawNewsItem(
        id="raw_1",
        source_id=source.id,
        raw_title="Copper slips",
        raw_description="Metals soften.",
        raw_url="https://example.com/copper",
        raw_published_at="2026-06-02T09:00:00+00:00",
        raw_payload={},
        content_hash="hash",
        fetched_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
    )

    class NormalizeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.executed: list[object] = []

        async def execute(self, stmt):
            self.executed.append(stmt)

            class Result:
                def all(self_inner):
                    if len(self.executed) == 1:
                        return [(raw, source)]
                    return []

            return Result()

        def add(self, item: object) -> None:
            self.added.append(item)

    session = NormalizeSession()

    inserted = await normalize_pending_raw_items(session, freshness_hours=24 * 365)

    assert inserted == 1
    assert session.added[0].processing_status == "normalized"
    assert "processing_status" in str(session.executed[1])
