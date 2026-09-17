# TradeHub

TradeHub is a self-hosted **Robinhood Agentic Trading-only** platform for defined-risk options automation.

This repository is intentionally Robinhood-only. It is designed around Robinhood's Trading MCP and a dedicated Robinhood Agentic account. It does not support Alpaca, IBKR, unofficial Robinhood APIs, or a multi-broker abstraction.

## Safety defaults

- Dry-run mode enabled by default
- Live order placement disabled until explicitly enabled
- Manual approval required by default
- Defined-risk strategies only; naked option selling is prohibited
- Default max loss per trade: 5% of account equity
- Default aggregate open-position max-loss cap: 20% of account equity
- Default daily realized-loss circuit breaker: 10% of account equity
- Phase 1: cash-secured puts and covered calls only, maximum 1 concurrent position
- Phase 2: long calls/puts, debit spreads, credit verticals, and iron condors
- Assignment is never automatically resolved
- Multi-leg strategies are managed by TradeHub while Robinhood MCP option orders are sequenced as individual legs

## Required order path

Strategy/scoring engine → immutable TradeIntent → Risk Manager → Approval Queue → Execution Gate → Robinhood review_option_order → Execution Engine → Robinhood place_option_order

No strategy module receives direct write access to Robinhood.

## Production deployment

```bash
git clone https://github.com/StMedrano/TradeHub.git
cd TradeHub
cp .env.example .env
nano .env
docker compose up -d --build
docker compose run --rm app pytest -q
```

Dashboard default:

```text
http://SERVER_IP:8787
```

Keep the dashboard on a trusted management path or authenticated reverse proxy. Do not expose it directly to the public Internet.

## Current rebuild milestone

Implemented:

- FastAPI dashboard/API
- Postgres persistence
- Manual approval queue
- Browser approval notifications
- Configurable risk manager
- Daily circuit-breaker logic
- Underlying pause/acknowledgement for assignment or expiration risk
- Dry-run/live execution gate
- Mid-price and bounded price-walk helpers
- Multi-leg sequencing state model
- Audit events
- Robinhood Trading MCP client boundary
- Docker/Compose deployment
- GitHub Actions tests

Live order placement remains disabled by default.