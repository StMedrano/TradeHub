from dataclasses import dataclass
from enum import StrEnum

class LegState(StrEnum):
    PLANNED = "planned"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    UNWIND_REQUIRED = "unwind_required"
    UNWOUND = "unwound"

@dataclass
class LegExecution:
    contract_id: str
    side: str
    effect: str
    state: LegState = LegState.PLANNED
    robinhood_order_id: str | None = None

@dataclass
class MultiLegPlan:
    """TradeHub strategy state for Robinhood single-leg option orders."""

    strategy_id: str
    risk_reducing_leg: LegExecution
    second_leg: LegExecution

    def second_leg_allowed(self) -> bool:
        return self.risk_reducing_leg.state == LegState.FILLED

    def mark_second_leg_timeout(self) -> None:
        if self.risk_reducing_leg.state == LegState.FILLED:
            self.second_leg.state = LegState.CANCELLED
            self.risk_reducing_leg.state = LegState.UNWIND_REQUIRED
