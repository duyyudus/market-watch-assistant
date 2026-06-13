from bot_worker.market_data import (
    MarketMoveDraft,
    MarketSymbolRequest,
    parse_binance_ticker_move,
    parse_coingecko_market_move,
    parse_hyperliquid_market_moves,
    parse_vietnam_quote_moves,
    parse_yahoo_chart_move,
    score_market_move,
)


def test_parse_binance_ticker_move_maps_price_and_volume_change() -> None:
    move = parse_binance_ticker_move(
        {
            "symbol": "BTCUSDT",
            "priceChangePercent": "7.5",
            "volume": "1200",
            "openTime": 1770000000000,
            "closeTime": 1770003600000,
        },
        window="1d",
    )

    assert move.asset_symbol == "BTC"
    assert move.asset_class == "crypto"
    assert move.window == "1d"
    assert move.price_change_pct == 7.5
    assert move.volume_change_pct is None


def test_parse_coingecko_market_move_maps_24h_change() -> None:
    move = parse_coingecko_market_move(
        [{"id": "bitcoin", "price_change_percentage_24h": 6.25}],
        symbol="BTC",
        window="1d",
    )

    assert move.asset_symbol == "BTC"
    assert move.asset_class == "crypto"
    assert move.exchange == "COINGECKO"
    assert move.price_change_pct == 6.25


def test_parse_vietnam_quote_moves_uses_24h_and_weekly_fields() -> None:
    moves = parse_vietnam_quote_moves(
        {
            "stocks": [
                {
                    "ticker": "VIC",
                    "exchange": "HOSE",
                    "price_change_24h": 0.79,
                    "price_change_1w": -3.07,
                }
            ]
        }
    )

    assert moves == [
        MarketMoveDraft(
            asset_symbol="VIC",
            asset_class="equity",
            exchange="HOSE",
            timestamp=moves[0].timestamp,
            window="1d",
            price_change_pct=0.79,
        ),
        MarketMoveDraft(
            asset_symbol="VIC",
            asset_class="equity",
            exchange="HOSE",
            timestamp=moves[1].timestamp,
            window="1w",
            price_change_pct=-3.07,
        ),
    ]


def test_parse_yahoo_chart_move_uses_first_and_last_close() -> None:
    move = parse_yahoo_chart_move(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "SPY", "exchangeName": "PCX"},
                        "timestamp": [1779111000, 1779456600],
                        "indicators": {
                            "quote": [
                                {
                                    "close": [100.0, 105.0],
                                    "volume": [1000, 1300],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        },
        symbol="SPY",
        asset_class="equity",
        window="1d",
    )

    assert move.asset_symbol == "SPY"
    assert move.exchange == "PCX"
    assert move.price_change_pct == 5.0
    assert move.volume_change_pct == 30.0


def test_parse_hyperliquid_market_moves_maps_true_24h_change() -> None:
    moves, skipped, unavailable = parse_hyperliquid_market_moves(
        [
            {
                "universe": [
                    {"name": "xyz:SP500"},
                    {"name": "xyz:GOLD"},
                ]
            },
            [
                {
                    "markPx": "105.0",
                    "prevDayPx": "100.0",
                    "dayNtlVlm": "250000.0",
                },
                {
                    "markPx": "2040.0",
                    "prevDayPx": "2000.0",
                    "dayNtlVlm": "500000.0",
                },
            ],
        ],
        requests_by_coin={
            "xyz:SP500": MarketSymbolRequest(symbol="SPX", asset_class="index", region="us"),
            "xyz:GOLD": MarketSymbolRequest(
                symbol="GOLD",
                asset_class="commodity",
                region="global",
            ),
        },
        window="1d",
        min_day_notional_volume=100000,
    )

    assert skipped == {}
    assert unavailable == {}
    assert moves[0].asset_symbol == "SPX"
    assert moves[0].asset_class == "index"
    assert moves[0].exchange == "HYPERLIQUID"
    assert moves[0].price_change_pct == 5.0
    assert moves[1].asset_symbol == "GOLD"
    assert moves[1].asset_class == "commodity"
    assert moves[1].price_change_pct == 2.0


def test_parse_hyperliquid_market_moves_skips_delisted_and_thin_markets() -> None:
    moves, skipped, unavailable = parse_hyperliquid_market_moves(
        [
            {
                "universe": [
                    {"name": "xyz:DXY", "isDelisted": True},
                    {"name": "xyz:VIX"},
                ]
            },
            [
                {
                    "markPx": "97.15",
                    "prevDayPx": "97.15",
                    "dayNtlVlm": "0.0",
                },
                {
                    "markPx": "20.0",
                    "prevDayPx": "20.0",
                    "dayNtlVlm": "0.0",
                },
            ],
        ],
        requests_by_coin={
            "xyz:DXY": MarketSymbolRequest(symbol="DXY", asset_class="fx", region="global"),
            "xyz:VIX": MarketSymbolRequest(symbol="VIX", asset_class="index", region="us"),
        },
        window="1d",
        min_day_notional_volume=100000,
    )

    assert moves == []
    # Delisted is a data problem (degrades); the thin market is a deliberate quality skip.
    assert unavailable["DXY"] == "Hyperliquid instrument xyz:DXY is delisted"
    assert "DXY" not in skipped
    assert skipped["VIX"] == "Hyperliquid instrument xyz:VIX dayNtlVlm 0.0 below 100000"
    assert "VIX" not in unavailable


def test_score_market_move_maps_material_moves_to_alert_signal() -> None:
    assert score_market_move(price_change_pct=0.5, volume_change_pct=None) < 70
    assert score_market_move(price_change_pct=5.0, volume_change_pct=None) >= 70
    assert score_market_move(price_change_pct=2.5, volume_change_pct=80.0) >= 70


def test_score_market_move_preserves_bonus_room_above_price_component() -> None:
    plain_large_move = score_market_move(price_change_pct=8.0, volume_change_pct=None)
    anomalous_smaller_move = score_market_move(
        price_change_pct=4.0,
        volume_change_pct=80.0,
        z_score=2.5,
    )

    assert plain_large_move == 70
    assert anomalous_smaller_move > plain_large_move
