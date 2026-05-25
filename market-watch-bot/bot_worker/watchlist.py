from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WatchlistEntry:
    name: str
    tier: str = "D"
    symbol: str | None = None
    entity_type: str = "macro_theme"
    region: str | None = None
    asset_class: str | None = None
    aliases: list[str] = field(default_factory=list)
    enabled: bool = True


def match_watchlist(text: str, entries: list[WatchlistEntry]) -> list[WatchlistEntry]:
    haystack = f" {text.casefold()} "
    matches: list[WatchlistEntry] = []
    for entry in entries:
        if not entry.enabled:
            continue
        terms = [entry.name, *entry.aliases]
        if entry.symbol:
            terms.append(entry.symbol)
        if any(f" {term.casefold()} " in haystack or term.casefold() in haystack for term in terms):
            matches.append(entry)
    return matches
