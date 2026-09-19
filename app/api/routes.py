import json
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ApprovalAction, CandidatePromotionRequest, PauseAck, RiskCheckRequest
from app.config import settings
from app.db import SessionLocal
from app.domain.models import AccountRiskSnapshot, RiskPolicy, StrategyType, TradeIntent
from app.persistence.models import AuditEvent, TradeProposal, TradeProposalDetail, UnderlyingPause
from app.risk.manager import RiskManager
from app.risk.state import portfolio_risk_state_service
from app.robinhood.client import RobinhoodTradingMCP
from app.robinhood.read_service import robinhood_read_service
from app.robinhood.market_data import robinhood_market_data
from app.robinhood.normalize import payload_shape, redacted_text_fingerprint
from app.robinhood.schema_args import build_arguments
from app.strategy.candidates import phase_one_candidate_engine

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
    risk_state = portfolio_risk_state_service.build(db, snapshot)
    authoritative_open_risk = (
        float(risk_state.snapshot.open_position_max_loss)
        if risk_state.authoritative and risk_state.snapshot is not None
        else None
    )
    risk_utilization_pct = (
        authoritative_open_risk / snapshot.equity * 100
        if authoritative_open_risk is not None and snapshot.equity
        else None
    )

    # Brokerage values come only from the authenticated Robinhood MCP read path.
    # Unsynced fields remain null rather than being simulated.
    return {
        "equity": snapshot.equity,
        "buying_power": snapshot.buying_power,
        "cash": snapshot.cash,
        "options_value": snapshot.options_value,
        "daily_pnl": snapshot.realized_pnl_today,
        "daily_pnl_pct": (
            (snapshot.realized_pnl_today / snapshot.equity * 100)
            if snapshot.realized_pnl_today is not None and snapshot.equity
            else None
        ),
        "total_pnl": None,
        "open_risk": authoritative_open_risk,
        "risk_utilization_pct": risk_utilization_pct,
        "portfolio_risk_authoritative": risk_state.authoritative,
        "portfolio_risk_reasons": list(risk_state.reasons),
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
        "realized_pnl_today": snapshot.realized_pnl_today,
        "realized_pnl_authoritative": snapshot.realized_pnl_authoritative,
        "realized_pnl_shape": snapshot.realized_pnl_shape,
        "realized_pnl_source": snapshot.realized_pnl_source,
        "pnl_trade_history_shape": snapshot.pnl_trade_history_shape,
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
        "underlying_price": result.underlying_price,
        "selected_expirations": result.selected_expirations,
        "strike_search_count": result.strike_search_count,
        "contracts": result.contracts,
        "tool_errors": result.tool_errors,
        "response_shapes": result.response_shapes,
        "execution_enabled": False,
        "informational_only": True,
    }



