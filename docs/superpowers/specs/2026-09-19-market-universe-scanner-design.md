# TradeHub Market-Universe Scanner Design

**Date:** 2026-09-19  
**Status:** Approved in chat; written-spec review pending  
**Project:** TradeHub  
**Scope:** Robinhood Agentic-only market discovery and account-fit options scanning

## 1. Purpose

TradeHub currently discovers Phase 1 cash-secured-put (CSP) opportunities from a configured watchlist. That is useful for focused testing but does not meet the product goal: TradeHub should discover mechanically eligible option opportunities across the broader Robinhood-supported U.S. equity market without requiring the operator to preselect symbols.

This design replaces the watchlist as the primary universe with a Robinhood-native market scanner pipeline. The watchlist remains as an optional priority lane, not an eligibility requirement.

The system must remain:

- Robinhood Agentic-only.
- Read-only during discovery.
- Dry-run/simulation-safe until explicit future live enablement.
- Fail-closed when required risk or market data is unavailable.
- Account-capital-aware.
- Bounded so a broad-market sweep does not create uncontrolled MCP traffic.
- Neutral about investment decisions: ranking is mechanical and does not constitute a recommendation.

## 2. Current constraints and invariants

Existing TradeHub invariants remain unchanged:

- No naked option selling.
- Known maximum loss is required before a candidate may be approval-ready.
- Default per-trade maximum loss remains 5% of risk equity.
- Default aggregate open-position maximum loss remains 20% of risk equity.
- Default daily realized-loss breaker remains 10% of risk equity.
- Maximum concurrent positions remains 1 in Phase 1.
- Spreads remain disabled for the current Robinhood account.
- Covered-call promotion remains disabled until whole-position stock cost-basis/downside risk is authoritative.
- Simulation capital and live-account capital remain isolated.
- Simulation proposals/positions can never be executed as Robinhood orders.
- Robinhood market/account/order access remains behind the existing MCP client boundary.

## 3. Robinhood capabilities used

The scanner must use only tools advertised by the authenticated Robinhood Agentic MCP session.

The design relies on Robinhood's documented scanner and market-data tools:

### Scanner tools

- `get_scans`
- `get_scanner_filter_specs`
- `create_scan`
- `run_scan`
- `update_scan_filters`
- `update_scan_config`

### Market-data and validation tools

- `get_equity_quotes`
- `get_equity_fundamentals`
- `get_equity_tradability`
- `get_earnings_calendar`
- `get_earnings_results`
- `get_option_chains`
- `get_option_instruments`
- `get_option_quotes`

The implementation must inspect the live MCP tool catalog and schemas at runtime rather than assume parameter names. `get_scanner_filter_specs` is the source of truth for scanner filter names, value formats, and supported sorts.

Official reference:
https://robinhood.com/us/en/support/articles/trading-with-your-agent/

## 4. High-level architecture

The market-universe scanner is a staged pipeline:

```text
Robinhood scanner filter specs
            |
            v
Managed TradeHub market scans
            |
            v
Broad equity universe results
            |
            v
Cheap equity prefilter
  - tradability
  - minimum price
  - stock liquidity
  - market cap when available
  - earnings exclusion
  - capital-aware prioritization
            |
            v
Bounded symbol queue
            |
            v
Existing option-chain scanner
            |
            v
Option contract filters
  - DTE
  - delta
  - OI
  - volume
  - spread
            |
            v
Existing RiskManager
  - buying power
  - per-trade max loss
  - portfolio max loss
  - daily breaker
  - concurrent positions
            |
            v
Mechanical matches / near misses
            |
            v
Simulation or approval workflow
```

## 5. Market universe

### 5.1 Definition

"Whole market" means the broad Robinhood-supported U.S. equity universe that can be discovered through the Agentic scanner, subject to explicit TradeHub eligibility filters.

It does not mean every listed security is entitled to an option-chain call. Securities that fail cheap equity-level filters must be rejected before expensive option-chain retrieval.

### 5.2 Watchlist role

The existing `STRATEGY_WATCHLIST` remains supported but changes role:

- Watchlist symbols are scanned first.
- They are not the only symbols eligible for TradeHub.
- A symbol outside the watchlist may become a mechanical match.
- A watchlist symbol receives no risk exception or scoring bonus unless a future design explicitly adds one.

## 6. Managed Robinhood scans

TradeHub will own one or more saved Robinhood scans with stable names prefixed by `TradeHub:`.

Because the exact Robinhood scanner result limits and filter names are schema-dependent, TradeHub must not assume that a single saved scan can enumerate the entire eligible universe.

The scanner service must:

