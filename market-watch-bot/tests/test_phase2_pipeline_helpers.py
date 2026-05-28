from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from bot_worker.digest import digest_window_for_date
from bot_worker.services import (
    digest_time_in_window,
    format_report_time_range,
    is_rss_item_fresh,
    select_digest_headline,
    select_report_time_range,
)


def test_rss_freshness_cutoff_rejects_old_published_items() -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)

    assert is_rss_item_fresh(
        published_at=now - timedelta(hours=71),
        fetched_at=now,
        now=now,
        freshness_hours=72,
    )
    assert not is_rss_item_fresh(
        published_at=now - timedelta(hours=73),
        fetched_at=now,
        now=now,
        freshness_hours=72,
    )


def test_rss_freshness_uses_fetched_at_when_published_missing() -> None:
    now = datetime(2026, 5, 25, 12, tzinfo=UTC)

    assert is_rss_item_fresh(
        published_at=None,
        fetched_at=now - timedelta(hours=1),
        now=now,
        freshness_hours=72,
    )


def test_digest_window_for_date_uses_local_calendar_day() -> None:
    start, end = digest_window_for_date("2026-05-25", ZoneInfo("Asia/Ho_Chi_Minh"))

    assert start.isoformat() == "2026-05-24T17:00:00+00:00"
    assert end.isoformat() == "2026-05-25T17:00:00+00:00"


def test_digest_time_in_window_prefers_published_at_over_cluster_created_at() -> None:
    start = datetime(2026, 5, 24, 17, tzinfo=UTC)
    end = datetime(2026, 5, 25, 17, tzinfo=UTC)

    assert not digest_time_in_window(
        published_at=datetime(2026, 5, 21, 9, 37, tzinfo=UTC),
        fetched_at=datetime(2026, 5, 25, 4, 10, tzinfo=UTC),
        created_at=datetime(2026, 5, 25, 4, 10, tzinfo=UTC),
        since=start,
        until=end,
    )


def test_select_digest_headline_prefers_latest_in_window_member() -> None:
    start = datetime(2026, 5, 24, 17, tzinfo=UTC)
    end = datetime(2026, 5, 25, 17, tzinfo=UTC)

    headline = select_digest_headline(
        canonical_headline="Top cổ phiếu đáng chú ý đầu phiên 22/05",
        members=[
            (
                "Top cổ phiếu đáng chú ý đầu phiên 22/05",
                datetime(2026, 5, 22, 1, tzinfo=UTC),
                datetime(2026, 5, 25, 4, tzinfo=UTC),
                datetime(2026, 5, 25, 4, tzinfo=UTC),
            ),
            (
                "Top cổ phiếu đáng chú ý đầu tuần 25/05",
                datetime(2026, 5, 25, 1, tzinfo=UTC),
                datetime(2026, 5, 25, 4, tzinfo=UTC),
                datetime(2026, 5, 25, 4, tzinfo=UTC),
            ),
        ],
        since=start,
        until=end,
    )

    assert headline == "Top cổ phiếu đáng chú ý đầu tuần 25/05"


def test_select_digest_headline_uses_fetched_at_when_published_missing() -> None:
    start = datetime(2026, 5, 24, 17, tzinfo=UTC)
    end = datetime(2026, 5, 25, 17, tzinfo=UTC)

    headline = select_digest_headline(
        canonical_headline="Older canonical headline",
        members=[
            (
                "Fresh undated feed item",
                None,
                datetime(2026, 5, 25, 4, tzinfo=UTC),
                datetime(2026, 5, 25, 4, tzinfo=UTC),
            )
        ],
        since=start,
        until=end,
    )

    assert headline == "Fresh undated feed item"


def test_select_report_time_range_uses_earliest_and_latest_effective_member_time() -> None:
    reported_at, latest_report_at = select_report_time_range(
        [
            (
                datetime(2026, 5, 26, 9, 5, tzinfo=UTC),
                datetime(2026, 5, 28, 1, tzinfo=UTC),
                datetime(2026, 5, 28, 1, tzinfo=UTC),
            ),
            (
                datetime(2026, 5, 28, 14, 10, tzinfo=UTC),
                datetime(2026, 5, 28, 14, 12, tzinfo=UTC),
                datetime(2026, 5, 28, 14, 12, tzinfo=UTC),
            ),
        ]
    )

    assert reported_at == datetime(2026, 5, 26, 9, 5, tzinfo=UTC)
    assert latest_report_at == datetime(2026, 5, 28, 14, 10, tzinfo=UTC)


def test_select_report_time_range_falls_back_to_fetched_then_created_at() -> None:
    reported_at, latest_report_at = select_report_time_range(
        [
            (
                None,
                datetime(2026, 5, 27, 10, tzinfo=UTC),
                datetime(2026, 5, 27, 9, tzinfo=UTC),
            ),
            (
                None,
                None,
                datetime(2026, 5, 26, 8, tzinfo=UTC),
            ),
        ]
    )

    assert reported_at == datetime(2026, 5, 26, 8, tzinfo=UTC)
    assert latest_report_at == datetime(2026, 5, 27, 10, tzinfo=UTC)


def test_format_report_time_range_collapses_single_timestamp() -> None:
    value = datetime(2026, 5, 28, 9, 5, tzinfo=UTC)

    assert format_report_time_range((value, value)) == "reported May 28 09:05"


def test_format_report_time_range_displays_range() -> None:
    assert (
        format_report_time_range(
            (
                datetime(2026, 5, 26, 9, 5, tzinfo=UTC),
                datetime(2026, 5, 28, 14, 10, tzinfo=UTC),
            )
        )
        == "reports May 26 09:05 - May 28 14:10"
    )
