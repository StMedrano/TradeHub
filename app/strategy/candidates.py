from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import settings
from app.robinhood.market_data import OptionScanResult
from app.robinhood.read_service import RobinhoodSnapshot


def _decimal(value: Any) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _days_to_expiry(value: Any) -> int | None:
    if not value:
        return None
    try:
        expiry = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return (expiry - date.today()).days


def _shares_for_symbol(snapshot: RobinhoodSnapshot, symbol: str) -> int:
    total = Decimal("0")
    for row in snapshot.equity_positions:
        row_symbol = str(row.get("symbol") or "").upper()
        if row_symbol != symbol.upper():
            continue
        qty = _decimal(row.get("quantity"))
        if qty is not None and qty > 0:
            total += qty
    return int(total)


@dataclass(frozen=True)
class CandidateDiagnostic:
    option_id: str | None
    option_type: str | None
    expiration_date: str | None
    strike_price: Any
    passed: bool
    reasons: tuple[str, ...]
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "option_type": self.option_type,
            "expiration_date": self.expiration_date,
            "strike_price": self.strike_price,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "score": self.score,
        }


@dataclass(frozen=True)
class StrategyCandidate:
    symbol: str
    strategy: str
    option_id: str | None
    expiration_date: str | None
    dte: int | None
    strike_price: Decimal | None
    option_type: str | None
    bid: Decimal | None
    ask: Decimal | None
    mark: Decimal | None
    spread_pct: float | None
    implied_volatility: float | None
    delta: float | None
    theta: float | None
    open_interest: int
    volume: int
    multiplier: int
    contracts: int
    shares_held: int
    estimated_credit: Decimal | None
    estimated_collateral: Decimal | None
    estimated_max_loss: Decimal | None
    buying_power_sufficient: bool | None
    score: float
    risk_status: str
    risk_note: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "option_id": self.option_id,
            "expiration_date": self.expiration_date,
            "dte": self.dte,
            "strike_price": str(self.strike_price) if self.strike_price is not None else None,
            "option_type": self.option_type,
            "bid": str(self.bid) if self.bid is not None else None,
            "ask": str(self.ask) if self.ask is not None else None,
            "mark": str(self.mark) if self.mark is not None else None,
            "spread_pct": self.spread_pct,
            "implied_volatility": self.implied_volatility,
            "delta": self.delta,
            "theta": self.theta,
            "open_interest": self.open_interest,
            "volume": self.volume,
            "multiplier": self.multiplier,
            "contracts": self.contracts,
            "shares_held": self.shares_held,
            "estimated_credit": str(self.estimated_credit) if self.estimated_credit is not None else None,
            "estimated_collateral": str(self.estimated_collateral) if self.estimated_collateral is not None else None,
            "estimated_max_loss": str(self.estimated_max_loss) if self.estimated_max_loss is not None else None,
            "buying_power_sufficient": self.buying_power_sufficient,
            "score": self.score,
            "risk_status": self.risk_status,
            "risk_note": self.risk_note,
            "reasons": list(self.reasons),
        }



