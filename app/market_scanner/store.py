import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.market_scanner.types import EquityScreenResult
from app.persistence.models import (
    MarketOpportunitySnapshot,
    MarketScanRun,
    MarketScanSymbol,
)


_ACTIVE_RUN_STATUSES = {"queued", "discovering", "deep_scanning"}


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return datetime.now(timezone.utc)


class MarketScannerStore:
    def __init__(self, db: Session):
        self.db = db

    def create_run(
        self,
        *,
        risk_capital_mode: str,
        risk_equity: Decimal,
        config_snapshot: dict[str, object],
    ) -> MarketScanRun:
        run = MarketScanRun(
            id=f"scan-{uuid4()}",
            status="queued",
            risk_capital_mode=risk_capital_mode,
            risk_equity=risk_equity,
            config_json=json.dumps(config_snapshot, sort_keys=True),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(self, run_id: str) -> MarketScanRun | None:
        return self.db.get(MarketScanRun, run_id)

    def get_active_run(self) -> MarketScanRun | None:
        return self.db.scalar(
            select(MarketScanRun)
            .where(MarketScanRun.status.in_(_ACTIVE_RUN_STATUSES))
            .order_by(MarketScanRun.created_at.asc())
        )

    def set_run_status(self, run_id: str, status: str) -> None:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run.status = status
        now = datetime.now(timezone.utc)
        if status in {"discovering", "deep_scanning"} and run.started_at is None:
            run.started_at = now
        if status in {"complete", "partial", "failed"}:
            run.completed_at = now
        self.db.commit()

    def recover_interrupted_runs(self) -> list[str]:
        rows = self.db.scalars(
            select(MarketScanRun)
            .where(MarketScanRun.status.in_({"discovering", "deep_scanning"}))
            .order_by(MarketScanRun.created_at.asc())
        ).all()
        recovered: list[str] = []
        for row in rows:
            row.status = "queued"
            row.completed_at = None
            recovered.append(row.id)
        if rows:
            self.db.commit()
        return recovered

    def upsert_symbol(
        self,
        run_id: str,
        symbol: str,
        source_slice: str,
        watchlist_priority: bool,
    ) -> MarketScanSymbol:
        normalized = symbol.strip().upper()
        row = self.db.scalar(
            select(MarketScanSymbol).where(
                MarketScanSymbol.run_id == run_id,
                MarketScanSymbol.symbol == normalized,
            )
        )
        if row is None:
            previous = self.db.scalar(
                select(MarketScanSymbol)
                .where(
                    MarketScanSymbol.symbol == normalized,
                    MarketScanSymbol.run_id != run_id,
                    MarketScanSymbol.last_deep_scan_at.is_not(None),
                )
                .order_by(MarketScanSymbol.last_deep_scan_at.desc())
            )
            row = MarketScanSymbol(
                run_id=run_id,
                symbol=normalized,
                source_slice=source_slice,
                watchlist_priority=watchlist_priority,
                last_deep_scan_at=(
                    previous.last_deep_scan_at if previous is not None else None
                ),
                consecutive_error_count=(
                    previous.consecutive_error_count if previous is not None else 0
                ),
            )
            self.db.add(row)
        else:
            row.watchlist_priority = row.watchlist_priority or watchlist_priority
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_symbol(self, run_id: str, symbol: str) -> MarketScanSymbol | None:
        return self.db.scalar(
            select(MarketScanSymbol).where(
                MarketScanSymbol.run_id == run_id,
                MarketScanSymbol.symbol == symbol.strip().upper(),
            )
        )

    def symbols(self, run_id: str) -> list[str]:
        return list(
            self.db.scalars(
                select(MarketScanSymbol.symbol)
                .where(MarketScanSymbol.run_id == run_id)
                .order_by(MarketScanSymbol.symbol.asc())
            ).all()
        )

    def mark_equity_screen(
        self,
        run_id: str,
        symbol: str,
        result: EquityScreenResult,
    ) -> None:
        row = self.get_symbol(run_id, symbol)
        if row is None:
            raise KeyError(f"{run_id}:{symbol}")
        row.equity_screen_status = "passed" if result.passed else "rejected"
        row.equity_reasons_json = json.dumps(list(result.reasons))
        row.priority_score = Decimal(str(result.priority_score))
        row.earnings_status = (
            "not_applicable" if result.is_etf else "clear" if result.passed else "checked"
        )
        self.db.commit()

    def mark_deep_scan(
        self,
        run_id: str,
        symbol: str,
        *,
        status: str,
        market_filter_passes: int,
        mechanical_match_count: int,
        near_miss_count: int,
        tool_errors: dict[str, str],
    ) -> None:
        row = self.get_symbol(run_id, symbol)
        if row is None:
            raise KeyError(f"{run_id}:{symbol}")
        row.option_scan_status = status
        row.market_filter_passes = market_filter_passes
        row.mechanical_match_count = mechanical_match_count
        row.near_miss_count = near_miss_count
        row.tool_errors_json = json.dumps(tool_errors, sort_keys=True)
        if status in {"complete", "failed"}:
            row.last_deep_scan_at = datetime.now(timezone.utc)
            row.completed_at = row.last_deep_scan_at
        elif status == "running":
            row.started_at = datetime.now(timezone.utc)
        row.consecutive_error_count = (
            row.consecutive_error_count + 1 if status == "failed" else 0
        )
        self.db.commit()

    def replace_symbol_opportunities(
        self,
        run_id: str,
        symbol: str,
        rows: list[dict[str, object]],
    ) -> None:
        normalized = symbol.strip().upper()
        self.db.execute(
            delete(MarketOpportunitySnapshot).where(
                MarketOpportunitySnapshot.run_id == run_id,
                MarketOpportunitySnapshot.symbol == normalized,
            )
        )
        for item in rows:
            option_id = item.get("option_id")
            if not option_id:
                continue
            self.db.add(
                MarketOpportunitySnapshot(
                    run_id=run_id,
                    symbol=normalized,
                    option_id=str(option_id),
                    strategy=str(item.get("strategy") or "cash_secured_put"),
                    expiration_date=str(item.get("expiration_date") or ""),
                    strike_price=_decimal(item.get("strike_price")) or Decimal("0"),
                    delta=_decimal(item.get("delta")),
                    bid=_decimal(item.get("bid")),
                    ask=_decimal(item.get("ask")),
                    mark=_decimal(item.get("mark")),
                    open_interest=int(item.get("open_interest") or 0),
                    volume=int(item.get("volume") or 0),
                    spread_pct=_decimal(item.get("spread_pct")),
                    estimated_credit=_decimal(item.get("estimated_credit")) or Decimal("0"),
                    estimated_collateral=_decimal(item.get("estimated_collateral")) or Decimal("0"),
                    estimated_max_loss=_decimal(item.get("estimated_max_loss")) or Decimal("0"),
                    score=_decimal(item.get("score")) or Decimal("0"),
                    risk_approved=bool(item.get("risk_approved")),
                    rejection_stage=(
                        str(item["rejection_stage"])
                        if item.get("rejection_stage") is not None
                        else None
                    ),
                    risk_reasons_json=json.dumps(item.get("risk_reasons") or []),
                    minimum_equity_for_trade_limit=_decimal(
                        item.get("minimum_equity_for_trade_limit")
                    ),
                    scanned_at=_datetime(item.get("scanned_at")),
                )
            )
        self.db.commit()

    def latest_opportunities(
        self,
        symbol: str | None = None,
    ) -> list[MarketOpportunitySnapshot]:
        query = select(MarketOpportunitySnapshot).where(
            MarketOpportunitySnapshot.risk_approved.is_(True)
        )
        if symbol:
            query = query.where(
                MarketOpportunitySnapshot.symbol == symbol.strip().upper()
            )
        return list(
            self.db.scalars(
                query.order_by(
                    MarketOpportunitySnapshot.scanned_at.desc(),
                    MarketOpportunitySnapshot.score.desc(),
                )
            ).all()
        )

    def latest_near_misses(
        self,
        symbol: str | None = None,
    ) -> list[MarketOpportunitySnapshot]:
        query = select(MarketOpportunitySnapshot).where(
            MarketOpportunitySnapshot.risk_approved.is_(False)
        )
        if symbol:
            query = query.where(
                MarketOpportunitySnapshot.symbol == symbol.strip().upper()
            )
        return list(
            self.db.scalars(
                query.order_by(
                    MarketOpportunitySnapshot.scanned_at.desc(),
                    MarketOpportunitySnapshot.estimated_max_loss.asc(),
                )
            ).all()
        )

    def stale_symbol_candidates(
        self,
        run_id: str,
        limit: int,
    ) -> list[MarketScanSymbol]:
        rows = self.db.scalars(
            select(MarketScanSymbol).where(
                MarketScanSymbol.run_id == run_id,
                MarketScanSymbol.equity_screen_status == "passed",
                MarketScanSymbol.option_scan_status.in_(("pending", "running")),
            )
        ).all()
        rows = sorted(
            rows,
            key=lambda row: (
                not row.watchlist_priority,
                row.last_deep_scan_at is not None,
                row.last_deep_scan_at or datetime.min.replace(tzinfo=timezone.utc),
                -float(row.priority_score or 0),
                row.symbol,
            ),
        )
        return list(rows[:limit])
