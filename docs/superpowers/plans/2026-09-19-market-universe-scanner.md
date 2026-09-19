# Market-Universe Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Robinhood Agentic-only, restart-safe whole-market discovery pipeline that finds mechanically eligible Phase 1 CSP opportunities without requiring a watchlist, while preserving TradeHub's existing live/simulation risk isolation and execution prohibitions.

**Architecture:** Add a dedicated `app/market_scanner/` subsystem instead of expanding `app/api/routes.py`. A schema-aware Robinhood scanner adapter discovers symbols; a DB-backed coordinator/prefilter persists universe state; a bounded deep-scan service reuses `RobinhoodMarketDataService`, `PhaseOneCandidateEngine`, and `RiskManager`; an in-process worker resumes persisted runs after restart; a dedicated API router and React dashboard surface scan progress, mechanical matches, and near misses.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic Settings, Robinhood Agentic MCP, pytest, React 19, Radix UI, Vite 8, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-19-market-universe-scanner-design.md`

## Global Constraints

- Robinhood Agentic is the only broker/market integration.
- Market discovery and deep scanning are read-only with respect to orders.
- No market-scanner component may call `review_option_order`, `place_option_order`, or `cancel_option_order`.
- `RISK_CAPITAL_MODE=simulation` and `RISK_CAPITAL_MODE=live_account` remain isolated.
- Simulation proposals/positions remain permanently non-executable.
- Spreads remain disabled for the current Robinhood account.
- Covered-call promotion remains disabled until whole-position stock risk is authoritative.
- Default per-trade maximum loss remains 5% of risk equity.
- Default aggregate maximum loss remains 20% of risk equity.
- Default daily realized-loss breaker remains 10% of risk equity.
- Maximum concurrent Phase 1 positions remains 1.
- Market scanner is disabled by default until explicitly enabled with `MARKET_SCANNER_ENABLED=true`.
- Approved strategy defaults become DTE 21-45, absolute short-put delta 0.15-0.30, open interest >= 500, option volume >= 50, and midpoint spread <= 10%.
- Approved equity discovery defaults are minimum price $5, average stock volume >= 1,000,000/day when available, market cap >= $1B when available, Robinhood tradability required, and earnings-before-expiration exclusion for single stocks.
- Missing data required by an enabled hard filter fails closed.
- Watchlist membership changes scan priority only; it never bypasses eligibility or risk rules.
- A cached market opportunity never becomes a proposal directly: promotion must continue to perform a fresh symbol scan and authoritative risk evaluation.

## Review Focus

1. **Robinhood scanner schema changes or missing desired filters:** the system must surface an explicit unsupported/missing-filter result and enforce the rule downstream when an official Robinhood read tool can supply the field; otherwise fail closed. Covered by Tasks 2 and 4.
2. **Interrupted scan during application restart:** persisted `discovering` or `deep_scanning` runs must return to `queued` and resume without duplicating completed symbol work. Covered by Task 7.
3. **Watchlist priority accidentally becoming an eligibility bypass:** a watchlist symbol that fails tradability, earnings, liquidity, or risk must still be rejected. Covered by Tasks 4 and 5.
4. **Partial Robinhood/MCP failure:** successful symbols must remain usable while exhausted transient failures mark the run `partial`, not discard the entire sweep. Covered by Tasks 6 and 7.
5. **Stale market opportunity promotion:** promotion must rescan the selected symbol and rerun risk even when a persisted market opportunity exists. Covered by Task 8.

---

## File Structure

New backend files:

- `app/market_scanner/__init__.py` — package boundary.
- `app/market_scanner/types.py` — scanner dataclasses/enums shared across services.
- `app/market_scanner/robinhood_scanner.py` — schema-aware Robinhood saved-scan discovery/management.
- `app/market_scanner/store.py` — SQLAlchemy persistence operations for runs, symbols, and opportunity snapshots.
- `app/market_scanner/prefilter.py` — equity-level tradability/fundamental/earnings/capital-priority checks.
- `app/market_scanner/coordinator.py` — deduplication, queue ordering, fair coverage, and run orchestration.
- `app/market_scanner/deep_scan.py` — bounded option-chain/candidate/risk evaluation and snapshot persistence.
- `app/market_scanner/worker.py` — one-run-at-a-time in-process worker with restart recovery.
- `app/api/market_scanner.py` — market-scanner API router.

Modified backend files:

- `app/config.py` — scanner settings and approved stricter strategy defaults.
- `.env.example` — document scanner settings.
- `app/persistence/models.py` — add `MarketScanRun`, `MarketScanSymbol`, and `MarketOpportunitySnapshot`.
- `app/main.py` — include scanner router; start/stop scanner worker.
- `app/api/routes.py` — only add dashboard summary fields and preserve fresh promotion semantics; do not place scanner route logic here.
- `docs/ROADMAP.md` — record market-universe scanner milestone.

New/modified tests:

- `tests/test_market_scanner_types.py`
- `tests/test_robinhood_scanner.py`
- `tests/test_market_scanner_store.py`
- `tests/test_market_prefilter.py`
- `tests/test_market_coordinator.py`
- `tests/test_market_deep_scan.py`
- `tests/test_market_worker.py`
- `tests/test_market_scanner_api.py`
- `tests/test_strategy_candidates.py`
- `tests/test_account_fit_watchlist.py`

Frontend:

- `frontend/src/marketScanner.js` — pure formatting/derivation helpers for scanner UI.
- `frontend/src/marketScanner.test.js` — Vitest tests for UI derivations.
- `frontend/src/App.jsx` — new Market Scanner navigation/content and API polling.
- `frontend/src/styles.css` — scanner metric/status layout.
- `frontend/package.json` — add Vitest test script/dev dependency.
- `.github/workflows/test.yml` — run frontend unit tests before build.

---

### Task 1: Configuration and Scanner Domain Types

**Files:**
- Create: `app/market_scanner/__init__.py`
- Create: `app/market_scanner/types.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Test: `tests/test_market_scanner_types.py`
- Test: `tests/test_strategy_candidates.py`

