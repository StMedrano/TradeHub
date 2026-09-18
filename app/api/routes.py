import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ApprovalAction, PauseAck, RiskCheckRequest
from app.config import settings
from app.db import SessionLocal
from app.domain.models import AccountRiskSnapshot, RiskPolicy, TradeIntent
from app.persistence.models import AuditEvent, TradeProposal, UnderlyingPause
from app.risk.manager import RiskManager
from app.robinhood.client import RobinhoodTradingMCP
from app.robinhood.read_service import robinhood_read_service
from app.robinhood.market_data import robinhood_market_data

router = APIRouter(prefix="/api")
risk_manager = RiskManager()
robinhood = RobinhoodTradingMCP()

def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def current_policy() -> RiskPolicy:
    return RiskPolicy(
        max_trade_loss_pct=Decimal(str(settings.max_trade_loss_pct)),
        max_portfolio_loss_pct=Decimal(str(settings.max_portfolio_loss_pct)),
        daily_loss_breaker_pct=Decimal(str(settings.daily_loss_breaker_pct)),
        max_concurrent_positions=settings.max_concurrent_positions,
        phase=settings.phase,
        require_approval=settings.require_approval,
    )

@router.get("/health")
def health():
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "phase": settings.phase,
        "robinhood_mcp_enabled": settings.robinhood_mcp_enabled,
        "robinhood_only": True,
    }

@router.get("/approvals")
def approvals(db: Session = Depends(db_session)):
    rows = db.scalars(
        select(TradeProposal)
        .where(TradeProposal.status == "pending_approval")
        .order_by(TradeProposal.created_at.desc())
    ).all()
    return [
        {
            "id": x.id,
            "underlying": x.underlying,
            "strategy": x.strategy,
            "contracts": x.contracts,
            "known_max_loss": x.known_max_loss,
            "created_at": x.created_at,
        }
        for x in rows
    ]

@router.post("/risk/check")
def risk_check(body: RiskCheckRequest, db: Session = Depends(db_session)):
    intent = TradeIntent(
        strategy=body.strategy,
        underlying=body.underlying.upper(),
        contracts=body.contracts,
        known_max_loss=body.known_max_loss,
        shares_held=body.shares_held,
        has_short_call=body.has_short_call,
        has_short_put=body.has_short_put,
        is_defined_risk=body.is_defined_risk,
    )
    account = AccountRiskSnapshot(
        equity=body.account_equity,
        open_position_max_loss=body.open_position_max_loss,
        realized_pnl_today=body.realized_pnl_today,
        concurrent_positions=body.concurrent_positions,
        paused_underlyings=frozenset(x.upper() for x in body.paused_underlyings),
    )
    result = risk_manager.evaluate(intent, account, current_policy())
    status = "pending_approval" if result.approved else "rejected"

    db.add(
        TradeProposal(
            id=intent.id,
            underlying=intent.underlying,
            strategy=intent.strategy.value,
            contracts=intent.contracts,
            known_max_loss=float(intent.known_max_loss),
            status=status,
            risk_reasons="\n".join(result.reasons),
        )
    )
    db.add(
        AuditEvent(
            event_type="risk_decision",
            severity="info" if result.approved else "warning",
            underlying=intent.underlying,
            message=f"Risk decision: {'PASS' if result.approved else 'REJECT'}",
            payload_json=json.dumps(
                {
                    "proposal_id": intent.id,
                    "reasons": result.reasons,
                    "trade_max_loss": str(result.trade_max_loss),
                    "trade_limit": str(result.trade_limit),
                    "projected_portfolio_max_loss": str(result.projected_portfolio_max_loss),
                    "portfolio_limit": str(result.portfolio_limit),
                    "realized_loss_today": str(result.realized_loss_today),
                    "daily_loss_limit": str(result.daily_loss_limit),
                }
            ),
        )
    )
    db.commit()

    return {
        "proposal_id": intent.id,
        "approved_by_risk": result.approved,
        "status": status,
        "reasons": result.reasons,
    }

