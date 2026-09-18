from datetime import date, timedelta

from app.robinhood.market_data import OptionScanResult
from app.robinhood.read_service import RobinhoodSnapshot
from app.strategy.candidates import PhaseOneCandidateEngine


def contract(
    *,
    option_type: str,
    strike: str = "100",
    delta: float = 0.25,
    spread_pct: float = 4.0,
    open_interest: int = 500,
    volume: int = 100,
):
    expiry = (date.today() + timedelta(days=30)).isoformat()
    return {
        "option_id": f"{option_type}-1",
        "symbol": "ABC",
        "expiration_date": expiry,
        "strike_price": strike,
        "option_type": option_type,
        "trade_value_multiplier": "100",
        "bid": 2.0,
        "ask": 2.2,
        "mark": 2.1,
        "spread_pct": spread_pct,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility": 0.30,
        "delta": delta if option_type == "call" else -abs(delta),
        "gamma": 0.02,
        "theta": -0.03,
        "vega": 0.10,
        "rho": 0.01,
    }


def scan(*rows):
    return OptionScanResult(
        symbol="ABC",
        scanned_at="2026-09-18T12:00:00+00:00",
        chain_count=1,
        instrument_count=len(rows),
        quote_count=len(rows),
        contracts=list(rows),
    )


def test_prefers_covered_calls_when_shares_are_owned():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=50000,
        equity_positions=[{"symbol": "ABC", "quantity": "100"}],
    )

    rows = PhaseOneCandidateEngine().generate(
        scan(contract(option_type="call"), contract(option_type="put")),
        snapshot,
    )

    assert rows
    assert all(row.strategy == "covered_call" for row in rows)
    assert rows[0].shares_held == 100


def test_csp_candidate_uses_collateral_and_buying_power():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=15000,
        equity_positions=[],
    )

    rows = PhaseOneCandidateEngine().generate(
        scan(contract(option_type="put", strike="100")),
        snapshot,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.strategy == "cash_secured_put"
    assert row.estimated_credit == 200
    assert row.estimated_collateral == 9800
    assert row.buying_power_sufficient is True
    assert row.risk_status == "portfolio_risk_pending"


def test_csp_rejects_when_buying_power_is_insufficient():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=5000,
        equity_positions=[],
    )

    rows = PhaseOneCandidateEngine().generate(
        scan(contract(option_type="put", strike="100")),
        snapshot,
    )

    assert len(rows) == 1
    assert rows[0].buying_power_sufficient is False
    assert rows[0].risk_status == "buying_power_reject"


def test_liquidity_filter_removes_wide_spread():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=50000,
        equity_positions=[],
    )

    rows = PhaseOneCandidateEngine().generate(
        scan(contract(option_type="put", spread_pct=30.0)),
        snapshot,
    )

    assert rows == []
