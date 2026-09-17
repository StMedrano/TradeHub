from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

class StrategyType(StrEnum):
    CASH_SECURED_PUT = "cash_secured_put"
    COVERED_CALL = "covered_call"
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    IRON_CONDOR = "iron_condor"
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    DEBIT_SPREAD = "debit_spread"

class ProposalStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    DRY_RUN_LOGGED = "dry_run_logged"
    EXECUTING = "executing"
    FILLED = "filled"
    ABANDONED = "abandoned"
    PAUSED = "paused"

@dataclass(frozen=True)
class TradeIntent:
    strategy: StrategyType
    underlying: str
    contracts: int
    known_max_loss: Decimal
    shares_held: int = 0
    is_defined_risk: bool = True
    has_short_call: bool = False
    has_short_put: bool = False
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass(frozen=True)
class AccountRiskSnapshot:
    equity: Decimal
    open_position_max_loss: Decimal
    realized_pnl_today: Decimal
    concurrent_positions: int
    paused_underlyings: frozenset[str] = frozenset()

@dataclass(frozen=True)
class RiskPolicy:
    max_trade_loss_pct: Decimal
    max_portfolio_loss_pct: Decimal
    daily_loss_breaker_pct: Decimal
    max_concurrent_positions: int
    phase: int
    require_approval: bool

@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    trade_max_loss: Decimal
    trade_limit: Decimal
    projected_portfolio_max_loss: Decimal
    portfolio_limit: Decimal
    realized_loss_today: Decimal
    daily_loss_limit: Decimal
