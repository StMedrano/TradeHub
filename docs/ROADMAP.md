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
- [ ] OAuth/token persistence for the Robinhood MCP session
- [ ] Account/balance normalization
- [ ] Equity holdings and share counts
- [ ] Option chains/instruments
- [ ] Option quotes
- [ ] Option positions
- [ ] Open/historical orders
- [ ] Expiration calendar
- [ ] Assignment/event detection

## Milestone 3 — strategy engine
- [ ] IV rank/percentile input
- [ ] Directional signal interface
- [ ] Liquidity gate
- [ ] Covered-call preference when sufficient shares exist
- [ ] CSP candidate plugin
- [ ] Covered-call plugin
- [ ] Long call/put plugin
- [ ] Debit spread plugin
- [ ] Bull put/bear call plugin
- [ ] Iron condor plugin

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
