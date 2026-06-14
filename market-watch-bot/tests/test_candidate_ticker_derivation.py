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


class _EntitySession:
    """Session stub returning fixed LLM-extracted entities for every lookup."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    async def scalars(self, _stmt):
        return _ScalarRows(self._rows)


class _Entity:
    def __init__(self, normalized_name: str, ticker: str | None = None) -> None:
        self.normalized_name = normalized_name
        self.ticker = ticker


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


@pytest.mark.asyncio
async def test_watchlist_resolves_ticker_from_recognized_entity_name() -> None:
    # The LLM recognized the entity but did not attach a ticker; the watchlist
    # must resolve it from the entity name so the cluster is not left ticker-less.
    watch_entries = [
        WatchlistEntry(
            symbol="VIC",
            name="Vingroup",
            tier="S",
            region="vietnam",
            aliases=["Tap doan Vingroup"],
        ),
    ]
    session = _EntitySession([_Entity("Tập đoàn Vingroup"), _Entity("VinFast")])

    candidate = await event_services._candidate_from_item(
        session, _news_item(), watch_entries
    )

    assert candidate.tickers == ["VIC"]


@pytest.mark.asyncio
async def test_watchlist_ticker_merges_with_llm_ticker() -> None:
    watch_entries = [
        WatchlistEntry(symbol="VIC", name="Vingroup", tier="S", region="vietnam"),
    ]
    session = _EntitySession([_Entity("Vingroup"), _Entity("Nvidia", ticker="NVDA")])

    candidate = await event_services._candidate_from_item(
        session, _news_item(), watch_entries
    )

    assert candidate.tickers == ["NVDA", "VIC"]