@router.post("/approvals/{proposal_id}/approve")
def approve(proposal_id: str, action: ApprovalAction, db: Session = Depends(db_session)):
    p = db.get(TradeProposal, proposal_id)
    if not p:
        raise HTTPException(404, "Proposal not found.")
    if p.status != "pending_approval":
        raise HTTPException(409, f"Proposal is already {p.status}.")
    p.status = "approved"
    p.approved_by = action.actor
    p.approval_note = action.note
    db.add(
        AuditEvent(
            event_type="manual_approval",
            underlying=p.underlying,
            message=f"Proposal {p.id} approved by {action.actor}.",
            payload_json=json.dumps({"note": action.note}),
        )
    )
    db.commit()
    return {"status": "approved", "proposal_id": p.id}

@router.post("/approvals/{proposal_id}/reject")
def reject(proposal_id: str, action: ApprovalAction, db: Session = Depends(db_session)):
    p = db.get(TradeProposal, proposal_id)
    if not p:
        raise HTTPException(404, "Proposal not found.")
    if p.status != "pending_approval":
        raise HTTPException(409, f"Proposal is already {p.status}.")
    p.status = "rejected"
    p.approved_by = action.actor
    p.approval_note = action.note
    db.add(
        AuditEvent(
            event_type="manual_rejection",
            severity="warning",
            underlying=p.underlying,
            message=f"Proposal {p.id} rejected by {action.actor}.",
            payload_json=json.dumps({"note": action.note}),
        )
    )
    db.commit()
    return {"status": "rejected", "proposal_id": p.id}

@router.get("/pauses")
def pauses(db: Session = Depends(db_session)):
    rows = db.scalars(
        select(UnderlyingPause).where(UnderlyingPause.acknowledged.is_(False))
    ).all()
    return [
        {"symbol": x.symbol, "reason": x.reason, "created_at": x.created_at}
        for x in rows
    ]

@router.post("/pauses/{symbol}/acknowledge")
def acknowledge_pause(symbol: str, body: PauseAck, db: Session = Depends(db_session)):
    p = db.get(UnderlyingPause, symbol.upper())
    if not p:
        raise HTTPException(404, "Pause not found.")
    p.acknowledged = True
    p.acknowledged_by = body.actor
    db.add(
        AuditEvent(
            event_type="underlying_pause_acknowledged",
            underlying=symbol.upper(),
            message=f"{symbol.upper()} pause acknowledged by {body.actor}.",
        )
    )
    db.commit()
    return {"status": "acknowledged", "symbol": symbol.upper()}

@router.get("/robinhood/tools")
async def robinhood_tools():
    if not settings.robinhood_mcp_enabled:
        return {
            "enabled": False,
            "message": "Robinhood MCP is disabled until authentication is configured.",
        }
    result = await robinhood.list_tools()
    return {"enabled": True, "result": str(result)}


@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(db_session)):
    pending = db.scalars(
        select(TradeProposal).where(TradeProposal.status == "pending_approval")
    ).all()
    active_pauses = db.scalars(
        select(UnderlyingPause).where(UnderlyingPause.acknowledged.is_(False))
    ).all()

    snapshot = robinhood_read_service.snapshot

    # Brokerage values come only from the authenticated Robinhood MCP read path.
    # Unsynced fields remain null rather than being simulated.
    return {
        "equity": snapshot.equity,
        "buying_power": snapshot.buying_power,
        "cash": snapshot.cash,
        "options_value": snapshot.options_value,
        "daily_pnl": None,
        "daily_pnl_pct": None,
        "total_pnl": None,
        "open_risk": None,
        "risk_utilization_pct": None,
        "open_positions": snapshot.open_positions,
        "open_orders": snapshot.open_orders,
        "pending_approvals": len(pending),
        "paused_underlyings": len(active_pauses),
        "trading_mode": settings.trading_mode.value,
        "phase": settings.phase,
        "require_approval": settings.require_approval,
        "robinhood_mcp_enabled": settings.robinhood_mcp_enabled,
        "robinhood_connection_state": snapshot.connection_state,
        "robinhood_last_sync": snapshot.last_sync,
        "robinhood_last_error": snapshot.last_error,
        "max_concurrent_positions": settings.max_concurrent_positions,
        "max_trade_loss_pct": settings.max_trade_loss_pct,
        "max_portfolio_loss_pct": settings.max_portfolio_loss_pct,
        "daily_loss_breaker_pct": settings.daily_loss_breaker_pct,
        "liquidity_max_spread_pct": settings.liquidity_max_spread_pct,
        "system_status": "healthy",
    }


