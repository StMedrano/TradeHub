from decimal import Decimal
from app.config import TradingMode
from app.execution.gates import ExecutionGate
from app.execution.multileg import LegExecution, LegState, MultiLegPlan
from app.execution.pricing import OptionQuote, price_walk

def test_dry_run_blocks_orders():
    allowed, _ = ExecutionGate(
        mode=TradingMode.DRY_RUN,
        phase=1,
        require_approval=True,
    ).may_place_order(approved=True)
    assert not allowed

def test_live_requires_approval():
    allowed, _ = ExecutionGate(
        mode=TradingMode.LIVE,
        phase=1,
        require_approval=True,
    ).may_place_order(approved=False)
    assert not allowed

def test_live_approved_phase_one_passes_gate():
    allowed, _ = ExecutionGate(
        mode=TradingMode.LIVE,
        phase=1,
        require_approval=True,
    ).may_place_order(approved=True)
    assert allowed

def test_price_walk_starts_at_mid():
    quote = OptionQuote(Decimal("1.00"), Decimal("1.20"))
    prices = price_walk(
        quote,
        side="buy",
        increment=Decimal("0.01"),
        max_slippage_pct=Decimal("0.10"),
    )
    assert prices[0] == Decimal("1.10")
    assert all(x <= Decimal("1.20") for x in prices)

def test_second_leg_waits_for_first_fill():
    plan = MultiLegPlan(
        strategy_id="test",
        risk_reducing_leg=LegExecution("long", "buy", "open"),
        second_leg=LegExecution("short", "sell", "open"),
    )
    assert not plan.second_leg_allowed()
    plan.risk_reducing_leg.state = LegState.FILLED
    assert plan.second_leg_allowed()

def test_failed_second_leg_requires_unwind():
    plan = MultiLegPlan(
        strategy_id="test",
        risk_reducing_leg=LegExecution("long", "buy", "open", state=LegState.FILLED),
        second_leg=LegExecution("short", "sell", "open"),
    )
    plan.mark_second_leg_timeout()
    assert plan.second_leg.state == LegState.CANCELLED
    assert plan.risk_reducing_leg.state == LegState.UNWIND_REQUIRED