1. Call `get_scanner_filter_specs`.
2. Build a semantic map of available filters and sorts.
3. Reuse existing TradeHub-owned scans when compatible.
4. Create or update scans when filters/config change.
5. Run scans in bounded slices when necessary.
6. Deduplicate symbols across slices.
7. Persist the last successful universe snapshot and per-symbol scan status.

Examples of possible slices include price bands or sort rotations. The implementation must choose slices from filters actually advertised by Robinhood rather than hard-code unsupported scanner fields.

## 7. Default equity-level discovery filters

These are TradeHub mechanical defaults, not investment recommendations.

- Minimum underlying price: **$5.00**
- Minimum average stock volume: **1,000,000 shares/day**, when a compatible scanner/fundamental field is available
- Minimum market capitalization: **$1 billion**, when available
- Tradability: must pass Robinhood tradability checks
- Earnings: reject new-entry candidates when the company has an earnings report before option expiration
- Missing required discovery data: fail closed for the affected rule
- ETFs may pass without an earnings event if all other requirements pass

If a desired filter is not exposed by `get_scanner_filter_specs`, TradeHub may enforce it downstream using an official Robinhood market-data tool. It must not silently skip the rule.

## 8. Capital-aware discovery

The scanner should avoid unnecessary option-chain work when an underlying is extremely unlikely to produce a CSP that fits the active risk-capital mode.

The authoritative CSP screening budget is:

```text
min(
    active buying power,
    per-trade remaining loss capacity,
    remaining aggregate portfolio-loss capacity
)
```

The exact option candidate still uses:

```text
estimated max loss =
(strike - credit per share) * multiplier * contracts
```

The broad equity stage may use capital as a prioritization signal, but it must not treat spot price as a hard substitute for strike/max-loss risk. A higher-priced stock may still have an out-of-the-money strike that fits risk.

Therefore:

- Capital-aware screening may lower priority for symbols far above the approximate CSP strike ceiling.
- It must not permanently exclude them solely from spot price unless the exclusion can be proven from available option/strike data.
- Full acceptance/rejection remains contract-level in the existing candidate engine and RiskManager.

## 9. Option deep-scan defaults

The broad-market scanner will use stricter initial liquidity defaults than the current development watchlist scan.

Mechanical defaults:

- DTE: **21-45 days**
- Absolute short-put delta: **0.15-0.30**
- Option open interest: **>= 500**
- Option daily volume: **>= 50**
- Bid/ask spread: **<= 10% of midpoint**
- Contracts: **1**
- Missing Greeks: reject
- Missing bid/ask data: reject
- Missing strike/expiration/multiplier: reject
- Earnings before expiration: reject new entry
- Unsupported strategy: reject

These values must be configuration settings, not literals buried in scanner code.

Existing Phase 1 risk limits remain separate hard gates and must never be weakened automatically to increase match count.

## 10. Scanner scheduling and batching

A whole-market sweep must be bounded.

### 10.1 Scan cycle

A market sweep has these states:

- `queued`
- `discovering`
- `deep_scanning`
- `complete`
- `partial`
- `failed`

Each sweep gets a persistent ID and timestamps.

### 10.2 Concurrency

Initial defaults:

- Equity/metadata batches: up to the MCP-supported batch size for the relevant tool.
- Option deep scans: **2 concurrent symbols** initially.
- Global maximum deep-scan symbols per cycle: configurable.
- Retry transient MCP/SSE failures with the existing bounded retry pattern.
- Do not retry deterministic schema/validation failures indefinitely.

### 10.3 Fair coverage

TradeHub must not repeatedly scan only the same top-ranked symbols.

The scheduler will maintain:

- last deep-scan time per symbol,
- last result state,
- consecutive error count,
- last mechanical-match time,
- priority flag for watchlist symbols.

The queue should combine:

1. watchlist priority,
2. never-scanned/new symbols,
3. stale symbols,
4. previously promising symbols.

This ensures broad-market coverage over successive sweeps.

## 11. Persistence model

Add persistent scanner tables/models rather than keep universe state only in memory.

### MarketScanRun

Stores:

- id
- status
- started_at
- completed_at
- risk_capital_mode
- risk_equity at start
- symbols_discovered
- symbols_prefiltered
- symbols_deep_scanned
- contracts_evaluated
- matches_found
- error_count
- config snapshot

### MarketScanSymbol

Stores one row per run/symbol:

- run_id
- symbol
- source slice
- priority/watchlist flag
- equity screen status
- equity rejection reasons
- earnings status
- option scan status
- market filter pass count
- mechanical match count
- near-miss count
- tool errors
- started_at/completed_at

### MarketOpportunitySnapshot

Stores the latest mechanical candidate snapshot needed by the API/dashboard:

