from datetime import UTC, datetime

import pytest

import bot_worker.services.events as event_services
from bot_worker.db.models import NormalizedNewsItem
from bot_worker.watchlist import WatchlistEntry


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _EmptySession:
    """Session stub whose entity/ticker lookups return nothing."""

    async def scalars(self, _stmt):
        return _ScalarRows([])


def _news_item() -> NormalizedNewsItem:
    return NormalizedNewsItem(
        id="news_1",
        title="Nvidia CEO shrugs off tech rout as oil and gas lease auction bidders weigh in",
        source_score=80,
        region="global",
        asset_classes=["global_macro"],
        processing_status="normalized",
        created_at=datetime(2026, 6, 12, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_no_llm_tickers_means_no_tickers() -> None:
    # Vietnamese symbols whose codes are substrings of common English words:
    # "BID" in "bidders", "GAS" in "oil and gas".
    watch_entries = [
        WatchlistEntry(symbol="BID", name="BIDV", tier="A", region="vietnam"),
        WatchlistEntry(symbol="GAS", name="PV Gas", tier="A", region="vietnam"),
    ]

    candidate = await event_services._candidate_from_item(
        _EmptySession(), _news_item(), watch_entries
    )

    # With no LLM-extracted tickers, the watchlist must not inject substring matches.
    assert candidate.tickers == []
