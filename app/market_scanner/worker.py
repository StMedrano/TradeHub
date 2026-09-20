import asyncio
from decimal import Decimal
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.market_scanner.coordinator import (
    MarketUniverseCoordinator,
    coordinator_for_store,
)
from app.market_scanner.deep_scan import (
    MarketDeepScanService,
    deep_scan_for_store,
)
from app.market_scanner.store import MarketScannerStore
from app.persistence.models import MarketScanRun


CoordinatorFactory = Callable[[MarketScannerStore], MarketUniverseCoordinator]
DeepScanFactory = Callable[
    [MarketScannerStore, Session],
    MarketDeepScanService,
]


class MarketScanWorker:
    def __init__(
        self,
        *,
        session_factory=SessionLocal,
        coordinator_factory: CoordinatorFactory = coordinator_for_store,
        deep_scan_factory: DeepScanFactory = deep_scan_for_store,
    ):
        self.session_factory = session_factory
        self.coordinator_factory = coordinator_factory
        self.deep_scan_factory = deep_scan_factory
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    async def start(self) -> None:
        db = self.session_factory()
        try:
            MarketScannerStore(db).recover_interrupted_runs()
        finally:
            db.close()

        if not settings.market_scanner_enabled:
            return
        if self._task is not None and not self._task.done():
            return

        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            if not self._task.done():
                self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def create_or_queue_run(
        self,
        *,
        risk_capital_mode: str,
        risk_equity: Decimal,
        config_snapshot: dict[str, object],
    ) -> MarketScanRun:
        db = self.session_factory()
        try:
            store = MarketScannerStore(db)
            active = store.get_active_run()
            if active is not None:
                raise RuntimeError(
                    f"An active market scan already exists: {active.id}."
                )
            run = store.create_run(
                risk_capital_mode=risk_capital_mode,
                risk_equity=risk_equity,
                config_snapshot=config_snapshot,
            )
            run_id = run.id
        finally:
            db.close()

        self._wake.set()

        db = self.session_factory()
        try:
            persisted = MarketScannerStore(db).get_run(run_id)
            if persisted is None:
                raise RuntimeError("Queued market scan could not be reloaded.")
            return persisted
        finally:
            db.close()

    def queue_run(self, run_id: str) -> None:
        db = self.session_factory()
        try:
            store = MarketScannerStore(db)
            run = store.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status not in {"complete", "partial", "failed"}:
                store.set_run_status(run_id, "queued")
        finally:
            db.close()
        self._wake.set()

    async def run_once(self, run_id: str) -> None:
        db = self.session_factory()
        try:
            store = MarketScannerStore(db)
            run = store.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status in {"complete", "partial", "failed"}:
                return

            coordinator = self.coordinator_factory(store)
            deep_scan = self.deep_scan_factory(store, db)

            if run.symbols_discovered == 0:
                await coordinator.discover(run_id)

            store.set_run_status(run_id, "deep_scanning")
            symbols = coordinator.next_deep_scan_symbols(
                run_id,
                settings.market_scanner_max_deep_symbols,
            )
            results = (
                await deep_scan.scan_many(run_id, symbols)
                if symbols
                else {}
            )

            deep_failures = any(
                result.status == "failed"
                for result in results.values()
            )
            deep_successes = any(
                result.status == "complete"
                for result in results.values()
            )
            run_state = store.get_run(run_id)
            recorded_errors = bool(
                run_state is not None and run_state.error_count > 0
            )
            has_errors = deep_failures or recorded_errors

            if has_errors:
                final_status = "partial" if deep_successes else "failed"
            else:
                final_status = "complete"

            store.set_run_status(run_id, final_status)
        except Exception:
            try:
                store = MarketScannerStore(db)
                run = store.get_run(run_id)
                if run is not None and run.status not in {
                    "complete",
                    "partial",
                    "failed",
                }:
                    store.set_run_status(run_id, "failed")
            finally:
                raise
        finally:
            db.close()

    async def _next_queued_run_id(self) -> str | None:
        db = self.session_factory()
        try:
            active = MarketScannerStore(db).get_active_run()
            if active is not None and active.status == "queued":
                return active.id
            return None
        finally:
            db.close()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            run_id = await self._next_queued_run_id()
            if run_id is not None:
                try:
                    await self.run_once(run_id)
                except Exception:
                    # run_once persists failed state; the loop stays alive for
                    # a future explicitly queued scan.
                    pass
                continue

            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=5.0)
            except TimeoutError:
                pass


market_scan_worker = MarketScanWorker()
