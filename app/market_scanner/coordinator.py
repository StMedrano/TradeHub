import asyncio
from decimal import Decimal
from typing import Protocol

from app.config import settings
from app.market_scanner.prefilter import EquityPrefilter, equity_prefilter
from app.market_scanner.robinhood_scanner import (
    RobinhoodScannerService,
    robinhood_scanner_service,
)
from app.market_scanner.store import MarketScannerStore
from app.market_scanner.types import DiscoveredSymbol, EquityScreenResult
from app.robinhood.client import RobinhoodAuthRequired


class SymbolDiscoveryProvider(Protocol):
    async def discover_slices(self) -> list[DiscoveredSymbol]: ...


def _watchlist_set() -> set[str]:
    result: set[str] = set()
    for raw in settings.strategy_watchlist.split(","):
        symbol = raw.strip().upper()
        if symbol:
            result.add(symbol)
    return result


class MarketUniverseCoordinator:
    def __init__(
        self,
        scanner: SymbolDiscoveryProvider | RobinhoodScannerService,
        store: MarketScannerStore,
        prefilter: EquityPrefilter,
    ):
        self.scanner = scanner
        self.store = store
        self.prefilter = prefilter

    async def discover(self, run_id: str) -> int:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)

        self.store.set_run_status(run_id, "discovering")
        discovered = await self.scanner.discover_slices()
        watchlist = _watchlist_set()

        unique: dict[str, DiscoveredSymbol] = {}
        for item in discovered:
            symbol = item.symbol.strip().upper()
            if not symbol:
                continue
            unique.setdefault(symbol, item)

        for symbol, item in unique.items():
            self.store.upsert_symbol(
                run_id,
                symbol,
                item.source_slice,
                symbol in watchlist,
            )

        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run.symbols_discovered = len(unique)
        run.symbols_prefiltered = 0
        self.store.db.commit()

        capacity = (
            Decimal(str(run.risk_equity))
            * Decimal(str(settings.max_trade_loss_pct))
        )
        base_error_count = run.error_count
        passed = 0
        prefilter_errors = 0
        semaphore = asyncio.Semaphore(
            settings.market_scanner_prefilter_concurrency
        )

        async def screen_symbol(symbol: str):
            async with semaphore:
                watchlist_priority = symbol in watchlist
                try:
                    result = await self.prefilter.screen(
                        symbol,
                        watchlist_priority,
                        capacity,
                    )
                    return symbol, result, None
                except RobinhoodAuthRequired as exc:
                    return symbol, None, exc
                except Exception as exc:
                    result = EquityScreenResult(
                        symbol=symbol,
                        passed=False,
                        reasons=(f"Equity prefilter read failed: {exc}",),
                        priority_score=0.0,
                    )
                    return symbol, result, exc

        tasks = [
            asyncio.create_task(screen_symbol(symbol))
            for symbol in sorted(unique)
        ]

        try:
            for completed in asyncio.as_completed(tasks):
                symbol, result, error = await completed
                if isinstance(error, RobinhoodAuthRequired):
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise error

                if error is not None:
                    prefilter_errors += 1
                assert result is not None
                self.store.mark_equity_screen(run_id, symbol, result)
                if result.passed:
                    passed += 1

                progress = self.store.get_run(run_id)
                if progress is not None:
                    progress.symbols_prefiltered = passed
                    progress.error_count = base_error_count + prefilter_errors
                    self.store.db.commit()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        return len(unique)

    def next_deep_scan_symbols(
        self,
        run_id: str,
        limit: int,
    ) -> list[str]:
        bounded = max(
            0,
            min(limit, settings.market_scanner_max_deep_symbols),
        )
        if bounded == 0:
            return []
        rows = self.store.stale_symbol_candidates(run_id, bounded)
        return [row.symbol for row in rows]


def coordinator_for_store(store: MarketScannerStore) -> MarketUniverseCoordinator:
    return MarketUniverseCoordinator(
        robinhood_scanner_service,
        store,
        equity_prefilter,
    )