@router.get("/activity")
def activity(db: Session = Depends(db_session)):
    rows = db.scalars(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)
    ).all()
    return [
        {
            "id": x.id,
            "event_type": x.event_type,
            "severity": x.severity,
            "underlying": x.underlying,
            "message": x.message,
            "created_at": x.created_at,
        }
        for x in rows
    ]



@router.get("/robinhood/status")
def robinhood_status():
    snapshot = robinhood_read_service.snapshot
    return {
        "enabled": settings.robinhood_mcp_enabled,
        "auth_state_present": robinhood.auth_state_exists(),
        "connection_state": snapshot.connection_state,
        "last_sync": snapshot.last_sync,
        "last_error": snapshot.last_error,
        "tool_errors": snapshot.tool_errors,
        "open_equity_positions": snapshot.open_equity_positions,
        "open_option_positions": snapshot.open_option_positions,
        "open_orders": snapshot.open_orders,
    }


@router.post("/robinhood/sync")
async def robinhood_sync():
    if not settings.robinhood_mcp_enabled:
        raise HTTPException(
            409,
            "Robinhood MCP is disabled. Authenticate first and enable it in .env.",
        )
    snapshot = await robinhood_read_service.sync_once()
    return {
        "connection_state": snapshot.connection_state,
        "last_sync": snapshot.last_sync,
        "last_error": snapshot.last_error,
        "tool_errors": snapshot.tool_errors,
    }



@router.get("/positions")
def robinhood_positions():
    snapshot = robinhood_read_service.snapshot

    equities = [
        {
            "symbol": row.get("symbol"),
            "quantity": row.get("quantity"),
            "average_buy_price": row.get("average_buy_price"),
            "shares_available_for_sells": row.get("shares_available_for_sells"),
            "direction": row.get("type"),
        }
        for row in snapshot.equity_positions
    ]

    options = [
        {
            "symbol": row.get("chain_symbol") or row.get("symbol"),
            "option_id": row.get("option_id") or row.get("instrument_id"),
            "direction": row.get("type"),
            "quantity": row.get("quantity"),
            "average_price": row.get("average_price"),
            "expiration_date": row.get("expiration_date"),
            "trade_value_multiplier": row.get("trade_value_multiplier"),
            "opened_at": row.get("opened_at"),
        }
        for row in snapshot.option_positions
    ]

    return {
        "connection_state": snapshot.connection_state,
        "last_sync": snapshot.last_sync,
        "equities": equities,
        "options": options,
    }



@router.get("/robinhood/tool-schemas")
async def robinhood_tool_schemas():
    if not settings.robinhood_mcp_enabled:
        raise HTTPException(409, "Robinhood MCP is disabled.")
    catalog = await robinhood.tool_catalog()
    allowed = {
        name: data
        for name, data in catalog.items()
        if name.startswith("get_")
    }
    return {"tools": allowed}


@router.get("/opportunities/scan")
async def scan_option_opportunities(symbol: str):
    if not settings.robinhood_mcp_enabled:
        raise HTTPException(409, "Robinhood MCP is disabled.")
    if robinhood_read_service.snapshot.connection_state not in {
        "connected",
        "degraded",
    }:
        raise HTTPException(
            409,
            "Robinhood read connection is not ready. Complete OAuth and sync first.",
        )

    try:
        result = await robinhood_market_data.scan_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Robinhood option scan failed: {exc}") from exc

    return {
        "symbol": result.symbol,
        "scanned_at": result.scanned_at,
        "chain_count": result.chain_count,
        "instrument_count": result.instrument_count,
        "quote_count": result.quote_count,
        "contracts": result.contracts,
        "tool_errors": result.tool_errors,
        "execution_enabled": False,
        "informational_only": True,
    }
