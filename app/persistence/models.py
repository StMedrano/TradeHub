from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Text, UniqueConstraint
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
    strike_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    expiration_date: Mapped[str] = mapped_column(String(16))
    entry_credit: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    known_max_loss: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    exit_debit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)



class MarketScanRun(Base):
    __tablename__ = "market_scan_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    risk_capital_mode: Mapped[str] = mapped_column(String(32))
    risk_equity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    symbols_discovered: Mapped[int] = mapped_column(Integer, default=0)
    symbols_prefiltered: Mapped[int] = mapped_column(Integer, default=0)
    symbols_deep_scanned: Mapped[int] = mapped_column(Integer, default=0)
    contracts_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    matches_found: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class MarketScanSymbol(Base):
    __tablename__ = "market_scan_symbols"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", name="uq_market_scan_run_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    source_slice: Mapped[str] = mapped_column(String(128))
    watchlist_priority: Mapped[bool] = mapped_column(Boolean, default=False)
    equity_screen_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    equity_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    earnings_status: Mapped[str] = mapped_column(String(32), default="unknown")
    option_scan_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    market_filter_passes: Mapped[int] = mapped_column(Integer, default=0)
    mechanical_match_count: Mapped[int] = mapped_column(Integer, default=0)
    near_miss_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_errors_json: Mapped[str] = mapped_column(Text, default="{}")
    consecutive_error_count: Mapped[int] = mapped_column(Integer, default=0)
    priority_score: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    last_deep_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketOpportunitySnapshot(Base):
    __tablename__ = "market_opportunity_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "option_id", name="uq_market_run_option"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    option_id: Mapped[str] = mapped_column(String(128), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    expiration_date: Mapped[str] = mapped_column(String(16))
    strike_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    mark: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    open_interest: Mapped[int] = mapped_column(Integer, default=0)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    estimated_credit: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    estimated_collateral: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    estimated_max_loss: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    risk_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejection_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    minimum_equity_for_trade_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
