import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from app.config import RiskCapitalMode, settings
from app.domain.models import (
    AccountRiskSnapshot,
    RiskPolicy,
    StrategyType,
    TradeIntent,
)
from app.market_scanner.prefilter import EquityReadProvider, RobinhoodEquityReadProvider
from app.market_scanner.store import MarketScannerStore
from app.risk.manager import RiskManager
from app.risk.state import portfolio_risk_state_service, simulation_risk_state_service
from app.robinhood.client import RobinhoodAuthRequired
from app.robinhood.market_data import RobinhoodMarketDataService, robinhood_market_data
from app.robinhood.read_service import RobinhoodSnapshot, robinhood_read_service
from app.strategy.candidates import PhaseOneCandidateEngine, phase_one_candidate_engine


@dataclass(frozen=True)
class RiskContext:
    authoritative: bool
    snapshot: AccountRiskSnapshot | None
    strategy_snapshot: RobinhoodSnapshot
    policy: RiskPolicy
    mode: str
    reasons: tuple[str, ...]


class RiskContextProvider(Protocol):
    async def get(self) -> RiskContext: ...


@dataclass(frozen=True)
class DeepScanSymbolResult:
    symbol: str
    status: str
    match_count: int
    near_miss_count: int
    candidates: list[dict[str, object]]
    tool_errors: dict[str, str]


class DatabaseRiskContextProvider:
    def __init__(self, db: Session):
        self.db = db

    async def get(self) -> RiskContext:
        policy = RiskPolicy(
            max_trade_loss_pct=Decimal(str(settings.max_trade_loss_pct)),
            max_portfolio_loss_pct=Decimal(str(settings.max_portfolio_loss_pct)),
            daily_loss_breaker_pct=Decimal(str(settings.daily_loss_breaker_pct)),
            max_concurrent_positions=settings.max_concurrent_positions,
            phase=settings.phase,
            require_approval=settings.require_approval,
        )

        if settings.risk_capital_mode == RiskCapitalMode.SIMULATION:
            capital = Decimal(str(settings.simulation_capital))
            state = simulation_risk_state_service.build(
                self.db,
                capital=capital,
            )
            reserved = (
                state.snapshot.open_position_max_loss
                if state.snapshot is not None
                else Decimal("0")
            )
            available = max(capital - reserved, Decimal("0"))
            strategy_snapshot = RobinhoodSnapshot(
                connection_state="connected",
                equity=float(capital),
                buying_power=float(available),
                cash=float(available),
                realized_pnl_today=0.0,
                realized_pnl_authoritative=True,
                equity_positions=[],
                option_positions=[],
                open_equity_positions=0,
                open_option_positions=0,
                open_orders=0,
            )
            return RiskContext(
                authoritative=state.authoritative,
                snapshot=state.snapshot,
                strategy_snapshot=strategy_snapshot,
                policy=policy,
                mode=RiskCapitalMode.SIMULATION.value,
                reasons=state.reasons,
            )

        await robinhood_read_service.sync_once()
        state = portfolio_risk_state_service.build(
            self.db,
            robinhood_read_service.snapshot,
        )
        return RiskContext(
            authoritative=state.authoritative,
            snapshot=state.snapshot,
            strategy_snapshot=robinhood_read_service.snapshot,
            policy=policy,
            mode=RiskCapitalMode.LIVE_ACCOUNT.value,
            reasons=state.reasons,
        )


