from app.robinhood.read_service import (
    RobinhoodReadService,
    _load_persisted_account_number,
    _persist_account_number,
    _parse_realized_pnl,
    _parse_trade_history_daily_pnl,
)


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



def test_trade_history_fallback_sums_scoped_rows():
    payload = {
        "data": {
            "results": [
                {"realized_pnl": "4.50", "closed_at": "2026-09-18T14:00:00Z"},
                {"realized_pnl": "-1.25", "closed_at": "2026-09-18T15:00:00Z"},
            ]
        }
    }
    value, authoritative = _parse_trade_history_daily_pnl(
        payload,
        scoped_to_day=True,
    )
    assert value == 3.25
    assert authoritative is True


def test_trade_history_empty_scoped_day_is_zero():
    value, authoritative = _parse_trade_history_daily_pnl(
        {"data": {"results": []}},
        scoped_to_day=True,
    )
    assert value == 0.0
    assert authoritative is True


def test_trade_history_unscoped_payload_does_not_unlock_risk():
    payload = {
        "data": {
            "results": [
                {"realized_pnl": "4.50", "closed_at": "2026-09-18T14:00:00Z"}
            ]
        }
    }
    value, authoritative = _parse_trade_history_daily_pnl(
        payload,
        scoped_to_day=False,
    )
    assert value is None
    assert authoritative is False



def test_total_returns_is_authoritative():
    payload = {
        "account_number": "redacted",
        "window": "day",
        "data_points": [],
        "total_returns": "-7.50",
    }
    value, authoritative = _parse_realized_pnl(payload)
    assert value == -7.5
    assert authoritative is True


def test_labeled_plain_text_pnl_is_authoritative():
    payload = "Window: day\nTotal Returns: $12.34\nTrades: 2"
    value, authoritative = _parse_realized_pnl(payload)
    assert value == 12.34
    assert authoritative is True


def test_labeled_plain_text_parentheses_are_negative():
    payload = "Total Realized P&L: ($8.25)"
    value, authoritative = _parse_realized_pnl(payload)
    assert value == -8.25
    assert authoritative is True



def test_persisted_agentic_account_round_trip(tmp_path, monkeypatch):
    from app.robinhood import read_service as module

    path = tmp_path / "robinhood_account.json"
    monkeypatch.setattr(module.settings, "robinhood_account_store", str(path))

    _persist_account_number("AGENTIC123")

    assert _load_persisted_account_number() == "AGENTIC123"
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_markdown_table_total_returns_is_authoritative():
    payload = "| Metric | Value |\n|---|---:|\n| Total Returns | ($5.50) |"
    value, authoritative = _parse_realized_pnl(payload)
    assert value == -5.5
    assert authoritative is True



def test_explicit_no_realized_pnl_is_authoritative_zero():
    value, authoritative = _parse_realized_pnl(
        "No realized P&L data found for this period."
    )
    assert value == 0.0
    assert authoritative is True


def test_scoped_trade_history_no_trades_is_authoritative_zero():
    value, authoritative = _parse_trade_history_daily_pnl(
        "No trades found for the selected period.",
        scoped_to_day=True,
    )
    assert value == 0.0
    assert authoritative is True
