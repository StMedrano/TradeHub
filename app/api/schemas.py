from decimal import Decimal
from pydantic import BaseModel, Field
from app.domain.models import StrategyType

class RiskCheckRequest(BaseModel):
    strategy: StrategyType
    underlying: str = Field(min_length=1, max_length=16)
    contracts: int = Field(gt=0)
    known_max_loss: Decimal = Field(gt=0)
    shares_held: int = Field(default=0, ge=0)
    has_short_call: bool = False
    has_short_put: bool = False
    is_defined_risk: bool = True
    account_equity: Decimal = Field(gt=0)
    open_position_max_loss: Decimal = Field(default=Decimal("0"), ge=0)
    realized_pnl_today: Decimal = Decimal("0")
    concurrent_positions: int = Field(default=0, ge=0)
    paused_underlyings: list[str] = []

class ApprovalAction(BaseModel):
    actor: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)

class PauseAck(BaseModel):
    actor: str = Field(min_length=1, max_length=128)



class CandidatePromotionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    option_id: str = Field(min_length=1, max_length=128)



class SimulationCloseRequest(BaseModel):
    exit_debit: Decimal = Field(ge=0)
    actor: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=2000)