**Interfaces:**
- Produces `MarketScanStatus(StrEnum)` with `queued`, `discovering`, `deep_scanning`, `complete`, `partial`, `failed`.
- Produces `EquityScreenResult`, `DiscoveredSymbol`, and `MarketOpportunity` dataclasses.
- Produces scanner settings on global `settings`: `market_scanner_enabled`, `market_scanner_max_deep_symbols`, `market_scanner_option_concurrency`, `market_scanner_min_price`, `market_scanner_min_avg_volume`, `market_scanner_min_market_cap`, `market_scanner_exclude_earnings`.
- Changes existing strategy defaults to the approved stricter values.

- [ ] **Step 1: Write failing settings/default tests**

Create `tests/test_market_scanner_types.py` with:

```python
from decimal import Decimal

from app.config import Settings
from app.market_scanner.types import MarketScanStatus


def test_market_scanner_defaults_are_conservative_and_disabled():
    cfg = Settings(_env_file=None)

    assert cfg.market_scanner_enabled is False
    assert cfg.market_scanner_max_deep_symbols == 100
    assert cfg.market_scanner_option_concurrency == 2
    assert cfg.market_scanner_min_price == 5.0
    assert cfg.market_scanner_min_avg_volume == 1_000_000
    assert cfg.market_scanner_min_market_cap == 1_000_000_000
    assert cfg.market_scanner_exclude_earnings is True

    assert cfg.strategy_min_dte == 21
    assert cfg.strategy_max_dte == 45
    assert cfg.strategy_short_delta_min == 0.15
    assert cfg.strategy_short_delta_max == 0.30
    assert cfg.strategy_min_open_interest == 500
    assert cfg.strategy_min_volume == 50
    assert cfg.liquidity_max_spread_pct == 0.10


def test_market_scan_status_values_are_stable():
    assert MarketScanStatus.QUEUED.value == "queued"
    assert MarketScanStatus.DISCOVERING.value == "discovering"
    assert MarketScanStatus.DEEP_SCANNING.value == "deep_scanning"
    assert MarketScanStatus.COMPLETE.value == "complete"
    assert MarketScanStatus.PARTIAL.value == "partial"
    assert MarketScanStatus.FAILED.value == "failed"
```

Add a regression in `tests/test_strategy_candidates.py` constructing contracts just inside/outside DTE, delta, OI, volume, and spread limits so the approved defaults are pinned.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/test_market_scanner_types.py tests/test_strategy_candidates.py
```

Expected: import/attribute failures for missing scanner types/settings and assertion failures for old strategy defaults.

- [ ] **Step 3: Implement minimal settings and types**

In `app/config.py`, add:

```python
market_scanner_enabled: bool = False
market_scanner_max_deep_symbols: int = Field(default=100, ge=1, le=1000)
market_scanner_option_concurrency: int = Field(default=2, ge=1, le=10)
market_scanner_min_price: float = Field(default=5.0, ge=0)
market_scanner_min_avg_volume: int = Field(default=1_000_000, ge=0)
market_scanner_min_market_cap: int = Field(default=1_000_000_000, ge=0)
market_scanner_exclude_earnings: bool = True
```

Change:

```python
liquidity_max_spread_pct = 0.10
strategy_min_open_interest = 500
strategy_min_volume = 50
strategy_min_dte = 21
strategy_max_dte = 45
strategy_short_delta_min = 0.15
strategy_short_delta_max = 0.30
```

Create `app/market_scanner/types.py` with explicit typed dataclasses:

```python
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


class MarketScanStatus(StrEnum):
    QUEUED = "queued"
    DISCOVERING = "discovering"
    DEEP_SCANNING = "deep_scanning"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class DiscoveredSymbol:
    symbol: str
    source_slice: str
    watchlist_priority: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EquityScreenResult:
    symbol: str
    passed: bool
    reasons: tuple[str, ...]
    priority_score: float
    price: Decimal | None = None
    average_volume: int | None = None
    market_cap: Decimal | None = None
    is_etf: bool = False


@dataclass(frozen=True)
class MarketOpportunity:
    symbol: str
    option_id: str
    candidate: dict[str, Any]
    risk_approved: bool
    risk_reasons: tuple[str, ...]
    scanned_at: str
