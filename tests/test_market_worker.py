import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.market_scanner.store import MarketScannerStore
from app.market_scanner.worker import MarketScanWorker
from app.market_scanner.types import EquityScreenResult


def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False), engine


class FakeCoordinator:
    def __init__(self, store, symbols=None):
        self.store = store
        self.symbols_to_scan = list(symbols or [])
        self.discover_calls = 0

    async def discover(self, run_id):
        self.discover_calls += 1
        run = self.store.get_run(run_id)
        run.symbols_discovered = max(run.symbols_discovered, len(self.symbols_to_scan))
        run.symbols_prefiltered = max(run.symbols_prefiltered, len(self.symbols_to_scan))
        for symbol in self.symbols_to_scan:
            self.store.upsert_symbol(run_id, symbol, "fake", False)
            self.store.mark_equity_screen(
                run_id,
                symbol,
                EquityScreenResult(
                    symbol=symbol,
                    passed=True,
                    reasons=(),
                    priority_score=10,
                    price=Decimal("50"),
                ),
            )
        self.store.db.commit()
        return len(self.symbols_to_scan)

    def next_deep_scan_symbols(self, run_id, limit):
        return [
            row.symbol
            for row in self.store.stale_symbol_candidates(run_id, limit)
        ]


class FakeDeepScan:
    def __init__(self, store, statuses=None):
        self.store = store
        self.statuses = dict(statuses or {})

    async def scan_many(self, run_id, symbols):
        result = {}
        for symbol in symbols:
            status = self.statuses.get(symbol, "complete")
            self.store.mark_deep_scan(
                run_id,
                symbol,
                status=status,
                market_filter_passes=1 if status == "complete" else 0,
                mechanical_match_count=1 if status == "complete" else 0,
                near_miss_count=0,
                tool_errors={} if status == "complete" else {"scan": "failed"},
            )
            result[symbol] = type(
                "Result",
                (),
                {"status": status},
            )()
        return result


def worker_with_fakes(factory, symbols=None, statuses=None):
    def coordinator_factory(store):
        return FakeCoordinator(store, symbols)

    def deep_factory(store, db):
        return FakeDeepScan(store, statuses)

    return MarketScanWorker(
        session_factory=factory,
        coordinator_factory=coordinator_factory,
        deep_scan_factory=deep_factory,
    )


@pytest.mark.asyncio
async def test_startup_requeues_interrupted_run_without_resetting_completed_symbols(
    monkeypatch,
):
    from app.config import settings

    monkeypatch.setattr(settings, "market_scanner_enabled", False)
    factory, _ = session_factory()
    db = factory()
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={"max_deep_symbols": 100},
    )
    store.upsert_symbol(run.id, "AAPL", "price-250-500", False)
    store.mark_deep_scan(
        run.id,
        "AAPL",
        status="complete",
        market_filter_passes=4,
        mechanical_match_count=1,
        near_miss_count=0,
        tool_errors={},
    )
    store.set_run_status(run.id, "deep_scanning")
    db.close()

    worker = worker_with_fakes(factory)
    await worker.start()

    db = factory()
    recovered = MarketScannerStore(db)
    assert recovered.get_run(run.id).status == "queued"
    assert recovered.get_symbol(run.id, "AAPL").option_scan_status == "complete"
    db.close()
    await worker.stop()


@pytest.mark.asyncio
async def test_worker_marks_partial_when_one_symbol_fails():
    factory, _ = session_factory()
    worker = worker_with_fakes(
        factory,
        symbols=["AAPL", "BAD"],
        statuses={"AAPL": "complete", "BAD": "failed"},
    )
    run = worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    await worker.run_once(run.id)

    db = factory()
    stored = MarketScannerStore(db).get_run(run.id)
    assert stored.status == "partial"
    db.close()


def test_worker_rejects_second_active_run():
    factory, _ = session_factory()
    worker = worker_with_fakes(factory, symbols=["AAPL"])
    worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    with pytest.raises(RuntimeError, match="active market scan"):
        worker.create_or_queue_run(
            risk_capital_mode="simulation",
            risk_equity=Decimal("750000"),
            config_snapshot={},
        )


@pytest.mark.asyncio
async def test_resume_skips_discovery_when_persisted_universe_exists():
    factory, _ = session_factory()
    worker = worker_with_fakes(factory, symbols=["AAPL"])
    run = worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    db = factory()
    store = MarketScannerStore(db)
    store.upsert_symbol(run.id, "AAPL", "persisted", False)
    store.mark_equity_screen(
        run.id,
        "AAPL",
        EquityScreenResult(
            symbol="AAPL",
            passed=True,
            reasons=(),
            priority_score=10,
            price=Decimal("50"),
        ),
    )
    persisted = store.get_run(run.id)
    persisted.symbols_discovered = 1
    persisted.symbols_prefiltered = 1
    store.db.commit()
    db.close()

    await worker.run_once(run.id)

    db = factory()
    store = MarketScannerStore(db)
    assert store.get_run(run.id).status == "complete"
    assert store.get_symbol(run.id, "AAPL").option_scan_status == "complete"
    db.close()



