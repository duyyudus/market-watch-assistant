from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class MarketMoveDraft:
    asset_symbol: str
    asset_class: str
    exchange: str | None
    timestamp: datetime
    window: str
    price_change_pct: float
    volume_change_pct: float | None = None
    value_traded_change_pct: float | None = None
    z_score: float | None = None


def _ms_to_datetime(value: object | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def parse_binance_ticker_move(payload: dict[str, object], *, window: str) -> MarketMoveDraft:
    return MarketMoveDraft(
        asset_symbol=str(payload["symbol"]).upper(),
        asset_class="crypto",
        exchange="BINANCE",
        timestamp=_ms_to_datetime(payload.get("closeTime")),
        window=window,
        price_change_pct=float(payload.get("priceChangePercent", 0)),
    )


def parse_coingecko_market_move(
    payload: list[dict[str, object]], *, symbol: str, window: str
) -> MarketMoveDraft:
    if not payload:
        raise ValueError("CoinGecko response did not include market data")
    item = payload[0]
    return MarketMoveDraft(
        asset_symbol=symbol.upper(),
        asset_class="crypto",
        exchange="COINGECKO",
        timestamp=datetime.now(UTC),
        window=window,
        price_change_pct=float(item.get("price_change_percentage_24h") or 0),
        volume_change_pct=None,
    )


def parse_vietnam_quote_moves(payload: dict[str, object]) -> list[MarketMoveDraft]:
    moves: list[MarketMoveDraft] = []
    for item in payload.get("stocks", []):
        if not isinstance(item, dict):
            continue
        symbol = str(item["ticker"]).upper()
        exchange = str(item["exchange"]) if item.get("exchange") else None
        now = datetime.now(UTC)
        if item.get("price_change_24h") is not None:
            moves.append(
                MarketMoveDraft(
                    asset_symbol=symbol,
                    asset_class="equity",
                    exchange=exchange,
                    timestamp=now,
                    window="1d",
                    price_change_pct=float(item["price_change_24h"]),
                )
            )
        if item.get("price_change_1w") is not None:
            moves.append(
                MarketMoveDraft(
                    asset_symbol=symbol,
                    asset_class="equity",
                    exchange=exchange,
                    timestamp=now,
                    window="1w",
                    price_change_pct=float(item["price_change_1w"]),
                )
            )
    return moves


def parse_yahoo_chart_move(
    payload: dict[str, object], *, symbol: str, asset_class: str, window: str
) -> MarketMoveDraft:
    chart = payload.get("chart")
    if not isinstance(chart, dict) or chart.get("error"):
        raise ValueError("Yahoo chart response contained an error")
    result = chart.get("result")
    if not isinstance(result, list) or not result:
        raise ValueError("Yahoo chart response did not include results")
    item = result[0]
    if not isinstance(item, dict):
        raise ValueError("Yahoo chart result is not an object")
    timestamps = item.get("timestamp")
    indicators = item.get("indicators")
    if not isinstance(timestamps, list) or len(timestamps) < 2 or not isinstance(indicators, dict):
        raise ValueError("Yahoo chart response missing time series data")
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
        raise ValueError("Yahoo chart response missing quote data")
    quote = quotes[0]
    closes = [value for value in quote.get("close", []) if value is not None]
    volumes = [value for value in quote.get("volume", []) if value is not None]
    if len(closes) < 2:
        raise ValueError("Yahoo chart response must contain at least two closes")
    first_close = float(closes[0])
    last_close = float(closes[-1])
    first_volume = float(volumes[0]) if volumes else 0
    last_volume = float(volumes[-1]) if volumes else 0
    volume_change = None
    if first_volume:
        volume_change = round(((last_volume - first_volume) / first_volume) * 100, 2)
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return MarketMoveDraft(
        asset_symbol=symbol.upper(),
        asset_class=asset_class,
        exchange=str(meta.get("exchangeName")) if meta.get("exchangeName") else "YAHOO",
        timestamp=datetime.fromtimestamp(int(timestamps[-1]), tz=UTC),
        window=window,
        price_change_pct=round(((last_close - first_close) / first_close) * 100, 2),
        volume_change_pct=volume_change,
    )


def score_market_move(
    *, price_change_pct: float, volume_change_pct: float | None, z_score: float | None = None
) -> int:
    absolute_move = abs(price_change_pct)
    score = min(100, round(absolute_move * 14))
    if volume_change_pct is not None and volume_change_pct >= 50:
        score += 35
    if z_score is not None and z_score >= 2:
        score += 20
    return min(100, score)
