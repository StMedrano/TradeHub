from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.persistence.models import SimulationPosition, TradeProposal
from app.risk.state import PortfolioRiskStateService, SimulationRiskStateService
from app.robinhood.read_service import RobinhoodSnapshot


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def clean_snapshot(**overrides):
    base = dict(
        connection_state="connected",
        equity=100000,
        realized_pnl_today=250,
        realized_pnl_authoritative=True,
        open_option_positions=0,
        open_orders=0,
    )
    base.update(overrides)
    return RobinhoodSnapshot(**base)


def test_authoritative_when_phase_one_slot_is_empty():
    db = make_session()
    state = PortfolioRiskStateService().build(db, clean_snapshot())

    assert state.authoritative is True
    assert state.snapshot is not None
    assert state.snapshot.open_position_max_loss == 0
    assert state.snapshot.realized_pnl_today == 250


def test_not_authoritative_when_realized_pnl_is_missing():
    db = make_session()
    state = PortfolioRiskStateService().build(
        db,
        clean_snapshot(
            realized_pnl_today=None,
            realized_pnl_authoritative=False,
        ),
    )

    assert state.authoritative is False
    assert any("realized P&L" in reason for reason in state.reasons)


def test_not_authoritative_with_open_option_position():
    db = make_session()
    state = PortfolioRiskStateService().build(
        db,
        clean_snapshot(open_option_positions=1),
    )

    assert state.authoritative is False
    assert any("Open option positions" in reason for reason in state.reasons)


def test_not_authoritative_with_open_option_order():
    db = make_session()
    state = PortfolioRiskStateService().build(
        db,
        clean_snapshot(open_orders=1),
    )

    assert state.authoritative is False
    assert any("Open option orders" in reason for reason in state.reasons)


def test_active_proposal_reserves_phase_one_slot():
    db = make_session()
    db.add(
        TradeProposal(
            id="proposal-1",
            underlying="ABC",
            strategy="cash_secured_put",
            contracts=1,
            known_max_loss=4000,
            status="pending_approval",
            risk_reasons="",
        )
    )
    db.commit()

    state = PortfolioRiskStateService().build(db, clean_snapshot())

    assert state.authoritative is False
    assert any("active TradeHub proposal" in reason for reason in state.reasons)



def test_live_risk_ignores_simulation_proposals():
    db = make_session()
    db.add(
        TradeProposal(
            id="sim-proposal-1",
            underlying="ABC",
            strategy="cash_secured_put",
            contracts=1,
            known_max_loss=400,
            status="pending_approval",
            risk_reasons="",
        )
    )
    db.commit()

    state = PortfolioRiskStateService().build(db, clean_snapshot())

    assert state.authoritative is True
    assert state.snapshot is not None
    assert state.snapshot.concurrent_positions == 0


def test_simulation_risk_only_counts_simulation_proposals():
    db = make_session()
    db.add_all(
        [
            TradeProposal(
                id="sim-proposal-1",
                underlying="ABC",
                strategy="cash_secured_put",
                contracts=1,
                known_max_loss=400,
                status="pending_approval",
                risk_reasons="",
            ),
            TradeProposal(
                id="live-proposal-1",
                underlying="XYZ",
                strategy="cash_secured_put",
                contracts=1,
                known_max_loss=2000,
                status="pending_approval",
                risk_reasons="",
            ),
        ]
    )
    db.commit()

    state = SimulationRiskStateService().build(
        db,
        capital=Decimal("10000"),
    )

    assert state.authoritative is True
    assert state.snapshot is not None
    assert state.snapshot.equity == Decimal("10000")
    assert state.snapshot.open_position_max_loss == Decimal("400.0")
    assert state.snapshot.concurrent_positions == 1
    assert state.snapshot.realized_pnl_today == Decimal("0")



def test_simulation_open_position_reserves_risk():
    db = make_session()
    db.add(
        SimulationPosition(
            id="simpos-1",
            proposal_id="sim-proposal-1",
            underlying="ABC",
            strategy="cash_secured_put",
            option_id="option-1",
            contracts=1,
            strike_price=Decimal("30"),
            expiration_date="2026-10-16",
            entry_credit=Decimal("100"),
            known_max_loss=Decimal("2900"),
            status="open",
        )
    )
    db.commit()

    state = SimulationRiskStateService().build(
        db,
        capital=Decimal("100000"),
    )

    assert state.authoritative is True
    assert state.snapshot is not None
    assert state.snapshot.open_position_max_loss == Decimal("2900.0000")
    assert state.snapshot.concurrent_positions == 1


def test_closed_simulation_position_releases_risk_and_tracks_today_pnl():
    from datetime import datetime, timezone

    db = make_session()
    db.add(
        SimulationPosition(
            id="simpos-1",
            proposal_id="sim-proposal-1",
            underlying="ABC",
            strategy="cash_secured_put",
            option_id="option-1",
            contracts=1,
            strike_price=Decimal("30"),
            expiration_date="2026-10-16",
            entry_credit=Decimal("100"),
            known_max_loss=Decimal("2900"),
            status="closed",
            exit_debit=Decimal("40"),
            realized_pnl=Decimal("60"),
            closed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    state = SimulationRiskStateService().build(
        db,
        capital=Decimal("100000"),
    )

    assert state.authoritative is True
    assert state.snapshot is not None
    assert state.snapshot.open_position_max_loss == Decimal("0")
    assert state.snapshot.concurrent_positions == 0
    assert state.snapshot.realized_pnl_today == Decimal("60.0000")