@pytest.mark.asyncio
async def test_cycle_cap_rotates_never_scanned_symbols_across_runs(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "market_scanner_max_deep_symbols", 2)
    factory, _ = session_factory()
    symbols = ["AAA", "BBB", "CCC"]
    worker = worker_with_fakes(factory, symbols=symbols)

    first = worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )
    await worker.run_once(first.id)

    db = factory()
    first_store = MarketScannerStore(db)
    first_statuses = {
        symbol: first_store.get_symbol(first.id, symbol).option_scan_status
        for symbol in symbols
    }
    assert sum(status == "complete" for status in first_statuses.values()) == 2
    assert first_statuses["CCC"] == "pending"
    db.close()

    second = worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )
    await worker.run_once(second.id)

    db = factory()
    second_store = MarketScannerStore(db)
    assert second_store.get_symbol(second.id, "CCC").option_scan_status == "complete"
    db.close()


class BlockingDeepScan:
    def __init__(self, store):
        self.store = store
        self.started = asyncio.Event()

    async def scan_many(self, run_id, symbols):
        first = symbols[0]
        self.store.mark_deep_scan(
            run_id,
            first,
            status="complete",
            market_filter_passes=1,
            mechanical_match_count=0,
            near_miss_count=0,
            tool_errors={},
        )
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_worker_stop_cancels_active_sweep_and_restart_requeues(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "market_scanner_enabled", True)
    factory, _ = session_factory()
    blocker_box = {}

    def coordinator_factory(store):
        return FakeCoordinator(store, ["AAA", "BBB"])

    def deep_factory(store, db):
        blocker = BlockingDeepScan(store)
        blocker_box["value"] = blocker
        return blocker

    worker = MarketScanWorker(
        session_factory=factory,
        coordinator_factory=coordinator_factory,
        deep_scan_factory=deep_factory,
    )
    await worker.start()
    run = worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    while "value" not in blocker_box:
        await asyncio.sleep(0)
    await asyncio.wait_for(blocker_box["value"].started.wait(), timeout=1)
    await asyncio.wait_for(worker.stop(), timeout=1)

    monkeypatch.setattr(settings, "market_scanner_enabled", False)
    recovery_worker = MarketScanWorker(
        session_factory=factory,
        coordinator_factory=coordinator_factory,
        deep_scan_factory=deep_factory,
    )
    await recovery_worker.start()

    db = factory()
    store = MarketScannerStore(db)
    assert store.get_run(run.id).status == "queued"
    assert store.get_symbol(run.id, "AAA").option_scan_status == "complete"
    assert store.get_symbol(run.id, "BBB").option_scan_status == "pending"
    db.close()
    await recovery_worker.stop()



class ErrorCountingCoordinator(FakeCoordinator):
    def __init__(self, store, symbols=None, *, passed_symbols=1):
        super().__init__(store, symbols)
        self.passed_symbols = passed_symbols

    async def discover(self, run_id):
        await super().discover(run_id)
        run = self.store.get_run(run_id)
        run.error_count += 1
        run.symbols_prefiltered = self.passed_symbols
        self.store.db.commit()
        return run.symbols_discovered


@pytest.mark.asyncio
async def test_worker_marks_partial_when_prefilter_errors_have_successful_symbols():
    factory, _ = session_factory()

    def coordinator_factory(store):
        return ErrorCountingCoordinator(store, ["AAPL"], passed_symbols=1)

    worker = MarketScanWorker(
        session_factory=factory,
        coordinator_factory=coordinator_factory,
        deep_scan_factory=lambda store, db: FakeDeepScan(store),
    )
    run = worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    await worker.run_once(run.id)

    db = factory()
    assert MarketScannerStore(db).get_run(run.id).status == "partial"
    db.close()


@pytest.mark.asyncio
async def test_worker_marks_failed_when_discovery_errors_leave_no_survivors():
    factory, _ = session_factory()

    class NoSurvivorCoordinator(ErrorCountingCoordinator):
        async def discover(self, run_id):
            run = self.store.get_run(run_id)
            run.status = "discovering"
            run.symbols_discovered = 1
            run.symbols_prefiltered = 0
            run.error_count = 1
            self.store.db.commit()
            return 1

        def next_deep_scan_symbols(self, run_id, limit):
            return []

    worker = MarketScanWorker(
        session_factory=factory,
        coordinator_factory=lambda store: NoSurvivorCoordinator(
            store, [], passed_symbols=0
        ),
        deep_scan_factory=lambda store, db: FakeDeepScan(store),
    )
    run = worker.create_or_queue_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )

    await worker.run_once(run.id)

    db = factory()
    assert MarketScannerStore(db).get_run(run.id).status == "failed"
    db.close()
