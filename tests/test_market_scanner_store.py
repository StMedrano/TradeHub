from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.market_scanner.store import MarketScannerStore
from app.market_scanner.types import EquityScreenResult


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def candidate_payload(option_id="opt-1", approved=True):
    return {
        "option_id": option_id,
        "symbol": "AAPL",
        "strategy": "cash_secured_put",
        "expiration_date": "2026-10-16",
        "strike_price": "325.0000",
        "delta": -0.28,
        "bid": "3.80",
        "ask": "4.00",
        "mark": "3.90",
        "open_interest": 1200,
        "volume": 250,
        "spread_pct": 5.13,
        "estimated_credit": "380.0000",
        "estimated_collateral": "32120.0000",
        "estimated_max_loss": "32120.0000",
        "score": 92.7,
        "risk_approved": approved,
        "rejection_stage": None if approved else "risk_manager",
        "risk_reasons": [] if approved else ["Trade max loss exceeds per-trade limit."],
        "minimum_equity_for_trade_limit": None if approved else "642400.0000",
        "scanned_at": "2026-09-19T16:00:00+00:00",
    }


def test_create_run_persists_config_and_risk_context():
    db = make_session()
    store = MarketScannerStore(db)

    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={"min_price": 5, "max_deep_symbols": 100},
    )

    assert run.status == "queued"
    assert run.risk_capital_mode == "simulation"
    assert run.risk_equity == Decimal("750000.0000")
    assert '"min_price": 5' in run.config_json


def test_upsert_symbol_is_idempotent_for_same_run_and_symbol():
    db = make_session()
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    first = store.upsert_symbol(run.id, "AAPL", "price-250-500", True)
    second = store.upsert_symbol(run.id, "AAPL", "price-250-500", True)

    assert first.id == second.id
    assert store.symbols(run.id) == ["AAPL"]


def test_replace_symbol_opportunities_does_not_duplicate_option_id():
    db = make_session()
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    store.replace_symbol_opportunities(
        run.id,
        "AAPL",
        [candidate_payload(option_id="opt-1")],
    )
    store.replace_symbol_opportunities(
        run.id,
        "AAPL",
        [candidate_payload(option_id="opt-1")],
    )

    rows = store.latest_opportunities(symbol="AAPL")
    assert len(rows) == 1
    assert rows[0].option_id == "opt-1"


def test_recover_interrupted_runs_requeues_without_erasing_symbol_state():
    db = make_session()
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )
    store.upsert_symbol(run.id, "AAPL", "price-250-500", False)
    store.mark_equity_screen(
        run.id,
        "AAPL",
        EquityScreenResult(
            symbol="AAPL",
            passed=True,
            reasons=(),
            priority_score=10.0,
            price=Decimal("250"),
        ),
    )
    store.set_run_status(run.id, "deep_scanning")

    recovered = store.recover_interrupted_runs()

    assert recovered == [run.id]
    assert store.get_run(run.id).status == "queued"
    assert store.get_symbol(run.id, "AAPL").equity_screen_status == "passed"


def test_near_misses_are_separate_from_approved_opportunities():
    db = make_session()
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    store.replace_symbol_opportunities(
        run.id,
        "AAPL",
        [
            candidate_payload(option_id="pass", approved=True),
            candidate_payload(option_id="miss", approved=False),
        ],
    )

    assert [row.option_id for row in store.latest_opportunities("AAPL")] == ["pass"]
    assert [row.option_id for row in store.latest_near_misses("AAPL")] == ["miss"]
