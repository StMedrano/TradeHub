from decimal import Decimal
import pytest
from fastapi import HTTPException

from app.api.routes import _account_csp_capacity, _strategy_account_snapshot, _watchlist_symbols
from app.config import RiskCapitalMode, settings
from app.domain.models import AccountRiskSnapshot, RiskPolicy


def test_watchlist_symbols_normalizes_and_deduplicates(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 5)

    assert _watchlist_symbols("spy, SPY ,qqq") == ["SPY", "QQQ"]


def test_watchlist_symbols_uses_configured_default(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist", "abc,xyz")
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 5)

    assert _watchlist_symbols(None) == ["ABC", "XYZ"]


def test_watchlist_symbols_rejects_invalid_symbol(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 5)

    with pytest.raises(HTTPException) as exc:
        _watchlist_symbols("ABC,$BAD")

    assert exc.value.status_code == 400


def test_watchlist_symbols_enforces_scan_cap(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 2)

    with pytest.raises(HTTPException) as exc:
        _watchlist_symbols("AAA,BBB,CCC")

    assert exc.value.status_code == 400



def _risk_policy():
    return RiskPolicy(
        max_trade_loss_pct=Decimal("0.05"),
        max_portfolio_loss_pct=Decimal("0.20"),
        daily_loss_breaker_pct=Decimal("0.10"),
        max_concurrent_positions=1,
        phase=0,
        require_approval=True,
    )


def _risk_snapshot(**overrides):
    values = {
        "equity": Decimal("100000"),
        "open_position_max_loss": Decimal("0"),
        "realized_pnl_today": Decimal("0"),
        "concurrent_positions": 0,
        "paused_underlyings": frozenset(),
    }
    values.update(overrides)
    return AccountRiskSnapshot(**values)


def test_csp_capacity_uses_buying_power_when_it_is_binding():
    result = _account_csp_capacity(
        _risk_snapshot(),
        buying_power=3000,
        policy=_risk_policy(),
    )

    assert result["binding_constraint"] == "buying_power"
    assert result["max_csp_collateral"] == "3000"
    assert result["approximate_max_csp_strike_before_premium"] == "30.00"


def test_csp_capacity_uses_per_trade_limit_when_it_is_binding():
    result = _account_csp_capacity(
        _risk_snapshot(),
        buying_power=10000,
        policy=_risk_policy(),
    )

    assert result["binding_constraint"] == "per_trade_risk"
    assert result["max_csp_collateral"] == "5000.00"
    assert result["approximate_max_csp_strike_before_premium"] == "50.00"


def test_csp_capacity_uses_remaining_portfolio_limit_when_it_is_binding():
    result = _account_csp_capacity(
        _risk_snapshot(open_position_max_loss=Decimal("19000")),
        buying_power=10000,
        policy=_risk_policy(),
    )

    assert result["binding_constraint"] == "remaining_portfolio_risk"
    assert result["max_csp_collateral"] == "1000.00"
    assert result["approximate_max_csp_strike_before_premium"] == "10.00"



def test_simulation_strategy_snapshot_uses_virtual_remaining_capital(monkeypatch):
    monkeypatch.setattr(settings, "risk_capital_mode", RiskCapitalMode.SIMULATION)
    monkeypatch.setattr(settings, "simulation_capital", 10000.0)

    snapshot = _strategy_account_snapshot(
        _risk_snapshot(open_position_max_loss=Decimal("400")),
    )

    assert snapshot.equity == 10000.0
    assert snapshot.buying_power == 9600.0
    assert snapshot.cash == 9600.0
    assert snapshot.equity_positions == []
    assert snapshot.open_option_positions == 0
    assert snapshot.realized_pnl_authoritative is True
