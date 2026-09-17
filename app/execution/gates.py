from dataclasses import dataclass
from app.config import TradingMode

@dataclass(frozen=True)
class ExecutionGate:
    mode: TradingMode
    phase: int
    require_approval: bool

    def may_place_order(self, approved: bool) -> tuple[bool, str]:
        if self.mode != TradingMode.LIVE:
            return False, "Dry-run mode: Robinhood place_option_order is disabled."
        if self.phase == 0:
            return False, "Rollout Phase 0 prohibits live orders."
        if self.require_approval and not approved:
            return False, "Manual approval is required."
        return True, "Live execution gate passed."
