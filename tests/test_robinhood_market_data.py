from app.robinhood.market_data import RobinhoodMarketDataService


def test_normalize_contracts_computes_spread_and_greeks():
    instruments = {
        "results": [
            {
                "id": "opt-1",
                "chain_symbol": "SPY",
                "expiration_date": "2026-10-16",
                "strike_price": "500",
                "type": "call",
                "trade_value_multiplier": "100",
            }
        ]
    }
    quotes = {
        "results": [
            {
                "option_id": "opt-1",
                "bid_price": "4.90",
                "ask_price": "5.10",
                "implied_volatility": "0.25",
                "delta": "0.51",
                "theta": "-0.04",
                "open_interest": 1200,
                "volume": 300,
            }
        ]
    }

    rows = RobinhoodMarketDataService._normalize_contracts(instruments, quotes)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "SPY"
    assert row["spread_pct"] == 4.0
    assert row["implied_volatility"] == 0.25
    assert row["delta"] == 0.51
    assert row["theta"] == -0.04


def test_option_ids_accepts_common_robinhood_id_shapes():
    payload = {
        "results": [
            {"id": "a"},
            {"option_id": "b"},
            {"instrument_id": "c"},
        ]
    }

    assert RobinhoodMarketDataService._option_ids(payload) == ["a", "b", "c"]
