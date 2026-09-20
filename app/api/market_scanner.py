import json
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import RiskCapitalMode, settings
from app.db import SessionLocal
from app.market_scanner.store import MarketScannerStore
from app.market_scanner.worker import market_scan_worker
from app.persistence.models import (
    MarketOpportunitySnapshot,
    MarketScanRun,
)
from app.risk.state import portfolio_risk_state_service, simulation_risk_state_service
from app.robinhood.read_service import robinhood_read_service


router = APIRouter(prefix="/api/market-scanner", tags=["market-scanner"])


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _latest_run(db: Session) -> MarketScanRun | None:
    return db.scalar(
        select(MarketScanRun).order_by(MarketScanRun.created_at.desc())
    )


def _run_dict(run: MarketScanRun | None) -> dict[str, object]:
    if run is None:
        return {
            "run_id": None,
            "status": "idle",
            "symbols_discovered": 0,
            "symbols_prefiltered": 0,
            "symbols_deep_scanned": 0,
            "deep_scan_target": 0,
            "contracts_evaluated": 0,
            "matches_found": 0,
            "error_count": 0,
            "risk_capital_mode": settings.risk_capital_mode.value,
            "risk_equity": None,
            "per_trade_loss_limit": None,
            "portfolio_loss_limit": None,
            "started_at": None,
            "completed_at": None,
        }

    try:
        config = json.loads(run.config_json or "{}")
    except json.JSONDecodeError:
        config = {}

    max_deep_symbols = int(
        config.get(
            "max_deep_symbols",
            settings.market_scanner_max_deep_symbols,
        )
    )
    max_trade_loss_pct = Decimal(
        str(config.get("max_trade_loss_pct", settings.max_trade_loss_pct))
    )
    max_portfolio_loss_pct = Decimal(
        str(config.get("max_portfolio_loss_pct", settings.max_portfolio_loss_pct))
    )
    risk_equity = Decimal(str(run.risk_equity))

    return {
        "run_id": run.id,
        "status": run.status,
        "symbols_discovered": run.symbols_discovered,
        "symbols_prefiltered": run.symbols_prefiltered,
        "symbols_deep_scanned": run.symbols_deep_scanned,
        "deep_scan_target": min(run.symbols_prefiltered, max_deep_symbols),
        "contracts_evaluated": run.contracts_evaluated,
        "matches_found": run.matches_found,
        "error_count": run.error_count,
        "risk_capital_mode": run.risk_capital_mode,
        "risk_equity": str(run.risk_equity),
        "per_trade_loss_limit": str(risk_equity * max_trade_loss_pct),
        "portfolio_loss_limit": str(risk_equity * max_portfolio_loss_pct),
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
    }


def _opportunity_dict(row: MarketOpportunitySnapshot) -> dict[str, object]:
    return {
        "run_id": row.run_id,
        "symbol": row.symbol,
        "option_id": row.option_id,
        "strategy": row.strategy,
        "expiration_date": row.expiration_date,
        "strike_price": str(row.strike_price),
        "delta": str(row.delta) if row.delta is not None else None,
        "bid": str(row.bid) if row.bid is not None else None,
        "ask": str(row.ask) if row.ask is not None else None,
        "mark": str(row.mark) if row.mark is not None else None,
        "open_interest": row.open_interest,
        "volume": row.volume,
        "spread_pct": str(row.spread_pct) if row.spread_pct is not None else None,
        "estimated_credit": str(row.estimated_credit),
        "estimated_collateral": str(row.estimated_collateral),
        "estimated_max_loss": str(row.estimated_max_loss),
        "score": str(row.score),
        "risk_approved": row.risk_approved,
        "rejection_stage": row.rejection_stage,
        "risk_reasons": json.loads(row.risk_reasons_json or "[]"),
        "minimum_equity_for_trade_limit": (
            str(row.minimum_equity_for_trade_limit)
            if row.minimum_equity_for_trade_limit is not None
            else None
        ),
        "scanned_at": row.scanned_at,
    }