class PhaseOneCandidateEngine:
    """Mechanical Phase 1 candidate screening only.

    This engine never places orders and does not convert candidates directly into
    approval-ready trades. Portfolio max-loss accounting remains a separate hard gate.
    """

    def _base_filters(self, row: dict[str, Any]) -> tuple[bool, list[str], int | None]:
        reasons: list[str] = []
        dte = _days_to_expiry(row.get("expiration_date"))
        spread_pct = _float(row.get("spread_pct"))
        oi = _int(row.get("open_interest"))
        volume = _int(row.get("volume"))
        delta = _float(row.get("delta"))

        if dte is None:
            reasons.append("Expiration date is unavailable.")
        elif not settings.strategy_min_dte <= dte <= settings.strategy_max_dte:
            reasons.append(
                f"DTE {dte} is outside configured range "
                f"{settings.strategy_min_dte}-{settings.strategy_max_dte}."
            )

        max_spread_pct = settings.liquidity_max_spread_pct * 100
        if spread_pct is None:
            reasons.append("Bid/ask spread is unavailable.")
        elif spread_pct > max_spread_pct:
            reasons.append(
                f"Spread {spread_pct:.2f}% exceeds configured "
                f"{max_spread_pct:.2f}% limit."
            )

        if oi < settings.strategy_min_open_interest:
            reasons.append(
                f"Open interest {oi} is below minimum "
                f"{settings.strategy_min_open_interest}."
            )

        if volume < settings.strategy_min_volume:
            reasons.append(
                f"Volume {volume} is below minimum {settings.strategy_min_volume}."
            )

        if delta is None:
            reasons.append("Delta is unavailable.")
        else:
            abs_delta = abs(delta)
            if not (
                settings.strategy_short_delta_min
                <= abs_delta
                <= settings.strategy_short_delta_max
            ):
                reasons.append(
                    f"|Delta| {abs_delta:.3f} is outside configured range "
                    f"{settings.strategy_short_delta_min:.2f}-"
                    f"{settings.strategy_short_delta_max:.2f}."
                )

        return not reasons, reasons, dte

    @staticmethod
    def _score(row: dict[str, Any]) -> float:
        delta = abs(_float(row.get("delta")) or 0)
        target_delta = 0.25
        delta_score = max(0.0, 1.0 - abs(delta - target_delta) / 0.25)

        spread = _float(row.get("spread_pct"))
        spread_score = 0.0 if spread is None else max(0.0, 1.0 - min(spread, 100.0) / 100.0)

        oi = _int(row.get("open_interest"))
        oi_score = min(1.0, oi / 1000.0)

        volume = _int(row.get("volume"))
        volume_score = min(1.0, volume / 500.0)

        return round(
            100.0
            * (
                0.40 * delta_score
                + 0.25 * spread_score
                + 0.20 * oi_score
                + 0.15 * volume_score
            ),
            1,
        )

    def diagnose(
        self,
        scan: OptionScanResult,
        snapshot: RobinhoodSnapshot,
    ) -> list[CandidateDiagnostic]:
        symbol = scan.symbol.upper()
        shares = _shares_for_symbol(snapshot, symbol)
        has_cover = shares >= 100
        diagnostics: list[CandidateDiagnostic] = []

        for row in scan.contracts:
            passed, reasons, _ = self._base_filters(row)
            option_type = str(row.get("option_type") or "").lower()
            extra = list(reasons)

            if passed:
                if option_type == "call" and not has_cover:
                    extra.append(
                        "Covered call requires at least 100 owned shares."
                    )
                elif option_type == "put" and has_cover:
                    extra.append(
                        "Covered calls are preferred while sufficient shares are owned."
                    )
                elif option_type not in {"call", "put"}:
                    extra.append("Option type is not supported by Phase 1.")

            diagnostics.append(
                CandidateDiagnostic(
                    option_id=row.get("option_id"),
                    option_type=option_type or None,
                    expiration_date=row.get("expiration_date"),
                    strike_price=row.get("strike_price"),
                    passed=not extra,
                    reasons=tuple(extra),
                    score=self._score(row),
                )
            )

        diagnostics.sort(key=lambda item: (-item.score, item.expiration_date or ""))
        return diagnostics

    def generate(
        self,
        scan: OptionScanResult,
        snapshot: RobinhoodSnapshot,
    ) -> list[StrategyCandidate]:
        symbol = scan.symbol.upper()
        shares = _shares_for_symbol(snapshot, symbol)
        has_cover = shares >= 100
        results: list[StrategyCandidate] = []

        for row in scan.contracts:
            passed, reasons, dte = self._base_filters(row)
            if not passed:
                continue

            option_type = str(row.get("option_type") or "").lower()
            strike = _decimal(row.get("strike_price"))
            bid = _decimal(row.get("bid"))
            ask = _decimal(row.get("ask"))
            mark = _decimal(row.get("mark"))
            multiplier = _int(row.get("trade_value_multiplier")) or 100
            credit_per_share = bid if bid is not None and bid > 0 else mark

            if strike is None or credit_per_share is None or credit_per_share <= 0:
                continue

            contracts = 1
            estimated_credit = credit_per_share * multiplier * contracts
            score = self._score(row)

            if option_type == "call" and has_cover:
                results.append(
                    StrategyCandidate(
                        symbol=symbol,
                        strategy="covered_call",
                        option_id=row.get("option_id"),
                        expiration_date=row.get("expiration_date"),
                        dte=dte,
                        strike_price=strike,
                        option_type=option_type,
                        bid=bid,
                        ask=ask,
                        mark=mark,
                        spread_pct=_float(row.get("spread_pct")),
                        implied_volatility=_float(row.get("implied_volatility")),
                        delta=_float(row.get("delta")),
                        theta=_float(row.get("theta")),
                        open_interest=_int(row.get("open_interest")),
                        volume=_int(row.get("volume")),
                        multiplier=multiplier,
                        contracts=contracts,
                        shares_held=shares,
                        estimated_credit=estimated_credit,
                        estimated_collateral=None,
                        estimated_max_loss=None,
                        buying_power_sufficient=None,
                        score=score,
                        risk_status="portfolio_risk_pending",
                        risk_note=(
                            "Covered-call downside depends on the existing stock "
                            "position/cost basis. Candidate is not approval-ready "
                            "until whole-position risk is calculated."
                        ),
                        reasons=("Owned shares provide contract coverage.",),
                    )
                )

            elif option_type == "put" and not has_cover:
                collateral = (strike - credit_per_share) * multiplier * contracts
                if collateral <= 0:
                    continue
                bp = snapshot.buying_power
                bp_ok = None if bp is None else Decimal(str(bp)) >= collateral

                candidate_reasons: list[str] = []
                if bp_ok is False:
                    candidate_reasons.append(
                        "Estimated cash-secured collateral exceeds synchronized buying power."
                    )

                results.append(
                    StrategyCandidate(
                        symbol=symbol,
                        strategy="cash_secured_put",
                        option_id=row.get("option_id"),
                        expiration_date=row.get("expiration_date"),
                        dte=dte,
                        strike_price=strike,
                        option_type=option_type,
                        bid=bid,
                        ask=ask,
                        mark=mark,
                        spread_pct=_float(row.get("spread_pct")),
                        implied_volatility=_float(row.get("implied_volatility")),
                        delta=_float(row.get("delta")),
                        theta=_float(row.get("theta")),
                        open_interest=_int(row.get("open_interest")),
                        volume=_int(row.get("volume")),
                        multiplier=multiplier,
                        contracts=contracts,
                        shares_held=shares,
                        estimated_credit=estimated_credit,
                        estimated_collateral=collateral,
                        estimated_max_loss=collateral,
                        buying_power_sufficient=bp_ok,
                        score=score,
                        risk_status=(
                            "portfolio_risk_pending"
                            if bp_ok is not False
                            else "buying_power_reject"
                        ),
                        risk_note=(
                            "Per-contract CSP loss is bounded by strike minus "
                            "premium, but aggregate portfolio max loss is not yet "
                            "authoritative, so this candidate is not approval-ready."
                        ),
                        reasons=tuple(candidate_reasons),
                    )
                )

        # Covered calls are preferred when the account already owns sufficient shares.
        strategy_order = {"covered_call": 0, "cash_secured_put": 1}
        results.sort(
            key=lambda item: (
                strategy_order.get(item.strategy, 9),
                -item.score,
                item.dte if item.dte is not None else 9999,
            )
        )

        return results


phase_one_candidate_engine = PhaseOneCandidateEngine()
