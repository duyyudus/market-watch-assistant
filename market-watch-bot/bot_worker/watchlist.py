from __future__ import annotations

import re
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


def _term_matches(term: str, haystack: str) -> bool:
    """Whole-token match for ``term`` within an already-casefolded ``haystack``.

    Uses non-word-character lookarounds rather than naive ``in`` containment so a
    symbol/name cannot match as a substring of a larger word (e.g. "BID" inside
    "bidders" or "GAS" inside "gas-powered"). Lookarounds (not ``\\b``) are used so
    terms with internal punctuation such as "9988.HK" or "VN-Index" still match.
    """
    term = term.casefold().strip()
    if not term:
        return False
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", haystack) is not None


def match_watchlist(text: str, entries: list[WatchlistEntry]) -> list[WatchlistEntry]:
    haystack = text.casefold()
    matches: list[WatchlistEntry] = []
    for entry in entries:
        if not entry.enabled:
            continue
        terms = [entry.name, *entry.aliases]
        if entry.symbol:
            terms.append(entry.symbol)
        if any(_term_matches(term, haystack) for term in terms):
            matches.append(entry)
    return matches
