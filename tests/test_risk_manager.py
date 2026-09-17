from decimal import Decimal
from app.domain.models import AccountRiskSnapshot, RiskPolicy, StrategyType, TradeIntent
from app.risk.manager import RiskManager

rm = RiskManager()

def policy(**kw):
    base = dict(
        max_trade_loss_pct=Decimal("0.05"),
        max_portfolio_loss_pct=Decimal("0.20"),
        daily_loss_breaker_pct=Decimal("0.10"),
        max_concurrent_positions=10,
        phase=2,
        require_approval=True,
    )
    base.update(kw)
    return RiskPolicy(**base)

def acct(**kw):
    base = dict(
        equity=Decimal("100000"),
        open_position_max_loss=Decimal("0"),
        realized_pnl_today=Decimal("0"),
        concurrent_positions=0,
        paused_underlyings=frozenset(),
    )
    base.update(kw)
    return AccountRiskSnapshot(**base)

def intent(**kw):
    base = dict(
        strategy=StrategyType.LONG_CALL,
        underlying="SPY",
        contracts=1,
        known_max_loss=Decimal("1000"),
    )
    base.update(kw)
    return TradeIntent(**base)

def test_inside_limits_passes():
    assert rm.evaluate(intent(), acct(), policy()).approved

def test_over_trade_limit_fails():
    assert not rm.evaluate(intent(known_max_loss=Decimal("5000.01")), acct(), policy()).approved

def test_exact_trade_limit_passes():
    assert rm.evaluate(intent(known_max_loss=Decimal("5000")), acct(), policy()).approved

def test_portfolio_cap_fails():
    assert not rm.evaluate(
        intent(known_max_loss=Decimal("3000")),
        acct(open_position_max_loss=Decimal("18000")),
        policy(),
    ).approved

def test_daily_breaker_trips_at_threshold():
    assert not rm.evaluate(
        intent(),
        acct(realized_pnl_today=Decimal("-10000")),
        policy(),
    ).approved

def test_undefined_risk_fails():
    assert not rm.evaluate(intent(is_defined_risk=False), acct(), policy()).approved

def test_covered_call_requires_shares():
    assert not rm.evaluate(
        intent(
            strategy=StrategyType.COVERED_CALL,
            contracts=2,
            known_max_loss=Decimal("1000"),
            has_short_call=True,
            shares_held=199,
        ),
        acct(),
        policy(),
    ).approved

def test_covered_call_with_shares_passes():
    assert rm.evaluate(
        intent(
            strategy=StrategyType.COVERED_CALL,
            contracts=2,
            known_max_loss=Decimal("1000"),
            has_short_call=True,
            shares_held=200,
        ),
        acct(),
        policy(),
    ).approved

def test_paused_underlying_fails():
    assert not rm.evaluate(
        intent(underlying="AAPL"),
        acct(paused_underlyings=frozenset({"AAPL"})),
        policy(),
    ).approved

def test_phase_one_rejects_spread():
    assert not rm.evaluate(
        intent(strategy=StrategyType.BULL_PUT_SPREAD),
        acct(),
        policy(phase=1),
    ).approved

def test_phase_one_allows_csp():
    assert rm.evaluate(
        intent(
            strategy=StrategyType.CASH_SECURED_PUT,
            has_short_put=True,
            known_max_loss=Decimal("4000"),
        ),
        acct(),
        policy(phase=1),
    ).approved
