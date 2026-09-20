# TradeHub roadmap

## Milestone 1 — Robinhood-only rebuild
- [x] FastAPI application
- [x] Docker/Compose
- [x] Postgres
- [x] Risk manager
- [x] Approval queue
- [x] Browser approval notifications
- [x] Audit log
- [x] Underlying pause/acknowledgement
- [x] Dry-run/live execution gate
- [x] Robinhood MCP client boundary
- [x] Price-walk helper
- [x] Multi-leg state model
- [x] Tests and GitHub Actions

## Milestone 2 — authenticated Robinhood read path
- [x] OAuth/token persistence for the Robinhood MCP session
- [x] Account/balance normalization
- [~] Equity holdings sync (detail view still pending)
- [~] Option chains/instruments (schema-aware read scanner added)
- [~] Option quotes/IV/Greeks (schema-aware read scanner added)
- [~] Option positions sync (detail view still pending)
- [~] Option order sync (history/detail view still pending)
- [ ] Expiration calendar
- [ ] Assignment/event detection

## Milestone 3 — strategy engine
- [x] Authoritative server-side Phase 1 risk state when no option exposure/orders are open
- [x] Daily realized-P&L read gate for circuit-breaker decisions
- [x] Dry-run CSP promotion into approval queue
- [x] Candidate pass/fail diagnostics
- [ ] IV rank/percentile input
- [ ] Directional signal interface
- [x] Liquidity gate for Phase 1 candidate screening
- [x] Covered-call preference when sufficient shares exist
- [x] CSP candidate plugin (dry-run candidate only)
- [x] Covered-call plugin (dry-run candidate only)
- [ ] Long call/put plugin
- [ ] Debit spread plugin
- [ ] Bull put/bear call plugin
- [ ] Iron condor plugin

## Milestone 3A — whole-market discovery
- [x] Robinhood Agentic saved-scan discovery adapter
- [x] Price-sliced market discovery with downstream hard-filter enforcement
- [x] Watchlist-as-priority rather than watchlist-as-universe
- [x] Robinhood tradability, minimum-price, stock-volume, and market-cap prefilters
- [x] Single-stock earnings-before-expiration exclusion
- [x] Persisted scan runs, per-symbol checkpoints, opportunities, and near misses
- [x] Fair stale/never-scanned queue scheduling
- [x] Bounded option-chain deep-scan concurrency
- [x] Reuse of PhaseOneCandidateEngine and RiskManager
- [x] Simulation/live risk-capital isolation
- [x] Restart recovery and single-active-run enforcement
- [x] Partial MCP failure handling without discarding successful symbols
- [x] Dedicated market-scanner API
- [x] Whole-market scanner dashboard with persisted progress
- [x] Fresh-rescan promotion boundary for cached opportunities
- [x] Scanner order-tool safety regression
- [x] Disabled-by-default rollout via MARKET_SCANNER_ENABLED=false
- [ ] Production-scale sweep tuning from observed Robinhood MCP latency/rate limits
- [ ] Authentik/operator authorization before public exposure

## Milestone 4 — paging and operator controls
- [ ] Pushover provider
- [ ] Twilio provider
- [ ] Circuit-breaker page
- [ ] Assignment page
- [ ] Early-assignment-risk page
- [ ] Manual global halt/reset
- [ ] Operator authentication

## Milestone 5 — Phase 1 live
- [ ] Explicit two-step live enablement
- [ ] review_option_order integration
- [ ] place_option_order integration
- [ ] Fill polling
- [ ] Mid-price entry
- [ ] Bounded price walk
- [ ] Cancel/abandon behavior
- [ ] CSP and covered calls only
- [ ] Maximum one concurrent position

## Milestone 6 — Phase 2
- [ ] Long calls/puts and debit spreads
- [ ] Credit vertical sequencing
- [ ] Iron condor sequencing
- [ ] Long-leg-first enforcement
- [ ] Automatic unwind if later leg fails
- [ ] Restart recovery for partially completed strategies
- [ ] Strategy-level P&L/Greeks tracking
