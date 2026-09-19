from dataclasses import dataclass
from app.config import RiskCapitalMode, TradingMode

@dataclass(frozen=True)
class ExecutionGate:
    mode: TradingMode
    phase: int
    require_approval: bool
    risk_capital_mode: RiskCapitalMode = RiskCapitalMode.LIVE_ACCOUNT

    def may_place_order(self, approved: bool) -> tuple[bool, str]:
        if self.risk_capital_mode == RiskCapitalMode.SIMULATION:
            return False, "Simulation capital mode: real Robinhood orders are prohibited."
        if self.mode != TradingMode.LIVE:
            return False, "Dry-run mode: Robinhood place_option_order is disabled."
        if self.phase == 0:
            return False, "Rollout Phase 0 prohibits live orders."
        if self.require_approval and not approved:
            return False, "Manual approval is required."
        return True, "Live execution gate passed."