```

Document exact keys in `.env.example`.

- [ ] **Step 4: Run focused tests and full backend suite**

Run:

```bash
pytest -q tests/test_market_scanner_types.py tests/test_strategy_candidates.py
pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/market_scanner/__init__.py app/market_scanner/types.py .env.example tests/test_market_scanner_types.py tests/test_strategy_candidates.py
git commit -m "Add market scanner configuration and domain types"
```

---

### Task 2: Schema-Aware Robinhood Scanner Service

**Files:**
- Create: `app/market_scanner/robinhood_scanner.py`
- Test: `tests/test_robinhood_scanner.py`

**Interfaces:**
- Consumes `RobinhoodTradingMCP.tool_catalog()`, `RobinhoodTradingMCP.call()`, and `build_arguments()`.
- Produces `RobinhoodScannerService.filter_specs() -> dict[str, object]`.
- Produces `RobinhoodScannerService.ensure_tradehub_scan(name, filters, sort) -> str`.
- Produces `RobinhoodScannerService.run_scan(scan_id) -> list[dict[str, object]]`.
- Produces `RobinhoodScannerService.discover_slices() -> list[DiscoveredSymbol]`.
- Never exposes order/write methods.

- [ ] **Step 1: Write failing tests for advertised tools, schema building, scan reuse, and missing filters**

Create a fake MCP client with `tool_catalog()` and `call()` methods and tests:

```python
import pytest

from app.market_scanner.robinhood_scanner import RobinhoodScannerService


@pytest.mark.asyncio
async def test_filter_specs_requires_robinhood_scanner_tools(fake_scanner_client):
    fake_scanner_client.catalog.pop("get_scanner_filter_specs")

    service = RobinhoodScannerService(fake_scanner_client)

    with pytest.raises(RuntimeError, match="get_scanner_filter_specs"):
        await service.filter_specs()


@pytest.mark.asyncio
async def test_ensure_tradehub_scan_reuses_named_scan(fake_scanner_client):
    fake_scanner_client.responses["get_scans"] = {
        "data": [{"id": "scan-1", "name": "TradeHub:market:price-5-50"}]
    }

    service = RobinhoodScannerService(fake_scanner_client)
    scan_id = await service.ensure_tradehub_scan(
        "TradeHub:market:price-5-50",
        filters=[{"field": "price", "operator": "between", "value": [5, 50]}],
        sort={"field": "volume", "direction": "desc"},
    )

    assert scan_id == "scan-1"
    assert "create_scan" not in fake_scanner_client.calls


@pytest.mark.asyncio
async def test_missing_required_scanner_filter_is_reported_not_silently_skipped(
    fake_scanner_client,
):
    fake_scanner_client.responses["get_scanner_filter_specs"] = {
        "data": {"filters": [{"field": "price"}]}
    }

    service = RobinhoodScannerService(fake_scanner_client)
    support = await service.resolve_filter_support(
        {"price", "average_volume", "market_cap"}
    )

    assert support.available == {"price"}
    assert support.missing == {"average_volume", "market_cap"}
```

Also test `run_scan` normalization/deduplication from common wrapper shapes.

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest -q tests/test_robinhood_scanner.py
```

Expected: module/class missing.

- [ ] **Step 3: Implement the scanner service**

Use a read/scan-management allowlist:

```python
SCANNER_TOOLS = {
    "get_scans",
    "get_scanner_filter_specs",
    "create_scan",
    "run_scan",
    "update_scan_filters",
    "update_scan_config",
}
```

Every call must verify the tool exists in the live catalog before calling it. Build arguments through `build_arguments(schema, context)`; do not hard-code parameter names into the MCP call itself.

Define:

```python
@dataclass(frozen=True)
class FilterSupport:
    available: set[str]
    missing: set[str]
```

Normalize symbol fields from `symbol`, `ticker`, or `instrument.symbol`, uppercase them, reject malformed symbols, and deduplicate.

`discover_slices()` should use advertised filters to create bounded slices. Initial strategy:

1. Prefer a price lower-bound plus Robinhood-supported descending liquidity/volume sort.
2. If the scanner advertises a maximum result count and a price filter, create non-overlapping price bands: `5-25`, `25-50`, `50-100`, `100-250`, `250-500`, `500+`.
3. If price slicing is not supported, run the broadest compatible saved scan and mark unsupported desired filters for downstream enforcement.

Do not invent unsupported scanner fields.

- [ ] **Step 4: Verify focused and full suites**

```bash
pytest -q tests/test_robinhood_scanner.py
pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/market_scanner/robinhood_scanner.py tests/test_robinhood_scanner.py
git commit -m "Add schema-aware Robinhood market scanner service"
```

---

### Task 3: Persisted Market Scan Store

**Files:**
- Modify: `app/persistence/models.py`
- Create: `app/market_scanner/store.py`
- Test: `tests/test_market_scanner_store.py`

**Interfaces:**
- Produces SQLAlchemy models `MarketScanRun`, `MarketScanSymbol`, `MarketOpportunitySnapshot`.
- Produces `MarketScannerStore` methods for create/update/resume/query.
- All monetary values use `Numeric`/`Decimal`, never `Float`.

- [ ] **Step 1: Write failing persistence tests**

