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

## Dashboard UI

TradeHub now ships a React 19 + Vite + Radix Themes frontend that is compiled into
the production Docker image and served by FastAPI.

The dashboard includes:

- Preview-matched dark Robinhood-style layout
- Sidebar navigation
- Account metric cards
- Risk utilization and hard-limit cards
- Position overview
- Trade opportunity workspace
- Approval queue with approve/reject dialog
- Browser approval notifications
- Assignment/expiration hold acknowledgement
- Activity/audit table
- Robinhood MCP / rollout mode status
- Responsive tablet/mobile layout

When Robinhood MCP read access is disabled, brokerage account-value fields display
as unavailable instead of using fake production data.

To apply UI updates on an existing server:

```bash
cd /opt/TradeHub
git pull
docker compose up -d --build
```


## Robinhood authentication

TradeHub uses Robinhood's official Trading MCP OAuth flow. OAuth state is stored
inside the Docker volume `tradehub-secrets`; it is not stored in Git.

Keep TradeHub in dry-run while connecting:

```env
TRADING_MODE=dry_run
PHASE=0
ROBINHOOD_MCP_ENABLED=false
```

Run the one-time interactive OAuth bootstrap:

```bash
cd /opt/TradeHub
docker compose run --rm -it app python -m app.robinhood.auth_cli
```

The command prints a Robinhood authorization URL. Open it on a desktop browser,
complete Robinhood authorization, then copy the full localhost callback URL from
the browser address bar and paste it back into the terminal.

After the command reports success, edit `.env`:

```env
ROBINHOOD_MCP_ENABLED=true
TRADING_MODE=dry_run
PHASE=0
```

Then rebuild/restart:

```bash
docker compose up -d --build
docker compose logs -f app
```

Verify the read-only connection:

```bash
curl http://localhost:8787/api/robinhood/status
curl -X POST http://localhost:8787/api/robinhood/sync
```

The background synchronizer only invokes Robinhood read tools. It does not call
`review_option_order`, `place_option_order`, or `cancel_option_order`.

### Read-sync data currently used by the dashboard

- Robinhood account discovery
- Agentic account identification
- Portfolio total value
- Buying power
- Cash
- Options value
- Open equity position count
- Open option position count
- Open option order count

P&L, full position detail, chains, quotes, Greeks, IV rank, and strategy scanning
are the next read-only milestones.