class MarketDeepScanService:
    def __init__(
        self,
        *,
        market_data: RobinhoodMarketDataService,
        store: MarketScannerStore,
        risk_context_provider: RiskContextProvider,
        candidate_engine: PhaseOneCandidateEngine | None = None,
        risk_manager: RiskManager | None = None,
        equity_provider: EquityReadProvider | None = None,
    ):
        self.market_data = market_data
        self.store = store
        self.risk_context_provider = risk_context_provider
        self.candidate_engine = candidate_engine or phase_one_candidate_engine
        self.risk_manager = risk_manager or RiskManager()
        self.equity_provider = equity_provider
        self._store_lock = asyncio.Lock()

    async def _market_scan_with_retry(self, symbol: str):
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return await self.market_data.scan_symbol(symbol)
            except RobinhoodAuthRequired:
                raise
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0)
        assert last_error is not None
        raise last_error

    async def _earnings_rejection(
        self,
        symbol: str,
        expiration_date: str | None,
    ) -> str | None:
        if not settings.market_scanner_exclude_earnings:
            return None
        if self.equity_provider is None:
            return None

        snapshot = await self.equity_provider.snapshot(symbol)
        if snapshot.is_etf:
            return None
        if snapshot.next_earnings_date is None:
            return "Required earnings date is unavailable for contract screening."
        if not expiration_date:
            return "Option expiration is unavailable for earnings screening."
        try:
            expiry = date.fromisoformat(str(expiration_date)[:10])
        except ValueError:
            return "Option expiration is invalid for earnings screening."
        if snapshot.next_earnings_date <= expiry:
            return (
                f"Earnings on {snapshot.next_earnings_date.isoformat()} occur "
                "on or before option expiration."
            )
        return None

    async def _persist_failure(
        self,
        run_id: str,
        symbol: str,
        error: Exception,
    ) -> DeepScanSymbolResult:
        message = str(error)
        async with self._store_lock:
            self.store.mark_deep_scan(
                run_id,
                symbol,
                status="failed",
                market_filter_passes=0,
                mechanical_match_count=0,
                near_miss_count=0,
                tool_errors={"scan_symbol": message},
            )
            run = self.store.get_run(run_id)
            if run is not None:
                run.error_count += 1
                self.store.db.commit()
        return DeepScanSymbolResult(
            symbol=symbol,
            status="failed",
            match_count=0,
            near_miss_count=0,
            candidates=[],
            tool_errors={"scan_symbol": message},
        )

    async def _scan_with_context(
        self,
        run_id: str,
        symbol: str,
        context: RiskContext,
    ) -> DeepScanSymbolResult:
        async with self._store_lock:
            self.store.mark_deep_scan(
                run_id,
                symbol,
                status="running",
                market_filter_passes=0,
                mechanical_match_count=0,
                near_miss_count=0,
                tool_errors={},
            )

        try:
            scan = await self._market_scan_with_retry(symbol)
        except RobinhoodAuthRequired:
            raise
        except Exception as exc:
            return await self._persist_failure(run_id, symbol, exc)

        candidates = self.candidate_engine.generate(
            scan,
            context.strategy_snapshot,
        )
        diagnostics = self.candidate_engine.diagnose(
            scan,
            context.strategy_snapshot,
        )
        market_filter_passes = sum(1 for item in diagnostics if item.passed)

        rows: list[dict[str, object]] = []
        match_count = 0
        near_miss_count = 0

        for candidate in candidates:
            row = candidate.as_dict()
            row["scanned_at"] = scan.scanned_at
            row["risk_capital_mode"] = context.mode
            row["mechanical_only"] = True
            row["execution_enabled"] = False

            if candidate.strategy != StrategyType.CASH_SECURED_PUT.value:
                row.update(
                    {
                        "risk_approved": False,
                        "rejection_stage": "unsupported_strategy",
                        "risk_reasons": [
                            "Whole-market Phase 1 scanning currently persists CSP candidates only."
                        ],
                    }
                )
                near_miss_count += 1
                rows.append(row)
                continue

            if candidate.buying_power_sufficient is not True:
                row.update(
                    {
                        "risk_approved": False,
                        "rejection_stage": "buying_power",
                        "risk_reasons": list(candidate.reasons)
                        or ["Available risk-capital buying power is insufficient."],
                    }
                )
                near_miss_count += 1
                rows.append(row)
                continue

            if candidate.estimated_max_loss is None:
                row.update(
                    {
                        "risk_approved": False,
                        "rejection_stage": "max_loss",
                        "risk_reasons": ["Candidate maximum loss is unavailable."],
                    }
                )
                near_miss_count += 1
                rows.append(row)
                continue

            earnings_reason = await self._earnings_rejection(
                symbol,
                candidate.expiration_date,
            )
            if earnings_reason:
                row.update(
                    {
                        "risk_approved": False,
                        "rejection_stage": "earnings",
                        "risk_reasons": [earnings_reason],
                    }
                )
                near_miss_count += 1
                rows.append(row)
                continue

            if not context.authoritative or context.snapshot is None:
                row.update(
                    {
                        "risk_approved": False,
                        "rejection_stage": "portfolio_risk_unavailable",
                        "risk_reasons": list(context.reasons)
                        or ["Authoritative portfolio risk is unavailable."],
                    }
                )
                near_miss_count += 1
                rows.append(row)
                continue

            intent = TradeIntent(
                strategy=StrategyType.CASH_SECURED_PUT,
                underlying=candidate.symbol,
                contracts=candidate.contracts,
                known_max_loss=candidate.estimated_max_loss,
                shares_held=candidate.shares_held,
                has_short_put=True,
                is_defined_risk=True,
            )
            decision = self.risk_manager.evaluate(
                intent,
                context.snapshot,
                context.policy,
            )
            required_equity = (
                candidate.estimated_max_loss / context.policy.max_trade_loss_pct
                if context.policy.max_trade_loss_pct > 0
                else None
            )
            row.update(
                {
                    "risk_approved": decision.approved,
                    "rejection_stage": None if decision.approved else "risk_manager",
                    "risk_reasons": list(decision.reasons),
                    "trade_limit": str(decision.trade_limit),
                    "portfolio_limit": str(decision.portfolio_limit),
                    "daily_loss_limit": str(decision.daily_loss_limit),
                    "minimum_equity_for_trade_limit": (
                        str(required_equity) if required_equity is not None else None
                    ),
                }
            )
            if decision.approved:
                match_count += 1
            else:
                near_miss_count += 1
            rows.append(row)

        async with self._store_lock:
            self.store.replace_symbol_opportunities(run_id, symbol, rows)
            self.store.mark_deep_scan(
                run_id,
                symbol,
                status="complete",
                market_filter_passes=market_filter_passes,
                mechanical_match_count=match_count,
                near_miss_count=near_miss_count,
                tool_errors=scan.tool_errors,
            )
            run = self.store.get_run(run_id)
            if run is not None:
                run.symbols_deep_scanned += 1
                run.contracts_evaluated += scan.instrument_count
                run.matches_found += match_count
                run.error_count += len(scan.tool_errors)
                self.store.db.commit()

        return DeepScanSymbolResult(
            symbol=symbol,
            status="complete",
            match_count=match_count,
            near_miss_count=near_miss_count,
            candidates=[candidate.as_dict() for candidate in candidates],
            tool_errors=dict(scan.tool_errors),
        )

    async def scan_symbol(
        self,
        run_id: str,
        symbol: str,
    ) -> DeepScanSymbolResult:
        context = await self.risk_context_provider.get()
        try:
            return await self._scan_with_context(run_id, symbol, context)
        except RobinhoodAuthRequired:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return await self._persist_failure(run_id, symbol, exc)

    async def scan_many(
        self,
        run_id: str,
        symbols: list[str],
    ) -> dict[str, DeepScanSymbolResult]:
        context = await self.risk_context_provider.get()
        semaphore = asyncio.Semaphore(settings.market_scanner_option_concurrency)

        async def one(symbol: str):
            async with semaphore:
                try:
                    return await self._scan_with_context(run_id, symbol, context)
                except RobinhoodAuthRequired:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    return await self._persist_failure(run_id, symbol, exc)

        results = await asyncio.gather(*(one(symbol) for symbol in symbols))
        return {result.symbol: result for result in results}


def deep_scan_for_store(
    store: MarketScannerStore,
    db: Session,
) -> MarketDeepScanService:
    return MarketDeepScanService(
        market_data=robinhood_market_data,
        store=store,
        risk_context_provider=DatabaseRiskContextProvider(db),
        equity_provider=RobinhoodEquityReadProvider(),
    )
