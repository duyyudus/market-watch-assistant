from __future__ import annotations

from dataclasses import dataclass

# Hyperliquid encodes non-native instruments with this prefix (e.g. "XYZ:NVDA").
HYPERLIQUID_SYMBOL_PREFIX = "XYZ:"
# Asset classes routed to the global (Hyperliquid) provider.
GLOBAL_ASSET_CLASSES = {"equity", "us_equity", "etf", "index", "commodity", "fx", "rates"}


@dataclass(frozen=True)
class MarketResolvedSymbolRequest:
    symbol: str
    asset_class: str | None
    region: str | None
    provider: str | None
    provider_symbol: str | None
    fallback_provider: str | None = None
    status: str = "resolved"
    reason: str | None = None
