from bot_worker.watchlist import WatchlistEntry, match_watchlist


def test_match_watchlist_uses_symbol_name_and_aliases() -> None:
    entries = [
        WatchlistEntry(symbol="BTC", name="Bitcoin", tier="A", aliases=["digital gold"]),
        WatchlistEntry(symbol="VIC", name="Vingroup", tier="A", aliases=["VinGroup"]),
    ]

    matches = match_watchlist("Bitcoin jumps while VinGroup shares lag", entries)

    assert [match.symbol for match in matches] == ["BTC", "VIC"]


def test_match_watchlist_ignores_substring_collisions() -> None:
    entries = [
        WatchlistEntry(symbol="BID", name="BIDV", tier="A"),
        WatchlistEntry(symbol="GAS", name="PV Gas", tier="A"),
    ]

    matches = match_watchlist("oil and gas lease auction bidders weigh in", entries)

    # "BID" must not match "bidders". "GAS" as a standalone word in
    # "oil and gas" is a legitimate whole-token hit.
    assert [match.symbol for match in matches] == ["GAS"]


def test_match_watchlist_handles_punctuated_terms() -> None:
    entries = [
        WatchlistEntry(symbol="9988.HK", name="Alibaba", tier="A"),
        WatchlistEntry(symbol="VNINDEX", name="VN-Index", tier="A", aliases=["VN-Index"]),
    ]

    matches = match_watchlist("9988.HK climbs as VN-Index rebounds", entries)

    assert {match.symbol for match in matches} == {"9988.HK", "VNINDEX"}
