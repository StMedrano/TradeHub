from app.robinhood.read_service import RobinhoodReadService, _parse_realized_pnl


def test_selects_agentic_account():
    payload = {
        "data": {
            "accounts": [
                {
                    "account_number": "PRIMARY",
                    "agentic_allowed": False,
                },
                {
                    "account_number": "AGENTIC",
                    "agentic_allowed": True,
                },
            ]
        }
    }
    assert RobinhoodReadService._agentic_account_number(payload) == "AGENTIC"


def test_open_order_count():
    payload = {
        "data": {
            "results": [
                {"state": "filled"},
                {"state": "queued"},
                {"state": "confirmed"},
                {"state": "cancelled"},
                {"state": "partially_filled"},
            ]
        }
    }
    assert RobinhoodReadService._open_order_count(payload) == 3



def test_empty_pnl_data_is_authoritative_zero():
    payload = {
        "data": {"results": []},
        "guide": "Realized P&L is grouped by asset class.",
    }
    value, authoritative = _parse_realized_pnl(payload)
    assert value == 0.0
    assert authoritative is True


def test_realized_gain_is_parsed_authoritatively():
    payload = {
        "data": {
            "results": [
                {
                    "date": "2026-09-18",
                    "realized_gain": "-12.34",
                    "trade_count": 1,
                }
            ]
        }
    }
    value, authoritative = _parse_realized_pnl(payload)
    assert value == -12.34
    assert authoritative is True



def test_realized_pnl_sums_asset_class_breakdown():
    payload = {
        "data": {
            "results": [
                {"asset_class": "equity", "realized_gain_loss": "12.50"},
                {"asset_class": "option", "realized_gain_loss": "-5.25"},
            ]
        }
    }
    value, authoritative = _parse_realized_pnl(payload)
    assert value == 7.25
    assert authoritative is True


def test_realized_pnl_prefers_explicit_total_over_components():
    payload = {
        "data": {
            "total_realized_pnl": "20.00",
            "results": [
                {"asset_class": "equity", "realized_gain_loss": "12.50"},
                {"asset_class": "option", "realized_gain_loss": "7.50"},
            ],
        }
    }
    value, authoritative = _parse_realized_pnl(payload)
    assert value == 20.0
    assert authoritative is True
