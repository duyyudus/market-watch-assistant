from bot_worker.market_data import (
    MarketMoveDraft,
    parse_binance_ticker_move,
    parse_coingecko_market_move,
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

    assert move.asset_symbol == "BTCUSDT"
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


def test_score_market_move_maps_material_moves_to_alert_signal() -> None:
    assert score_market_move(price_change_pct=0.5, volume_change_pct=None) < 70
    assert score_market_move(price_change_pct=5.0, volume_change_pct=None) >= 70
    assert score_market_move(price_change_pct=2.5, volume_change_pct=80.0) >= 70
