from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import market_scanner as api
from app.config import RiskCapitalMode, settings
from app.db import Base
from app.market_scanner.store import MarketScannerStore


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def opportunity(option_id="opt-1", approved=True):
    return {
        "option_id": option_id,
        "symbol": "AAPL",
        "strategy": "cash_secured_put",
        "expiration_date": "2026-10-16",
        "strike_price": "325",
        "delta": "-0.28",
        "bid": "3.80",
        "ask": "4.00",
        "mark": "3.90",
        "open_interest": 1200,
        "volume": 250,
        "spread_pct": "5.13",
        "estimated_credit": "380",
        "estimated_collateral": "32120",
        "estimated_max_loss": "32120",
        "score": "92.7",
        "risk_approved": approved,
        "rejection_stage": None if approved else "risk_manager",
        "risk_reasons": [] if approved else ["Trade max loss exceeds per-trade limit."],
        "minimum_equity_for_trade_limit": None if approved else "642400",
        "scanned_at": "2026-09-19T16:00:00+00:00",
    }


class FakeWorker:
    def __init__(self, store):
        self.store = store

    def create_or_queue_run(self, **kwargs):
        return self.store.create_run(**kwargs)


@pytest.mark.asyncio
async def test_run_endpoint_queues_and_returns_run_id(monkeypatch):
    db = make_session()
    store = MarketScannerStore(db)
    monkeypatch.setattr(settings, "market_scanner_enabled", True)
    monkeypatch.setattr(settings, "risk_capital_mode", RiskCapitalMode.SIMULATION)
    monkeypatch.setattr(settings, "simulation_capital", 750000.0)
    monkeypatch.setattr(api, "market_scan_worker", FakeWorker(store))

    response = await api.queue_market_scan(db=db)

    assert response["status"] == "queued"
    assert response["run_id"].startswith("scan-")
    assert response["execution_enabled"] is False


@pytest.mark.asyncio
async def test_run_endpoint_rejects_when_scanner_disabled(monkeypatch):
    db = make_session()
    monkeypatch.setattr(settings, "market_scanner_enabled", False)

    with pytest.raises(HTTPException) as exc:
        await api.queue_market_scan(db=db)

    assert exc.value.status_code == 409


def test_opportunities_endpoint_returns_mechanical_language():
    db = make_session()
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )
    store.replace_symbol_opportunities(run.id, "AAPL", [opportunity()])

    body = api.market_opportunities(db=db)

    assert body["execution_enabled"] is False
    assert body["mechanical_only"] is True
    assert "recommend" not in body["note"].lower()
    assert body["items"][0]["option_id"] == "opt-1"


def test_near_miss_includes_rejection_stage_and_minimum_equity():
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
        [opportunity(option_id="miss", approved=False)],
    )

    row = api.market_near_misses(db=db)["items"][0]

    assert row["rejection_stage"] == "risk_manager"
    assert Decimal(row["minimum_equity_for_trade_limit"]) == Decimal("642400")


def test_status_returns_latest_run_counts():
    db = make_session()
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )
    run.symbols_discovered = 100
    run.symbols_prefiltered = 20
    store.db.commit()

    body = api.market_scanner_status(db=db)

    assert body["run_id"] == run.id
    assert body["symbols_discovered"] == 100
    assert body["symbols_prefiltered"] == 20
    assert body["execution_enabled"] is False
