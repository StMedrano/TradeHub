from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import AccountRiskSnapshot
from app.persistence.models import SimulationPosition, TradeProposal, UnderlyingPause
from app.robinhood.read_service import RobinhoodSnapshot


ACTIVE_PROPOSAL_STATUSES = {
    "pending_approval",
    "approved",
    "executing",
}


@dataclass(frozen=True)
class AuthoritativeRiskState:
    authoritative: bool
    snapshot: AccountRiskSnapshot | None
    reasons: tuple[str, ...]


class PortfolioRiskStateService:
    """Build server-side risk state; never trusts browser-supplied account values."""

    def build(
        self,
        db: Session,
        robinhood: RobinhoodSnapshot,
    ) -> AuthoritativeRiskState:
        reasons: list[str] = []

        if robinhood.connection_state not in {"connected", "degraded"}:
            reasons.append("Robinhood read state is not connected.")

        if robinhood.equity is None or robinhood.equity <= 0:
            reasons.append("Account equity is unavailable.")

        if not robinhood.realized_pnl_authoritative:
            reasons.append("Today's realized P&L is not authoritative.")

        active_proposals = db.scalars(
            select(TradeProposal).where(
                TradeProposal.status.in_(ACTIVE_PROPOSAL_STATUSES),
                ~TradeProposal.id.like("sim-%"),
            )
        ).all()

        concurrent_positions = robinhood.open_option_positions + len(active_proposals)

        # Phase 1 currently allows one option strategy at a time. Until the
        # position-state model can reconstruct max loss for every live strategy,
        # any existing option exposure/order makes aggregate max-loss unknown.
        if robinhood.open_option_positions > 0:
            reasons.append(
                "Open option positions exist; aggregate strategy max loss "
                "is not yet reconstructed authoritatively."
            )

        if robinhood.open_orders > 0:
            reasons.append(
                "Open option orders exist; reserved/execution risk is not yet "
                "reconstructed authoritatively."
            )

        if active_proposals:
            reasons.append(
                "An active TradeHub proposal already reserves the Phase 1 slot."
            )

        pauses = db.scalars(
            select(UnderlyingPause).where(
                UnderlyingPause.acknowledged.is_(False)
            )
        ).all()
        paused = frozenset(row.symbol.upper() for row in pauses)

        if reasons:
            return AuthoritativeRiskState(
                authoritative=False,
                snapshot=None,
                reasons=tuple(reasons),
            )

        return AuthoritativeRiskState(
            authoritative=True,
            snapshot=AccountRiskSnapshot(
                equity=Decimal(str(robinhood.equity)),
                open_position_max_loss=Decimal("0"),
                realized_pnl_today=Decimal(str(robinhood.realized_pnl_today)),
                concurrent_positions=concurrent_positions,
                paused_underlyings=paused,
            ),
            reasons=(),
        )


portfolio_risk_state_service = PortfolioRiskStateService()



class SimulationRiskStateService:
    """Build an isolated virtual risk ledger for dry-run simulation."""

    def build(
        self,
        db: Session,
        *,
        capital: Decimal,
    ) -> AuthoritativeRiskState:
        reasons: list[str] = []

        if capital <= 0:
            reasons.append("Simulation capital must be greater than zero.")

        active_proposals = db.scalars(
            select(TradeProposal).where(
                TradeProposal.status.in_(ACTIVE_PROPOSAL_STATUSES),
                TradeProposal.id.like("sim-%"),
            )
        ).all()

        open_positions = db.scalars(
            select(SimulationPosition).where(
                SimulationPosition.status == "open"
            )
        ).all()

        open_position_max_loss = sum(
            (Decimal(str(row.known_max_loss)) for row in active_proposals),
            Decimal("0"),
        ) + sum(
            (Decimal(str(row.known_max_loss)) for row in open_positions),
            Decimal("0"),
        )

        pauses = db.scalars(
            select(UnderlyingPause).where(
                UnderlyingPause.acknowledged.is_(False)
            )
        ).all()
        paused = frozenset(row.symbol.upper() for row in pauses)

        if reasons:
            return AuthoritativeRiskState(
                authoritative=False,
                snapshot=None,
                reasons=tuple(reasons),
            )

        return AuthoritativeRiskState(
            authoritative=True,
            snapshot=AccountRiskSnapshot(
                equity=capital,
                open_position_max_loss=open_position_max_loss,
                realized_pnl_today=Decimal("0"),
                concurrent_positions=len(active_proposals) + len(open_positions),
                paused_underlyings=paused,
            ),
            reasons=(),
        )


simulation_risk_state_service = SimulationRiskStateService()