Tests must create an in-memory SQLite database via existing `Base.metadata.create_all()` and verify:

```python
def test_create_run_persists_config_and_risk_context():
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={"min_price": 5, "max_deep_symbols": 100},
    )

    assert run.status == "queued"
    assert run.risk_capital_mode == "simulation"
    assert run.risk_equity == Decimal("750000.0000")


def test_upsert_symbol_is_idempotent_for_same_run_and_symbol():
    first = store.upsert_symbol(run_id, "AAPL", "price-250-500", True)
    second = store.upsert_symbol(run_id, "AAPL", "price-250-500", True)

    assert first.id == second.id


def test_replace_symbol_opportunities_does_not_duplicate_option_id():
    store.replace_symbol_opportunities(
        run_id,
        "AAPL",
        [candidate_payload(option_id="opt-1")],
    )
    store.replace_symbol_opportunities(
        run_id,
        "AAPL",
        [candidate_payload(option_id="opt-1")],
    )

    rows = store.latest_opportunities(symbol="AAPL")
    assert len(rows) == 1
```

Also test status counters and marking errors.

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest -q tests/test_market_scanner_store.py
```

Expected: model/store imports fail.

- [ ] **Step 3: Add models**

Add to `app/persistence/models.py`:

```python
class MarketScanRun(Base):
    __tablename__ = "market_scan_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    risk_capital_mode: Mapped[str] = mapped_column(String(32))
    risk_equity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    symbols_discovered: Mapped[int] = mapped_column(Integer, default=0)
    symbols_prefiltered: Mapped[int] = mapped_column(Integer, default=0)
    symbols_deep_scanned: Mapped[int] = mapped_column(Integer, default=0)
    contracts_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    matches_found: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), ...)
```

`MarketScanSymbol` must have a unique constraint on `(run_id, symbol)` and fields for source slice, priority, equity status/reasons, earnings status, option scan status, counts, errors, start/completion timestamps, and consecutive error count.

`MarketOpportunitySnapshot` must have a unique constraint on `(run_id, option_id)` and Numeric fields for strike, bid, ask, mark, credit, collateral, and max loss.

- [ ] **Step 4: Implement store methods**

Implement focused methods:

```python
create_run(...)
get_run(run_id)
get_active_run()
recover_interrupted_runs()
upsert_symbol(...)
mark_equity_screen(...)
mark_deep_scan(...)
replace_symbol_opportunities(...)
latest_opportunities(...)
latest_near_misses(...)
stale_symbol_candidates(...)
```

`recover_interrupted_runs()` changes only `discovering` and `deep_scanning` to `queued`; completed symbol rows stay completed.

- [ ] **Step 5: Verify**

```bash
pytest -q tests/test_market_scanner_store.py
pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add app/persistence/models.py app/market_scanner/store.py tests/test_market_scanner_store.py
git commit -m "Persist market scanner runs and opportunities"
```

---

### Task 4: Equity Prefilter and Earnings Gate

**Files:**
- Create: `app/market_scanner/prefilter.py`
- Test: `tests/test_market_prefilter.py`

**Interfaces:**
- Consumes Robinhood read tools only through a small `EquityReadProvider` protocol.
- Produces `EquityPrefilter.screen(symbol, expiration_dates, capacity) -> EquityScreenResult`.
- Produces `priority_score` but never converts priority into eligibility.
- Distinguishes ETFs from single stocks for earnings checks.

- [ ] **Step 1: Write failing rule tests**

Cover exact behaviors:

```python
@pytest.mark.asyncio
async def test_untradable_symbol_fails_even_when_watchlist_priority():
    result = await prefilter.screen(
        "ABC",
        watchlist_priority=True,
        capacity=Decimal("37500"),
    )
    assert result.passed is False
    assert "Robinhood reports the symbol is not tradable." in result.reasons


@pytest.mark.asyncio
async def test_price_below_five_fails():
    provider.quote_price = Decimal("4.99")
    result = await prefilter.screen("ABC", False, Decimal("37500"))
    assert result.passed is False
    assert any("minimum 5" in reason for reason in result.reasons)


@pytest.mark.asyncio
async def test_missing_required_average_volume_fails_closed():
    provider.average_volume = None
    result = await prefilter.screen("ABC", False, Decimal("37500"))
    assert result.passed is False
    assert any("average volume" in reason.lower() for reason in result.reasons)


@pytest.mark.asyncio
async def test_single_stock_with_earnings_before_expiration_fails():
    provider.is_etf = False
    provider.next_earnings_date = date(2026, 10, 12)
    result = await prefilter.screen(
        "ABC",
        False,
        Decimal("37500"),
        expiration_dates=[date(2026, 10, 16)],
    )
    assert result.passed is False
    assert any("earnings" in reason.lower() for reason in result.reasons)


@pytest.mark.asyncio
async def test_etf_does_not_require_corporate_earnings():
    provider.is_etf = True
    provider.next_earnings_date = None
    result = await prefilter.screen("ETF", False, Decimal("37500"))
    assert result.passed is True
```

Add a test proving a very high spot price reduces `priority_score` but does not itself set `passed=False`.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/test_market_prefilter.py
```

- [ ] **Step 3: Implement read-provider adapter**