async def _queue_risk_context(db: Session) -> tuple[str, Decimal]:
    if settings.risk_capital_mode == RiskCapitalMode.SIMULATION:
        equity = Decimal(str(settings.simulation_capital))
        state = simulation_risk_state_service.build(db, capital=equity)
        if not state.authoritative or state.snapshot is None:
            raise HTTPException(
                409,
                {
                    "message": "Simulation risk state is not authoritative.",
                    "reasons": list(state.reasons),
                },
            )
        return RiskCapitalMode.SIMULATION.value, state.snapshot.equity

    await robinhood_read_service.sync_once()
    state = portfolio_risk_state_service.build(
        db,
        robinhood_read_service.snapshot,
    )
    if not state.authoritative or state.snapshot is None:
        raise HTTPException(
            409,
            {
                "message": "Live account risk state is not authoritative.",
                "reasons": list(state.reasons),
            },
        )
    return RiskCapitalMode.LIVE_ACCOUNT.value, state.snapshot.equity


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def queue_market_scan(db: Session = Depends(db_session)):
    if not settings.market_scanner_enabled:
        raise HTTPException(
            409,
            "Whole-market scanner is disabled. Set MARKET_SCANNER_ENABLED=true explicitly.",
        )

    risk_mode, risk_equity = await _queue_risk_context(db)
    config_snapshot = {
        "min_price": settings.market_scanner_min_price,
        "min_avg_volume": settings.market_scanner_min_avg_volume,
        "min_market_cap": settings.market_scanner_min_market_cap,
        "exclude_earnings": settings.market_scanner_exclude_earnings,
        "max_deep_symbols": settings.market_scanner_max_deep_symbols,
        "option_concurrency": settings.market_scanner_option_concurrency,
        "strategy_min_dte": settings.strategy_min_dte,
        "strategy_max_dte": settings.strategy_max_dte,
        "strategy_short_delta_min": settings.strategy_short_delta_min,
        "strategy_short_delta_max": settings.strategy_short_delta_max,
        "strategy_min_open_interest": settings.strategy_min_open_interest,
        "strategy_min_volume": settings.strategy_min_volume,
        "liquidity_max_spread_pct": settings.liquidity_max_spread_pct,
        "max_trade_loss_pct": settings.max_trade_loss_pct,
        "max_portfolio_loss_pct": settings.max_portfolio_loss_pct,
    }

    try:
        run = market_scan_worker.create_or_queue_run(
            risk_capital_mode=risk_mode,
            risk_equity=risk_equity,
            config_snapshot=config_snapshot,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc

    return {
        "run_id": run.id,
        "status": run.status,
        "risk_capital_mode": run.risk_capital_mode,
        "risk_equity": str(run.risk_equity),
        "execution_enabled": False,
    }


@router.get("/status")
def market_scanner_status(db: Session = Depends(db_session)):
    return {
        **_run_dict(_latest_run(db)),
        "scanner_enabled": settings.market_scanner_enabled,
        "execution_enabled": False,
    }


@router.get("/runs/{run_id}")
def market_scan_run(run_id: str, db: Session = Depends(db_session)):
    run = db.get(MarketScanRun, run_id)
    if run is None:
        raise HTTPException(404, "Market scan run not found.")
    return {
        **_run_dict(run),
        "config": json.loads(run.config_json or "{}"),
        "execution_enabled": False,
    }


def _latest_run_opportunities(
    db: Session,
    *,
    approved: bool,
) -> list[MarketOpportunitySnapshot]:
    run = _latest_run(db)
    if run is None:
        return []
    return list(
        db.scalars(
            select(MarketOpportunitySnapshot)
            .where(
                MarketOpportunitySnapshot.run_id == run.id,
                MarketOpportunitySnapshot.risk_approved.is_(approved),
            )
            .order_by(
                MarketOpportunitySnapshot.score.desc()
                if approved
                else MarketOpportunitySnapshot.estimated_max_loss.asc()
            )
        ).all()
    )


@router.get("/opportunities")
def market_opportunities(db: Session = Depends(db_session)):
    rows = _latest_run_opportunities(db, approved=True)
    return {
        "items": [_opportunity_dict(row) for row in rows],
        "count": len(rows),
        "mechanical_only": True,
        "execution_enabled": False,
        "note": (
            "These are mechanical matches that pass configured market and "
            "TradeHub risk filters. Promotion always performs a fresh rescan "
            "and authoritative risk check."
        ),
    }


@router.get("/near-misses")
def market_near_misses(db: Session = Depends(db_session)):
    rows = _latest_run_opportunities(db, approved=False)
    return {
        "items": [_opportunity_dict(row) for row in rows],
        "count": len(rows),
        "mechanical_only": True,
        "execution_enabled": False,
        "note": "Near misses failed one or more configured mechanical or risk gates.",
    }