- symbol
- option_id
- strategy
- expiration
- strike
- delta
- bid/ask/mark
- OI
- volume
- spread
- estimated credit
- estimated collateral
- estimated max loss
- risk approval status
- risk rejection reasons
- score
- scan timestamp
- source scan run

These records are informational and do not themselves create a TradeProposal.

## 12. Market opportunity ranking

The existing candidate score remains a mechanical market-quality score, not an investment ranking.

The market-wide endpoint may sort mechanical matches by that score after all hard filters and risk gates pass.

No scanner result may use labels such as:

- best stock
- best trade
- recommended
- safe
- guaranteed

Allowed language:

- mechanical match
- passes configured filters
- risk-approved under current TradeHub rules
- near miss
- rejected by configured rule

## 13. APIs

### GET /api/market-scanner/status

Returns current/last scan status and aggregate counts.

### POST /api/market-scanner/run

Starts one bounded market scan cycle.

Requirements:

- Robinhood MCP enabled.
- Only one active whole-market scan at a time.
- Returns the scan run ID.
- Does not place orders.
- In initial implementation, scan execution may be synchronous/bounded or driven by an in-process worker, but state must be persisted so restart behavior is explicit.

### GET /api/market-scanner/runs/{run_id}

Returns aggregate scan metrics and errors.

### GET /api/market-scanner/opportunities

Returns latest mechanical matches across the broad universe.

Filters may include:

- symbol
- max age
- strategy
- expiration window
- risk-capital mode

### GET /api/market-scanner/near-misses

Returns rejected candidates with exact rejection stage/reasons and minimum-equity information where calculable.

Existing `/api/opportunities/account-fit` remains for direct/watchlist ad hoc testing.

## 14. Dashboard design

Add a Market Scanner section showing:

- scan status,
- last completed sweep,
- discovered symbol count,
- equity-screen survivors,
- symbols deep-scanned,
- contracts evaluated,
- mechanical matches,
- near misses,
- MCP/tool error count,
- active risk-capital mode,
- active risk equity,
- current 5% trade limit,
- current 20% portfolio limit.

The opportunities table should show:

- symbol
- expiration
- strike
- delta
- credit
- max loss
- score
- risk status
- scan age

Watchlist membership may be shown as metadata only.

## 15. Earnings handling

For single stocks, TradeHub should reject new option-selling entries when an earnings report is scheduled before the option expiration.

Data source priority:

1. `get_earnings_calendar` for market-wide scheduling.
2. `get_earnings_results` for symbol-specific confirmation when needed.

If earnings data is required but unavailable, the candidate fails closed.

ETFs are exempt from corporate earnings-event checks.

## 16. Error handling

### Scanner schema changes

If Robinhood changes scanner filters:

- refresh `get_scanner_filter_specs`,
- reconcile the managed scan,
- persist an audit/error record,
- fail closed on required filters that cannot be reconstructed.

### Partial MCP failures

A transient failure for one symbol must not invalidate the entire market scan.

The run becomes `partial` if:

- at least one symbol completed successfully, and
- one or more symbols failed after bounded retries.

### Authentication failure

OAuth/auth failures stop the scan and mark it `failed`. TradeHub must not substitute cached data for a fresh scan without clearly reporting staleness.

### Stale opportunities

Opportunity records must carry `scanned_at`. Promotion continues to re-scan the selected symbol and re-run authoritative risk, so a stale market snapshot can never directly become an approval-ready proposal.

## 17. Security and execution boundary

Market discovery must never call write/order tools.

Allowed scanner/deep-scan operations are read-only plus Robinhood saved-scan management tools.

A market opportunity is not an order.

Promotion remains the existing explicit boundary:

```text
MarketOpportunitySnapshot
        |
        v
fresh symbol rescan
        |
        v
authoritative risk
        |
        v
TradeProposal
        |
        v
manual approval
        |
        v
simulation lifecycle
```

No market-scanner component receives or calls `place_option_order`.

Simulation-mode execution prohibition remains enforced by the existing execution gate.

## 18. Account-capital guidance surfaced by TradeHub

TradeHub should display capital mechanics without telling the operator what investment decision to make.

For one standard 100-share CSP, a rough pre-premium strike ceiling from the 5% rule is:

```text
approximate strike ceiling =
(account equity * 0.05) / 100
```

Examples:

| Risk equity | 5% trade-loss cap | Approx. pre-premium CSP strike ceiling |
| ---: | ---: | ---: |
| $10,000 | $500 | $5 |
| $25,000 | $1,250 | $12.50 |
| $50,000 | $2,500 | $25 |
| $75,000 | $3,750 | $37.50 |
| $100,000 | $5,000 | $50 |
| $150,000 | $7,500 | $75 |
| $250,000 | $12,500 | $125 |

