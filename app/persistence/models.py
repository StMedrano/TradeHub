from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

class TradeProposal(Base):
    __tablename__ = "trade_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    contracts: Mapped[int] = mapped_column(Integer)
    known_max_loss: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_reasons: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    underlying: Mapped[str | None] = mapped_column(String(16), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

class UnderlyingPause(Base):
    __tablename__ = "underlying_pauses"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    reason: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )



class TradeProposalDetail(Base):
    __tablename__ = "trade_proposal_details"

    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    option_id: Mapped[str] = mapped_column(String(128), index=True)
    candidate_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )



class SimulationPosition(Base):
    __tablename__ = "simulation_positions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    option_id: Mapped[str] = mapped_column(String(128), index=True)
    contracts: Mapped[int] = mapped_column(Integer)
    strike_price: Mapped[float] = mapped_column(Numeric(18, 4))
    expiration_date: Mapped[str] = mapped_column(String(16))
    entry_credit: Mapped[float] = mapped_column(Numeric(18, 4))
    known_max_loss: Mapped[float] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    exit_debit: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
