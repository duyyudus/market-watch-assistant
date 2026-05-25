from bot_worker.watchlist import WatchlistEntry, match_watchlist


def test_match_watchlist_uses_symbol_name_and_aliases() -> None:
    entries = [
        WatchlistEntry(symbol="BTC", name="Bitcoin", tier="A", aliases=["digital gold"]),
        WatchlistEntry(symbol="VIC", name="Vingroup", tier="A", aliases=["VinGroup"]),
    ]

    matches = match_watchlist("Bitcoin jumps while VinGroup shares lag", entries)

    assert [match.symbol for match in matches] == ["BTC", "VIC"]