@router.get("/opportunities/candidates")
async def phase_one_candidates(symbol: str, db: Session = Depends(db_session)):
    if not settings.robinhood_mcp_enabled:
        raise HTTPException(409, "Robinhood MCP is disabled.")

    # Risk decisions must use a fresh account/P&L snapshot, not merely the
    # background-sync cache.
    await robinhood_read_service.sync_once()
    if robinhood_read_service.snapshot.connection_state not in {
        "connected",
        "degraded",
    }:
        raise HTTPException(
            409,
            "Robinhood read connection is not ready. Complete OAuth and sync first.",
        )

    try:
        scan = await robinhood_market_data.scan_symbol(symbol)
        candidates = phase_one_candidate_engine.generate(
            scan,
            robinhood_read_service.snapshot,
        )
        diagnostics = phase_one_candidate_engine.diagnose(
            scan,
            robinhood_read_service.snapshot,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            502,
            f"Robinhood strategy scan failed: {exc}",
        ) from exc

    risk_state = portfolio_risk_state_service.build(
        db,
        robinhood_read_service.snapshot,
    )
    candidate_rows = []
    risk_approved_candidate_exists = False

    for candidate in candidates:
        row = candidate.as_dict()
        row["risk_preview_authoritative"] = risk_state.authoritative
        row["risk_approved"] = False
        row["risk_reasons"] = list(risk_state.reasons)

        if (
            risk_state.authoritative
            and risk_state.snapshot is not None
            and candidate.strategy == "cash_secured_put"
            and candidate.buying_power_sufficient is True
            and candidate.estimated_max_loss is not None
        ):
            preview_intent = TradeIntent(
                strategy=StrategyType.CASH_SECURED_PUT,
                underlying=candidate.symbol,
                contracts=candidate.contracts,
                known_max_loss=candidate.estimated_max_loss,
                shares_held=candidate.shares_held,
                has_short_put=True,
                is_defined_risk=True,
            )
            preview = risk_manager.evaluate(
                preview_intent,
                risk_state.snapshot,
                current_policy(),
            )
            row["risk_approved"] = preview.approved
            row["risk_reasons"] = list(preview.reasons)
            row["trade_limit"] = str(preview.trade_limit)
            row["portfolio_limit"] = str(preview.portfolio_limit)
            row["daily_loss_limit"] = str(preview.daily_loss_limit)
            if preview.approved:
                risk_approved_candidate_exists = True

        candidate_rows.append(row)

    return {
        "symbol": scan.symbol,
        "scanned_at": scan.scanned_at,
        "underlying_price": scan.underlying_price,
        "selected_expirations": scan.selected_expirations,
        "strike_search_count": scan.strike_search_count,
        "candidates": candidate_rows,
        "diagnostics": [item.as_dict() for item in diagnostics],
        "passed_contracts": sum(1 for item in diagnostics if item.passed),
        "rejected_contracts": sum(1 for item in diagnostics if not item.passed),
        "filters": {
            "min_open_interest": settings.strategy_min_open_interest,
            "min_volume": settings.strategy_min_volume,
            "min_dte": settings.strategy_min_dte,
            "max_dte": settings.strategy_max_dte,
            "short_delta_min": settings.strategy_short_delta_min,
            "short_delta_max": settings.strategy_short_delta_max,
            "max_spread_pct": settings.liquidity_max_spread_pct * 100,
        },
        "portfolio_risk_authoritative": risk_state.authoritative,
        "risk_state_reasons": list(risk_state.reasons),
        "approval_ready": risk_state.authoritative and risk_approved_candidate_exists,
        "execution_enabled": False,
        "note": (
            "A CSP can be promoted into the dry-run approval queue."
            if risk_state.authoritative and risk_approved_candidate_exists
            else "Candidates remain non-executable until all authoritative risk gates pass."
        ),
        "tool_errors": scan.tool_errors,
        "response_shapes": scan.response_shapes,
    }



@router.post("/opportunities/promote")
async def promote_phase_one_candidate(
    body: CandidatePromotionRequest,
    db: Session = Depends(db_session),
):
    """Re-scan and promote one CSP candidate through authoritative server-side risk.

    Covered-call promotion remains disabled until whole-position stock cost-basis
    semantics are implemented. This endpoint never calls a Robinhood write tool.
    """
    if not settings.robinhood_mcp_enabled:
        raise HTTPException(409, "Robinhood MCP is disabled.")

    # Refresh authoritative account state immediately before any promotion
    # risk decision. This endpoint still never calls a Robinhood write tool.
    await robinhood_read_service.sync_once()

    symbol = body.symbol.strip().upper()
    candidate_key = f"{symbol}:{body.option_id}"

    existing = db.scalar(
        select(TradeProposalDetail).where(
            TradeProposalDetail.candidate_key == candidate_key
        )
    )
    if existing:
        raise HTTPException(
            409,
            "This Robinhood option candidate has already been promoted.",
        )

    risk_state = portfolio_risk_state_service.build(
        db,
        robinhood_read_service.snapshot,
    )
    if not risk_state.authoritative or risk_state.snapshot is None:
        raise HTTPException(
            409,
            {
                "message": "Authoritative portfolio risk state is not available.",
                "reasons": list(risk_state.reasons),
            },
        )

    try:
        scan = await robinhood_market_data.scan_symbol(symbol)
        candidates = phase_one_candidate_engine.generate(
            scan,
            robinhood_read_service.snapshot,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            502,
            f"Robinhood candidate refresh failed: {exc}",
        ) from exc

    candidate = next(
        (item for item in candidates if item.option_id == body.option_id),
        None,
    )
    if candidate is None:
        raise HTTPException(
            409,
            "Candidate no longer passes the current market-data filters.",
        )

    if candidate.strategy != "cash_secured_put":
        raise HTTPException(
            409,
            "Covered-call promotion is held until whole-position stock risk is authoritative.",
        )

    if candidate.buying_power_sufficient is not True:
        raise HTTPException(
            409,
            "Synchronized buying power is insufficient or unavailable.",
        )

    if candidate.estimated_max_loss is None:
        raise HTTPException(409, "Candidate max loss is unavailable.")

    intent = TradeIntent(
        strategy=StrategyType.CASH_SECURED_PUT,
        underlying=symbol,
        contracts=candidate.contracts,
        known_max_loss=candidate.estimated_max_loss,
        shares_held=candidate.shares_held,
        has_short_put=True,
        is_defined_risk=True,
    )
    result = risk_manager.evaluate(
        intent,
        risk_state.snapshot,
        current_policy(),
    )
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
        TradeProposalDetail(
            proposal_id=intent.id,
            candidate_key=candidate_key,
            option_id=body.option_id,
            candidate_json=json.dumps(candidate.as_dict()),
        )
    )
    db.add(
        AuditEvent(
            event_type="candidate_promoted",
            severity="info" if result.approved else "warning",
            underlying=symbol,
            message=(
                f"CSP candidate {body.option_id} promoted: "
                f"{'PASS' if result.approved else 'REJECT'}"
            ),
            payload_json=json.dumps(
                {
                    "proposal_id": intent.id,
                    "candidate": candidate.as_dict(),
                    "risk_reasons": list(result.reasons),
                    "trade_limit": str(result.trade_limit),
                    "portfolio_limit": str(result.portfolio_limit),
                    "daily_loss_limit": str(result.daily_loss_limit),
                }
            ),
        )
    )
    db.commit()

    return {
        "proposal_id": intent.id,
        "status": status,
        "approved_by_risk": result.approved,
        "risk_reasons": list(result.reasons),
        "execution_enabled": False,
        "trading_mode": settings.trading_mode.value,
    }