Implement schema-aware calls for:

- `get_equity_quotes`
- `get_equity_fundamentals`
- `get_equity_tradability`
- `get_earnings_calendar`

Use `build_arguments()` against live schemas.

Normalize quote price, average volume, market cap, security type, tradability, and earnings date with explicit helper functions.

- [ ] **Step 4: Implement rules and priority**

Eligibility rules enforce approved filters. Priority formula must remain simple and non-investment-oriented:

```python
priority_score = 0.0
if watchlist_priority:
    priority_score += 1000.0
if never_scanned:
    priority_score += 500.0
priority_score += min(staleness_hours, 168.0)
if price and approximate_strike_ceiling > 0:
    priority_score -= max(0.0, (price / approximate_strike_ceiling) - 1.0) * 10.0
```

This affects scan order only.

- [ ] **Step 5: Verify**

```bash
pytest -q tests/test_market_prefilter.py
pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add app/market_scanner/prefilter.py tests/test_market_prefilter.py
git commit -m "Add market equity and earnings prefilter"
```

---

### Task 5: Universe Coordinator and Fair Scheduling

**Files:**
- Create: `app/market_scanner/coordinator.py`
- Test: `tests/test_market_coordinator.py`

**Interfaces:**
- Consumes `RobinhoodScannerService.discover_slices()`, `MarketScannerStore`, `EquityPrefilter`.
- Produces `MarketUniverseCoordinator.discover(run_id) -> int`.
- Produces `MarketUniverseCoordinator.next_deep_scan_symbols(run_id, limit) -> list[str]`.
- Watchlist affects ordering only.

- [ ] **Step 1: Write failing deduplication/priority/fairness tests**

```python
@pytest.mark.asyncio
async def test_discovery_deduplicates_symbol_across_slices():
    scanner.discovered = [
        DiscoveredSymbol("AAPL", "slice-a"),
        DiscoveredSymbol("AAPL", "slice-b"),
        DiscoveredSymbol("MSFT", "slice-b"),
    ]

    count = await coordinator.discover(run_id)

    assert count == 2
    assert store.symbols(run_id) == ["AAPL", "MSFT"]


def test_watchlist_symbol_is_prioritized_but_failed_screen_is_not_queued():
    store.add_screened("AAA", passed=False, watchlist_priority=True, priority=1000)
    store.add_screened("BBB", passed=True, watchlist_priority=False, priority=10)

    assert coordinator.next_deep_scan_symbols(run_id, 10) == ["BBB"]


def test_never_scanned_and_stale_symbols_are_not_starved():
    store.add_screened("OLD", passed=True, last_deep_scan_hours=72)
    store.add_screened("FRESH", passed=True, last_deep_scan_hours=1)

    assert coordinator.next_deep_scan_symbols(run_id, 1) == ["OLD"]
```

Also test configured `market_scanner_max_deep_symbols` cap.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/test_market_coordinator.py
```

- [ ] **Step 3: Implement discovery and queue ordering**

`discover()`:

1. mark run `discovering`;
2. merge/dedupe scanner slice results;
3. set watchlist flag from `settings.strategy_watchlist`;
4. persist all unique symbols;
5. prefilter symbols in bounded read batches where supported;
6. persist explicit screen reasons;
7. update run counters.

`next_deep_scan_symbols()` queries only equity-screen-passed symbols and sorts by watchlist priority, never-scanned state, staleness, and prefilter priority.

- [ ] **Step 4: Verify**

```bash
pytest -q tests/test_market_coordinator.py
pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add app/market_scanner/coordinator.py tests/test_market_coordinator.py
git commit -m "Coordinate broad market discovery and fair scan scheduling"
```

---

### Task 6: Bounded Option Deep-Scan Service

**Files:**
- Create: `app/market_scanner/deep_scan.py`
- Test: `tests/test_market_deep_scan.py`

**Interfaces:**
- Consumes `RobinhoodMarketDataService.scan_symbol()`.
- Consumes `PhaseOneCandidateEngine.generate()/diagnose()`.
- Consumes existing effective simulation/live risk helpers through a narrow injected `RiskContextProvider`.
- Produces per-symbol persisted mechanical matches and near misses.
- Never calls promotion or execution APIs.

- [ ] **Step 1: Write failing tests for risk reuse, partial failure, multiplier, and concurrency**

Tests:

```python
@pytest.mark.asyncio
async def test_deep_scan_persists_only_risk_approved_matches():
    market_data.result = option_scan_with_two_csps(
        accepted_max_loss=Decimal("32000"),
        rejected_max_loss=Decimal("50000"),
    )
    risk_context.trade_limit = Decimal("37500")

    result = await service.scan_symbol(run_id, "AAPL")

    assert result.match_count == 1
    assert store.latest_opportunities(symbol="AAPL")[0].risk_approved is True
    assert store.latest_near_misses(symbol="AAPL")[0].risk_approved is False


@pytest.mark.asyncio
async def test_deep_scan_uses_contract_multiplier_from_candidate():
    market_data.result = csp_scan(
        strike=Decimal("10"),
        bid=Decimal("1"),
        multiplier=50,
    )

    result = await service.scan_symbol(run_id, "ABC")

    assert result.candidates[0]["estimated_max_loss"] == "450.0000"


