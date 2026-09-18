from app.robinhood.market_data import (
    RobinhoodMarketDataService,
    _centered_strikes,
    _equity_quote_price,
    _infer_strike_step,
)


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



def test_normalize_contracts_unwraps_quote_wrapper():
    instruments = {
        "data": {
            "instruments": [
                {
                    "id": "opt-1",
                    "chain_symbol": "SPY",
                    "expiration_date": "2026-10-16",
                    "strike_price": "500",
                    "type": "put",
                    "trade_value_multiplier": "100",
                }
            ]
        }
    }
    quotes = {
        "data": {
            "results": [
                {
                    "quote": {
                        "instrument_id": "opt-1",
                        "bid_price": "4.80",
                        "ask_price": "5.20",
                        "implied_volatility": "0.22",
                        "greeks": {
                            "delta": "-0.24",
                            "theta": "-0.05"
                        },
                        "open_interest": 850,
                        "volume": 120,
                    }
                }
            ]
        }
    }

    rows = RobinhoodMarketDataService._normalize_contracts(instruments, quotes)
    assert len(rows) == 1
    assert rows[0]["bid"] == 4.8
    assert rows[0]["ask"] == 5.2
    assert rows[0]["delta"] == -0.24
    assert rows[0]["open_interest"] == 850
    assert rows[0]["volume"] == 120


def test_chain_and_instrument_arrays_are_counted_directly():
    from app.robinhood.normalize import extract_records

    chains = {"data": {"chains": [{"id": "chain-1", "symbol": "SPY"}]}}
    instruments = {
        "data": {
            "instruments": [
                {"id": "a", "chain_symbol": "SPY"},
                {"id": "b", "chain_symbol": "SPY"},
            ]
        }
    }

    assert len(extract_records(chains)) == 1
    assert len(extract_records(instruments)) == 2



def test_equity_quote_price_unwraps_live_shape():
    payload = {
        "data": {
            "results": [
                {
                    "quote": {
                        "symbol": "SPY",
                        "last_trade_price": "763.42",
                        "bid_price": "763.40",
                        "ask_price": "763.44",
                    }
                }
            ]
        }
    }
    assert _equity_quote_price(payload) == 763.42


def test_infer_strike_step_and_center_search_near_spot():
    payload = {
        "data": {
            "instruments": [
                {"strike_price": "490.0000"},
                {"strike_price": "495.0000"},
                {"strike_price": "500.0000"},
            ]
        }
    }
    step = _infer_strike_step(payload)
    assert step == 5.0

    strikes = [float(value) for value in _centered_strikes(763.42, step)]
    assert len(strikes) == 13
    assert min(strikes) < 700
    assert max(strikes) > 825
    assert min(abs(value - 763.42) for value in strikes) <= 5.0
