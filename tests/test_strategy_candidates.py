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



def test_diagnostics_explain_filtered_contract():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=50000,
        equity_positions=[],
    )

    diagnostics = PhaseOneCandidateEngine().diagnose(
        scan(contract(option_type="put", spread_pct=30.0)),
        snapshot,
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].passed is False
    assert any("Spread" in reason for reason in diagnostics[0].reasons)


def test_diagnostics_explain_covered_call_share_requirement():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=50000,
        equity_positions=[],
    )

    diagnostics = PhaseOneCandidateEngine().diagnose(
        scan(contract(option_type="call")),
        snapshot,
    )

    assert diagnostics[0].passed is False
    assert any("100 owned shares" in reason for reason in diagnostics[0].reasons)



def test_bull_put_spread_preview_uses_bounded_max_loss():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=5000,
        equity_positions=[],
    )

    short_put = contract(option_type="put", strike="100")
    short_put["option_id"] = "put-short"
    short_put["bid"] = 2.00
    short_put["ask"] = 2.20
    short_put["mark"] = 2.10

    long_put = contract(option_type="put", strike="95", delta=0.10)
    long_put["option_id"] = "put-long"
    long_put["bid"] = 0.90
    long_put["ask"] = 1.00
    long_put["mark"] = 0.95

    rows = PhaseOneCandidateEngine().generate_bull_put_spreads(
        scan(short_put, long_put),
        snapshot,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.strategy == "bull_put_spread"
    assert row.short_option_id == "put-short"
    assert row.long_option_id == "put-long"
    assert row.spread_width == 5
    assert row.net_credit == 100
    assert row.estimated_max_loss == 400
    assert row.buying_power_sufficient is True


def test_bull_put_spread_preview_skips_non_credit_pair():
    snapshot = RobinhoodSnapshot(
        connection_state="connected",
        buying_power=5000,
        equity_positions=[],
    )

    short_put = contract(option_type="put", strike="100")
    short_put["option_id"] = "put-short"
    short_put["bid"] = 1.00

    long_put = contract(option_type="put", strike="95", delta=0.10)
    long_put["option_id"] = "put-long"
    long_put["ask"] = 1.10

    rows = PhaseOneCandidateEngine().generate_bull_put_spreads(
        scan(short_put, long_put),
        snapshot,
    )

    assert rows == []