@router.get("/robinhood/pnl-diagnostics")
async def robinhood_pnl_diagnostics():
    """Safe diagnostics for Robinhood P&L tools.

    Returns schemas and response shapes only. It does not expose account numbers
    or raw trade/P&L payload values.
    """
    if not settings.robinhood_mcp_enabled:
        raise HTTPException(409, "Robinhood MCP is disabled.")

    account_number = robinhood_read_service.snapshot.agentic_account_number
    if not account_number:
        await robinhood_read_service.sync_once()
        account_number = robinhood_read_service.snapshot.agentic_account_number

    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    if not account_number:
        return {
            "market_date": today,
            "account_number_present": False,
            "connection_state": robinhood_read_service.snapshot.connection_state,
            "sync_errors": robinhood_read_service.snapshot.tool_errors,
            "detail": "Agentic account number could not be synchronized.",
            "tools": {},
        }

    catalog = await robinhood.tool_catalog()
    result: dict[str, object] = {
        "market_date": today,
        "account_number_present": True,
        "tools": {},
    }

    for tool_name in ("get_realized_pnl", "get_pnl_trade_history"):
        tool = catalog.get(tool_name)
        if not tool:
            result["tools"][tool_name] = {
                "advertised": False,
            }
            continue

        schema = tool.get("input_schema") or {}
        if tool_name == "get_realized_pnl":
            context = {
                "account_number": account_number,
                "start_date": today,
                "end_date": today,
            }
        else:
            context = {
                "account_number": account_number,
                "span": "week",
                "limit": 500,
            }

        try:
            args = build_arguments(schema, context)
        except Exception as exc:
            result["tools"][tool_name] = {
                "advertised": True,
                "schema": schema,
                "argument_build_error": str(exc),
            }
            continue

        safe_args = {
            key: {
                "type": type(value).__name__,
                "value": (
                    "<redacted>"
                    if "account" in key.lower()
                    else value
                ),
            }
            for key, value in args.items()
        }

        try:
            payload = await robinhood.call(tool_name, args)
            tool_result = {
                "advertised": True,
                "schema": schema,
                "arguments": safe_args,
                "response_shape": payload_shape(payload),
                "response_fingerprint": redacted_text_fingerprint(payload),
            }

            if tool_name == "get_realized_pnl":
                from app.robinhood.read_service import _parse_realized_pnl
                parsed, authoritative = _parse_realized_pnl(payload)
                tool_result["parsed_value"] = parsed
                tool_result["parser_authoritative"] = authoritative
            else:
                from app.robinhood.read_service import _parse_trade_history_daily_pnl
                scope_fields = {
                    "start_date", "from_date", "start", "since", "after", "date",
                    "end_date", "to_date", "end", "until", "before",
                }
                scoped_to_day = any(key in args for key in scope_fields)
                parsed, authoritative = _parse_trade_history_daily_pnl(
                    payload,
                    scoped_to_day=scoped_to_day,
                )
                tool_result["scoped_to_day"] = scoped_to_day
                tool_result["parsed_value"] = parsed
                tool_result["parser_authoritative"] = authoritative

            result["tools"][tool_name] = tool_result
        except Exception as exc:
            result["tools"][tool_name] = {
                "advertised": True,
                "schema": schema,
                "arguments": safe_args,
                "error": str(exc),
            }

    return result