Actual contract risk remains `(strike - premium/share) * multiplier * contracts`.

Robinhood's CSP collateral rule separately requires enough cash to buy the underlying shares at the strike if assigned.

Official reference:
https://robinhood.com/us/en/support/articles/360001227606/

The UI should distinguish:

- broker/account eligibility,
- synchronized buying power,
- TradeHub per-trade risk capacity,
- TradeHub aggregate portfolio capacity,
- approximate CSP strike capacity.

It must not present a deposit amount as guaranteed to produce profitable or suitable trades.

## 19. Configuration

Planned configuration keys:

```text
MARKET_SCANNER_ENABLED=false
MARKET_SCANNER_MAX_DEEP_SYMBOLS=100
MARKET_SCANNER_OPTION_CONCURRENCY=2
MARKET_SCANNER_MIN_PRICE=5
MARKET_SCANNER_MIN_AVG_VOLUME=1000000
MARKET_SCANNER_MIN_MARKET_CAP=1000000000
MARKET_SCANNER_EXCLUDE_EARNINGS=true

STRATEGY_MIN_DTE=21
STRATEGY_MAX_DTE=45
STRATEGY_SHORT_DELTA_MIN=0.15
STRATEGY_SHORT_DELTA_MAX=0.30
STRATEGY_MIN_OPEN_INTEREST=500
STRATEGY_MIN_VOLUME=50
LIQUIDITY_MAX_SPREAD_PCT=0.10
```

Existing risk settings remain unchanged.

The initial release keeps `MARKET_SCANNER_ENABLED=false` until tests pass and the operator explicitly enables it.

## 20. Testing requirements

### Scanner schema tests

- Filter-spec parsing.
- Missing desired scanner filter.
- Unsupported sort.
- Scanner tool not advertised.
- Saved TradeHub scan reuse/update.

### Universe tests

- Deduplicate symbols from multiple scan slices.
- Watchlist symbols receive priority but no eligibility exemption.
- Tradability failure rejects symbol.
- Missing required fundamentals fails closed.
- Earnings-before-expiration rejects single stock.
- ETF bypasses earnings check.

### Deep-scan tests

- Enforce bounded concurrency.
- Stop at configured per-cycle deep-scan cap.
- Partial symbol failure does not fail successful symbols.
- Fair/stale scheduling prevents starvation.

### Risk tests

- Live and simulation capital modes remain isolated.
- Candidate max loss uses actual multiplier.
- 5% per-trade limit unchanged.
- 20% aggregate limit unchanged.
- Pending/approved/simulated positions continue reserving risk.
- Promotion re-scans and re-runs risk regardless of cached market result.

### Safety tests

- No market-scanner code path can call `review_option_order` or `place_option_order`.
- Simulation execution gate remains blocked.
- Stale snapshots cannot be promoted without fresh rescan.
- Missing earnings data fails closed when earnings exclusion is enabled.

## 21. Rollout sequence

1. Add scanner schema discovery and managed-scan service.
2. Add persistence for scan runs/symbols/opportunity snapshots.
3. Add broad equity discovery with bounded slices.
4. Add fundamentals/tradability/earnings prefilter.
5. Connect bounded option deep-scan queue to the existing candidate engine.
6. Persist mechanical matches/near misses.
7. Add market-scanner APIs.
8. Add dashboard scanner status/opportunity views.
9. Run in simulation mode only.
10. Compare market-wide results against existing direct symbol scans.
11. Enable scheduled/recurring sweeps only after stability is demonstrated.

## 22. Non-goals for this design

This design does not:

- enable live trading,
- change the 5%/20%/10% risk limits,
- enable spreads,
- enable covered-call promotion,
- add long calls/puts,
- infer investor suitability,
- choose a trade for the operator,
- guarantee full exchange-level enumeration if Robinhood's scanner API itself exposes a bounded universe,
- bypass Robinhood option permissions,
- use unofficial Robinhood APIs,
- add another broker.

## 23. Success criteria

The feature is successful when:

1. TradeHub can discover candidate symbols without a user watchlist.
2. A completed sweep covers the broad eligible Robinhood scanner universe over bounded slices.
3. Expensive option-chain calls are limited to symbols that survive cheap equity-level screening.
4. Results persist across restarts.
5. The API/dashboard explains where symbols/contracts were rejected.
6. Watchlist symbols are prioritized but not privileged.
7. Existing RiskManager invariants remain unchanged.
8. Promotion always performs a fresh symbol rescan and authoritative risk check.
9. Simulation and live-account risk remain isolated.
10. No discovery path can place a Robinhood order.
