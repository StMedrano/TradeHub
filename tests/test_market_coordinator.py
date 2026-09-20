from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.market_scanner.coordinator import MarketUniverseCoordinator
from app.market_scanner.store import MarketScannerStore
from app.market_scanner.types import DiscoveredSymbol, EquityScreenResult
from app.robinhood.client import RobinhoodAuthRequired


def make_store():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    return MarketScannerStore(db)


class FakeScanner:
    def __init__(self, discovered):
        self.discovered = discovered

    async def discover_slices(self):
        return self.discovered


class FakePrefilter:
    def __init__(self, rejected=None):
        self.rejected = set(rejected or [])

    async def screen(self, symbol, watchlist_priority, capacity, **kwargs):
        passed = symbol not in self.rejected
        return EquityScreenResult(
            symbol=symbol,
            passed=passed,
            reasons=() if passed else ("rejected",),
            priority_score=1000.0 if watchlist_priority else 10.0,
            price=Decimal("50"),
            average_volume=2_000_000,
            market_cap=Decimal("5000000000"),
            is_etf=True,
        )


def create_run(store):
    return store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )


@pytest.mark.asyncio
async def test_discovery_deduplicates_symbol_across_slices(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist", "")
    store = make_store()
    run = create_run(store)
    scanner = FakeScanner(
        [
            DiscoveredSymbol("AAPL", "slice-a"),
            DiscoveredSymbol("AAPL", "slice-b"),
            DiscoveredSymbol("MSFT", "slice-b"),
        ]
    )
    coordinator = MarketUniverseCoordinator(scanner, store, FakePrefilter())

    count = await coordinator.discover(run.id)

    assert count == 2
    assert store.symbols(run.id) == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_watchlist_symbol_is_prioritized_but_failed_screen_is_not_queued(
    monkeypatch,
):
    monkeypatch.setattr(settings, "strategy_watchlist", "AAA")
    store = make_store()
    run = create_run(store)
    scanner = FakeScanner(
        [
            DiscoveredSymbol("AAA", "slice-a"),
            DiscoveredSymbol("BBB", "slice-a"),
        ]
    )
    coordinator = MarketUniverseCoordinator(
        scanner,
        store,
        FakePrefilter(rejected={"AAA"}),
    )

    await coordinator.discover(run.id)

    assert coordinator.next_deep_scan_symbols(run.id, 10) == ["BBB"]


def test_never_scanned_and_stale_symbols_are_not_starved(monkeypatch):
    monkeypatch.setattr(settings, "market_scanner_max_deep_symbols", 100)
    store = make_store()
    run = create_run(store)

    for symbol in ("OLD", "FRESH"):
        store.upsert_symbol(run.id, symbol, "slice", False)
        store.mark_equity_screen(
            run.id,
            symbol,
            EquityScreenResult(
                symbol=symbol,
                passed=True,
                reasons=(),
                priority_score=10,
                price=Decimal("50"),
            ),
        )

    old = store.get_symbol(run.id, "OLD")
    fresh = store.get_symbol(run.id, "FRESH")
    old.last_deep_scan_at = datetime.now(timezone.utc) - timedelta(hours=72)
    fresh.last_deep_scan_at = datetime.now(timezone.utc) - timedelta(hours=1)
    store.db.commit()

    coordinator = MarketUniverseCoordinator(
        FakeScanner([]),
        store,
        FakePrefilter(),
    )

    assert coordinator.next_deep_scan_symbols(run.id, 1) == ["OLD"]


def test_deep_scan_queue_honors_configured_cycle_cap(monkeypatch):
    monkeypatch.setattr(settings, "market_scanner_max_deep_symbols", 1)
    store = make_store()
    run = create_run(store)
    for symbol in ("AAA", "BBB"):
        store.upsert_symbol(run.id, symbol, "slice", False)
        store.mark_equity_screen(
            run.id,
            symbol,
            EquityScreenResult(
                symbol=symbol,
                passed=True,
                reasons=(),
                priority_score=10,
                price=Decimal("50"),
            ),
        )

    coordinator = MarketUniverseCoordinator(FakeScanner([]), store, FakePrefilter())

    assert len(coordinator.next_deep_scan_symbols(run.id, 10)) == 1



class ErrorPrefilter(FakePrefilter):
    def __init__(self, *, auth=False):
        super().__init__()
        self.auth = auth

    async def screen(self, symbol, watchlist_priority, capacity, **kwargs):
        if symbol == "BAD":
            if self.auth:
                raise RobinhoodAuthRequired("authentication required")
            raise RuntimeError("fundamentals unavailable")
        return await super().screen(symbol, watchlist_priority, capacity, **kwargs)


@pytest.mark.asyncio
async def test_prefilter_failure_rejects_only_that_symbol_and_counts_error():
    store = make_store()
    run = create_run(store)
    coordinator = MarketUniverseCoordinator(
        FakeScanner([
            DiscoveredSymbol("GOOD", "slice"),
            DiscoveredSymbol("BAD", "slice"),
        ]),
        store,
        ErrorPrefilter(),
    )

    await coordinator.discover(run.id)

    assert store.get_symbol(run.id, "GOOD").equity_screen_status == "passed"
    assert store.get_symbol(run.id, "BAD").equity_screen_status == "rejected"
    assert store.get_run(run.id).error_count == 1


@pytest.mark.asyncio
async def test_prefilter_auth_failure_aborts_discovery():
    store = make_store()
    run = create_run(store)
    coordinator = MarketUniverseCoordinator(
        FakeScanner([DiscoveredSymbol("BAD", "slice")]),
        store,
        ErrorPrefilter(auth=True),
    )

    with pytest.raises(RobinhoodAuthRequired):
        await coordinator.discover(run.id)