@pytest.mark.asyncio
async def test_one_symbol_failure_does_not_discard_other_completed_symbol():
    market_data.fail_symbols = {"BAD"}

    rows = await service.scan_many(run_id, ["GOOD", "BAD"])

    assert rows["GOOD"].status == "complete"
    assert rows["BAD"].status == "failed"


@pytest.mark.asyncio
async def test_scan_many_never_exceeds_configured_concurrency():
    tracker = ConcurrencyTracker()
    await service.scan_many(run_id, ["A", "B", "C", "D"])

    assert tracker.max_seen <= 2
```

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/test_market_deep_scan.py
```

- [ ] **Step 3: Implement service**

Use `asyncio.Semaphore(settings.market_scanner_option_concurrency)`.

For each symbol:

1. mark symbol deep scan started;
2. get fresh option scan;
3. generate candidates with the active strategy account snapshot;
4. diagnose contracts;
5. for CSP candidates, preserve existing buying-power precheck;
6. invoke existing `RiskManager.evaluate()`;
7. classify as mechanical match or near miss with exact `rejection_stage` and `risk_reasons`;
8. persist opportunity snapshots;
9. persist tool errors and counts;
10. mark symbol complete/failed.

Do not reimplement max-loss formulas in this service.

- [ ] **Step 4: Verify**

```bash
pytest -q tests/test_market_deep_scan.py
pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add app/market_scanner/deep_scan.py tests/test_market_deep_scan.py
git commit -m "Add bounded market-wide option deep scanner"
```

---

### Task 7: Restart-Safe Market Scan Worker

**Files:**
- Create: `app/market_scanner/worker.py`
- Modify: `app/main.py`
- Test: `tests/test_market_worker.py`

**Interfaces:**
- Produces `MarketScanWorker.start()`, `stop()`, `queue_run(run_id)`, `run_once()`.
- On startup, calls `MarketScannerStore.recover_interrupted_runs()`.
- Processes one persisted run at a time.

- [ ] **Step 1: Write failing worker recovery/state tests**

```python
@pytest.mark.asyncio
async def test_startup_requeues_interrupted_run_without_resetting_completed_symbols():
    run = store.create_run(...)
    store.set_run_status(run.id, "deep_scanning")
    store.mark_deep_scan(run.id, "AAPL", status="complete", ...)
    store.mark_deep_scan(run.id, "MSFT", status="running", ...)

    await worker.start()
    recovered = store.get_run(run.id)

    assert recovered.status == "queued"
    assert store.get_symbol(run.id, "AAPL").option_scan_status == "complete"


@pytest.mark.asyncio
async def test_worker_marks_partial_when_one_symbol_exhausts_retries():
    deep_scan.results = {"AAPL": "complete", "BAD": "failed"}

    await worker.run_once(run.id)

    assert store.get_run(run.id).status == "partial"


@pytest.mark.asyncio
async def test_worker_rejects_second_active_run():
    first = store.create_run(...)
    store.set_run_status(first.id, "discovering")

    with pytest.raises(RuntimeError, match="active market scan"):
        worker.create_or_queue_run(...)
```

Add stop/cancellation test that checkpoints before task exits.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/test_market_worker.py
```

- [ ] **Step 3: Implement worker**

Worker behavior:

```python
async def start(self):
    self.store.recover_interrupted_runs()
    if not settings.market_scanner_enabled:
        return
    self._task = asyncio.create_task(self._loop())

async def stop(self):
    self._stop.set()
    if self._task:
        await self._task
```

`run_once()` transitions:

```text
queued -> discovering -> deep_scanning -> complete
                                 \-> partial
            \-> failed
```

Every symbol result is committed before advancing to the next batch.

Do not run scans automatically when `market_scanner_enabled=False`; manual API attempts return a disabled response.

- [ ] **Step 4: Wire startup/shutdown**

In `app/main.py`:

```python
from app.market_scanner.worker import market_scan_worker

@app.on_event("startup")
async def startup():
    init_db()
    robinhood_read_service.start()
    await market_scan_worker.start()

@app.on_event("shutdown")
async def shutdown():
    await market_scan_worker.stop()
    await robinhood_read_service.stop()
```

- [ ] **Step 5: Verify**

```bash
pytest -q tests/test_market_worker.py
pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add app/market_scanner/worker.py app/main.py tests/test_market_worker.py
git commit -m "Add restart-safe market scan worker"
```

---

### Task 8: Dedicated Market Scanner API and Fresh-Promotion Regression

**Files:**
- Create: `app/api/market_scanner.py`
- Modify: `app/main.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_market_scanner_api.py`
- Test: `tests/test_account_fit_watchlist.py`

**Interfaces:**
- `POST /api/market-scanner/run`
- `GET /api/market-scanner/status`
- `GET /api/market-scanner/runs/{run_id}`
- `GET /api/market-scanner/opportunities`
- `GET /api/market-scanner/near-misses`
- Existing `POST /api/opportunities/promote` remains the only candidate-to-proposal boundary.

- [ ] **Step 1: Write failing API tests**

Use FastAPI dependency overrides for DB/store/worker to test:

```python
def test_run_endpoint_queues_and_returns_run_id(client):
    response = client.post("/api/market-scanner/run")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["execution_enabled"] is False


