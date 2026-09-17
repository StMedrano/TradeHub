# TradeHub architecture

TradeHub is intentionally Robinhood Agentic-only.

## System boundary

Robinhood Trading MCP feeds account, position, quote, chain, and order data into TradeHub. Strategy code produces immutable trade intents. Those intents must pass the risk manager and, by default, manual approval before the execution layer can review or place an order.

## Risk invariants

- No naked option selling.
- Known max loss must be computable before approval.
- Per-trade max-loss cap is configurable.
- Aggregate open-position max-loss cap is configurable.
- Daily realized-loss breaker is configurable.
- Assignment/early-assignment events pause new entries for the underlying.

## Robinhood-only invariant

There is no multi-broker adapter. The external integration boundary is RobinhoodTradingMCP and the supported operations map directly to Robinhood Trading MCP tools.

Strategy code never receives the Robinhood client directly.

## Multi-leg invariant

TradeHub treats Robinhood option execution as single-leg and owns the strategy-level state machine.

For spreads and condors:

1. Build the full strategy plan and compute known max loss.
2. Re-run risk before execution.
3. Submit the risk-reducing long leg first.
4. Confirm the first leg is filled.
5. Submit the second leg.
6. If the second leg cannot fill within timeout/slippage bounds, cancel it.
7. Mark the first leg UNWIND_REQUIRED and close it.
8. Never intentionally leave a naked short leg.

## Assignment invariant

TradeHub never attempts to autonomously resolve an assignment.

On assignment or deep-ITM/approaching-expiration risk:

1. Create a high-severity audit event.
2. Send SMS/push when the alert provider is enabled.
3. Persist an underlying pause.
4. Display the hold in the dashboard.
5. Require manual acknowledgement.
6. Do not place a stock/options order intended to resolve the assignment.
