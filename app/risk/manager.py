from decimal import Decimal
from app.domain.models import AccountRiskSnapshot, RiskDecision, RiskPolicy, StrategyType, TradeIntent

PHASE_1_STRATEGIES = {
    StrategyType.CASH_SECURED_PUT,
    StrategyType.COVERED_CALL,
}

class RiskManager:
    """Pure risk decision engine. It cannot place orders."""

    def evaluate(self, intent: TradeIntent, account: AccountRiskSnapshot, policy: RiskPolicy) -> RiskDecision:
        reasons: list[str] = []

        if account.equity <= 0:
            reasons.append("Account equity must be greater than zero.")
        if intent.contracts <= 0:
            reasons.append("Contract quantity must be greater than zero.")
        if intent.known_max_loss <= 0:
            reasons.append("Known max loss must be positive and bounded.")
        if not intent.is_defined_risk:
            reasons.append("Undefined-risk or naked option positions are prohibited.")

        if intent.has_short_call and intent.strategy not in {
            StrategyType.COVERED_CALL,
            StrategyType.BEAR_CALL_SPREAD,
            StrategyType.IRON_CONDOR,
        }:
            reasons.append("Naked short calls are prohibited.")

        if intent.strategy == StrategyType.COVERED_CALL:
            required_shares = intent.contracts * 100
            if intent.shares_held < required_shares:
                reasons.append(
                    f"Covered call requires {required_shares} owned shares; snapshot shows {intent.shares_held}."
                )

        if intent.strategy == StrategyType.CASH_SECURED_PUT and not intent.has_short_put:
            reasons.append("Cash-secured put must identify its short put leg.")

        if intent.underlying.upper() in {x.upper() for x in account.paused_underlyings}:
            reasons.append(f"{intent.underlying.upper()} is paused pending manual acknowledgement.")

        if policy.phase == 1 and intent.strategy not in PHASE_1_STRATEGIES:
            reasons.append("Strategy is disabled in rollout Phase 1.")

        if account.concurrent_positions >= policy.max_concurrent_positions:
            reasons.append("Maximum concurrent position count has been reached.")

        equity = max(account.equity, Decimal("0"))
        trade_limit = equity * policy.max_trade_loss_pct
        portfolio_limit = equity * policy.max_portfolio_loss_pct
        daily_loss_limit = equity * policy.daily_loss_breaker_pct

        trade_max_loss = max(intent.known_max_loss, Decimal("0"))
        projected_portfolio = account.open_position_max_loss + trade_max_loss
        realized_loss_today = max(-account.realized_pnl_today, Decimal("0"))

        if trade_max_loss > trade_limit:
            reasons.append(f"Trade max loss {trade_max_loss} exceeds per-trade limit {trade_limit}.")
        if projected_portfolio > portfolio_limit:
            reasons.append("Projected aggregate max loss exceeds portfolio limit.")
        if daily_loss_limit > 0 and realized_loss_today >= daily_loss_limit:
            reasons.append("Daily realized-loss circuit breaker is tripped; new entries are halted.")

        return RiskDecision(
            approved=not reasons,
            reasons=tuple(reasons),
            trade_max_loss=trade_max_loss,
            trade_limit=trade_limit,
            projected_portfolio_max_loss=projected_portfolio,
            portfolio_limit=portfolio_limit,
            realized_loss_today=realized_loss_today,
            daily_loss_limit=daily_loss_limit,
        )