def test_run_endpoint_rejects_when_scanner_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "market_scanner_enabled", False)
    response = client.post("/api/market-scanner/run")
    assert response.status_code == 409


def test_opportunities_endpoint_returns_mechanical_language(client):
    response = client.get("/api/market-scanner/opportunities")
    body = response.json()
    assert body["execution_enabled"] is False
    assert body["mechanical_only"] is True
    assert "recommend" not in body["note"].lower()


def test_near_miss_includes_rejection_stage_and_minimum_equity(client):
    row = client.get("/api/market-scanner/near-misses").json()["items"][0]
    assert row["rejection_stage"] == "risk_manager"
    assert row["minimum_equity_for_trade_limit"] == "640700.0000"
```

- [ ] **Step 2: Add fresh-promotion regression test**

Add a test around the existing promotion service/route proving persisted market data is ignored for final approval:

```python
@pytest.mark.asyncio
async def test_market_snapshot_cannot_be_promoted_without_fresh_symbol_rescan(...):
    persisted = market_opportunity(option_id="old-opt", symbol="AAPL")
    market_data.scan_symbol.return_value = scan_without_option("old-opt")

    response = await promote_phase_one_candidate(
        CandidatePromotionRequest(symbol="AAPL", option_id="old-opt"),
        db,
    )

    assert response.status_code == 409
```

If direct route invocation is awkward, extract only the existing promotion implementation into a small service in this task and keep route behavior unchanged.

- [ ] **Step 3: Verify RED**

```bash
pytest -q tests/test_market_scanner_api.py tests/test_account_fit_watchlist.py
```

- [ ] **Step 4: Implement API router**

Create `router = APIRouter(prefix="/api/market-scanner", tags=["market-scanner"])`.

Responses must include:

- scan/run IDs and status,
- aggregate counts,
- active risk capital mode/equity,
- `execution_enabled: false`,
- `mechanical_only: true` for opportunity surfaces,
- timestamps/staleness,
- exact rejection reasons for near misses.

Include router in `app/main.py`.

Only add scanner aggregate fields to existing dashboard summary; keep scanner route code out of `app/api/routes.py`.

- [ ] **Step 5: Verify**

```bash
pytest -q tests/test_market_scanner_api.py tests/test_account_fit_watchlist.py
pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add app/api/market_scanner.py app/main.py app/api/routes.py tests/test_market_scanner_api.py tests/test_account_fit_watchlist.py
git commit -m "Expose whole-market scanner API"
```

---

### Task 9: Market Scanner Dashboard UI

**Files:**
- Create: `frontend/src/marketScanner.js`
- Create: `frontend/src/marketScanner.test.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Consumes backend endpoints from Task 8.
- Adds `market-scanner` navigation section.
- Provides Run Scan button only when scanner is enabled and no active run is present.
- Shows mechanical results without recommendation language.

- [ ] **Step 1: Add Vitest and failing pure-helper tests**

Modify package scripts:

```json
"test": "vitest run"
```

Add `vitest` to devDependencies.

Create tests:

```javascript
import { describe, expect, it } from "vitest";
import {
  scannerProgress,
  scannerStatusTone,
  opportunityAgeLabel
} from "./marketScanner";

describe("scannerProgress", () => {
  it("uses deep-scanned over prefiltered symbols", () => {
    expect(scannerProgress({
      symbols_prefiltered: 200,
      symbols_deep_scanned: 50
    })).toBe(25);
  });

  it("returns zero when no symbols survived prefilter", () => {
    expect(scannerProgress({
      symbols_prefiltered: 0,
      symbols_deep_scanned: 0
    })).toBe(0);
  });
});

describe("scannerStatusTone", () => {
  it("maps partial to amber and failed to red", () => {
    expect(scannerStatusTone("partial")).toBe("amber");
    expect(scannerStatusTone("failed")).toBe("red");
  });
});
```

- [ ] **Step 2: Verify RED**

```bash
cd frontend
npm test
```

Expected: helper module missing.

- [ ] **Step 3: Implement pure helpers**

`marketScanner.js` implements deterministic progress/status/age formatting only, with no fetch side effects.

- [ ] **Step 4: Add Market Scanner UI**

In `App.jsx`:

- Add navigation item `["market-scanner", "Market Scanner", BarChartIcon]`.
- Fetch `/api/market-scanner/status` during existing dashboard refresh.
- When market-scanner section is active, fetch latest opportunities and near misses.
- `Run Market Scan` posts to `/api/market-scanner/run`.
- Poll status while run is `queued`, `discovering`, or `deep_scanning`.
- Display metric cards:
  - discovered,
  - equity-screen survivors,
  - deep-scanned,
  - contracts evaluated,
  - matches,
  - errors.
- Display active risk mode/equity and current trade/portfolio limit.
- Display opportunities table columns:
  - Symbol
  - Expiration
  - Strike
  - Delta
  - Credit
  - Max Loss
  - Score
  - Risk Status
  - Scan Age
- Display near-miss table with exact rejection reason and minimum equity where present.
- Label results `Mechanical Matches`, never `Recommendations`.

- [ ] **Step 5: Add responsive styles**

Add scanner metric grid, progress row, stale-age badge, and mobile table behavior using existing dark/Radix styling patterns.

- [ ] **Step 6: Verify frontend**

```bash
cd frontend
npm test
npm run build
```

Expected: Vitest passes and Vite build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/marketScanner.js frontend/src/marketScanner.test.js frontend/src/App.jsx frontend/src/styles.css frontend/package.json frontend/package-lock.json
git commit -m "Add whole-market scanner dashboard"
```

---

### Task 10: CI, Safety Regression, Documentation, and Disabled-by-Default Rollout

**Files:**
- Modify: `.github/workflows/test.yml`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/ARCHITECTURE.md`
- Test: all backend and frontend tests

**Interfaces:**
- CI proves both frontend tests/build and backend suite.
- Documentation records read-only market scanner boundary and rollout state.

- [ ] **Step 1: Add CI frontend test step**

Before frontend build:

```yaml
- name: Test frontend
  working-directory: frontend
  run: npm test
```

Keep existing `npm run build` and `pytest -q`.

- [ ] **Step 2: Add order-boundary safety regression**

In `tests/test_market_deep_scan.py`, add an MCP fake that raises immediately if any tool name is outside the scanner/read allowlists. Run a full market deep-scan fixture and assert only read/scanner-management tools were called.

Test shape:

```python
@pytest.mark.asyncio
async def test_market_scan_never_calls_robinhood_order_tools():
    await worker.run_once(run_id)

    forbidden = {
        "review_option_order",
        "place_option_order",
        "cancel_option_order",
    }
    assert forbidden.isdisjoint(set(fake_client.called_tool_names))
```

- [ ] **Step 3: Document architecture and roadmap**

Add to `docs/ARCHITECTURE.md`:

```text
Robinhood scanner -> TradeHub universe prefilter -> bounded option deep scan
-> PhaseOneCandidateEngine -> RiskManager -> persisted mechanical snapshot
-> fresh-rescan promotion boundary
```

State explicitly that market discovery has no order-tool dependency.

Add a roadmap milestone with checked/unchecked subitems matching actual completion state after implementation.

- [ ] **Step 4: Run complete verification**

Backend:

```bash
pytest -q
```

Frontend:

```bash
cd frontend
npm test
npm run build
```

Check scanner remains disabled by default:

```bash
python - <<'PY'
from app.config import Settings
s = Settings(_env_file=None)
assert s.market_scanner_enabled is False
print("market scanner disabled by default")
PY
```

Expected: all commands succeed.

- [ ] **Step 5: Run targeted safety/config search**

```bash
grep -R "place_option_order\|review_option_order\|cancel_option_order" -n app/market_scanner app/api/market_scanner.py || true
grep -R "MARKET_SCANNER_ENABLED" -n .env.example app/config.py
```

Expected: no order-tool references in the scanner subsystem; scanner setting documented in both config and example env.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/test.yml docs/ARCHITECTURE.md docs/ROADMAP.md tests/test_market_deep_scan.py
git commit -m "Verify and document whole-market scanner safety"
```

---

## End-to-End Acceptance Check

After all tasks are complete, deploy in simulation mode with the scanner still disabled:

```env
TRADING_MODE=dry_run
RISK_CAPITAL_MODE=simulation
SIMULATION_CAPITAL=750000
MARKET_SCANNER_ENABLED=false
ROBINHOOD_MCP_ENABLED=true
ROBINHOOD_SPREADS_ENABLED=false
```

Rebuild and verify health first:

```bash
docker compose up -d --build
curl -s http://localhost:8787/api/health | python3 -m json.tool
```

Then explicitly enable only the market scanner:

```bash
sed -i 's/^MARKET_SCANNER_ENABLED=.*/MARKET_SCANNER_ENABLED=true/' .env
docker compose up -d --force-recreate app
```

Queue a sweep:

```bash
curl -s -X POST http://localhost:8787/api/market-scanner/run | python3 -m json.tool
```

Observe status:

```bash
curl -s http://localhost:8787/api/market-scanner/status | python3 -m json.tool
```

Inspect mechanical results:

```bash
curl -s http://localhost:8787/api/market-scanner/opportunities | python3 -m json.tool
curl -s http://localhost:8787/api/market-scanner/near-misses | python3 -m json.tool
```

Acceptance criteria:

- A scan can discover symbols that are not in `STRATEGY_WATCHLIST`.
- Watchlist symbols appear earlier in processing but still fail normally when ineligible.
- Scan status and counts persist across app restart.
- Restart resumes an interrupted run rather than creating a duplicate.
- Option-chain calls are bounded by concurrency and per-cycle caps.
- Mechanical matches include exact risk context and scan timestamps.
- Near misses include rejection stage/reasons and minimum-equity calculation where available.
- Promotion of a persisted opportunity performs a fresh Robinhood symbol scan and fresh authoritative risk check.
- `execution_enabled` remains false on scanner surfaces.
- Simulation/live risk isolation tests remain green.
- No scanner component can call Robinhood order tools.
- Full backend tests, frontend tests, and frontend build are green.
