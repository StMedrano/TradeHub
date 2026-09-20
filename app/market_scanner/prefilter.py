from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.config import settings
from app.market_scanner.types import EquityScreenResult
from app.robinhood.client import RobinhoodTradingMCP
from app.robinhood.schema_args import build_arguments


EQUITY_READ_TOOLS = {
    "get_equity_quotes",
    "get_equity_fundamentals",
    "get_equity_tradability",
    "get_earnings_calendar",
}


@dataclass(frozen=True)
class EquityReadSnapshot:
    symbol: str
    price: Decimal | None
    average_volume: int | None
    market_cap: Decimal | None
    is_etf: bool
    tradable: bool | None
    next_earnings_date: date | None


class EquityReadProvider(Protocol):
    async def snapshot(self, symbol: str) -> EquityReadSnapshot: ...


def _dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _dicts(item)


def _first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _decimal(value: Any) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _integer(value: Any) -> int | None:
    number = _decimal(value)
    return int(number) if number is not None else None


def _date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _first_payload_value(payload: Any, names: tuple[str, ...]) -> Any:
    for row in _dicts(payload):
        value = _first(row, names)
        if value is not None:
            return value
    return None


class RobinhoodEquityReadProvider:
    def __init__(self, client: RobinhoodTradingMCP | None = None):
        self.client = client or RobinhoodTradingMCP()

    async def _call(
        self,
        tool_name: str,
        symbol: str,
        catalog: dict[str, dict[str, Any]],
    ) -> Any:
        if tool_name not in EQUITY_READ_TOOLS:
            raise RuntimeError(f"{tool_name} is not an approved equity read tool.")
        tool = catalog.get(tool_name)
        if tool is None:
            raise RuntimeError(f"Robinhood MCP did not advertise {tool_name}.")
        args = build_arguments(
            tool.get("input_schema") or {},
            {"symbol": symbol, "symbols": [symbol]},
        )
        return await self.client.call(tool_name, args)

    async def snapshot(self, symbol: str) -> EquityReadSnapshot:
        symbol = symbol.strip().upper()
        catalog = await self.client.tool_catalog()

        quote = await self._call("get_equity_quotes", symbol, catalog)
        fundamentals = await self._call("get_equity_fundamentals", symbol, catalog)
        tradability = await self._call("get_equity_tradability", symbol, catalog)

        security_type = str(
            _first_payload_value(
                fundamentals,
                ("security_type", "instrument_type", "asset_type", "type"),
            )
            or ""
        ).lower()
        is_etf = "etf" in security_type or "exchange traded fund" in security_type

        earnings = (
            None
            if is_etf
            else await self._call("get_earnings_calendar", symbol, catalog)
        )

        price = _decimal(
            _first_payload_value(
                quote,
                (
                    "last_trade_price",
                    "last_non_reg_trade_price",
                    "mark_price",
                    "previous_close",
                    "price",
                ),
            )
        )
        average_volume = _integer(
            _first_payload_value(
                fundamentals,
                (
                    "average_volume_2_weeks",
                    "average_volume",
                    "avg_volume",
                    "average_daily_volume",
                ),
            )
        )
        market_cap = _decimal(
            _first_payload_value(
                fundamentals,
                ("market_cap", "market_capitalization", "marketCapitalization"),
            )
        )

        raw_tradable = _first_payload_value(
            tradability,
            ("tradable", "is_tradable", "tradeable", "is_tradeable"),
        )
        tradable: bool | None
        if isinstance(raw_tradable, bool):
            tradable = raw_tradable
        elif raw_tradable is not None:
            tradable = str(raw_tradable).strip().lower() in {
                "true",
                "1",
                "yes",
                "tradable",
                "active",
            }
        else:
            status = str(
                _first_payload_value(
                    tradability,
                    ("tradability", "state", "status"),
                )
                or ""
            ).lower()
            tradable = True if status in {"tradable", "active"} else None

        earnings_dates: list[date] = []
        for row in _dicts(earnings):
            raw = _first(
                row,
                (
                    "report_date",
                    "earnings_date",
                    "expected_report_date",
                    "next_earnings_date",
                    "date",
                ),
            )
            parsed = _date(raw)
            if parsed is not None:
                earnings_dates.append(parsed)

        today = datetime.now().date()
        future = sorted(value for value in earnings_dates if value >= today)
        next_earnings = future[0] if future else None

        return EquityReadSnapshot(
            symbol=symbol,
            price=price,
            average_volume=average_volume,
            market_cap=market_cap,
            is_etf=is_etf,
            tradable=tradable,
            next_earnings_date=next_earnings,
        )


class EquityPrefilter:
    def __init__(self, provider: EquityReadProvider | None = None):
        self.provider = provider or RobinhoodEquityReadProvider()

    async def screen(
        self,
        symbol: str,
        watchlist_priority: bool,
        capacity: Decimal,
        *,
        expiration_dates: list[date] | None = None,
        never_scanned: bool = True,
        staleness_hours: float = 0.0,
    ) -> EquityScreenResult:
        data = await self.provider.snapshot(symbol)
        reasons: list[str] = []

        if data.tradable is not True:
            reasons.append("Robinhood reports the symbol is not tradable.")

        minimum_price = Decimal(str(settings.market_scanner_min_price))
        if data.price is None:
            reasons.append("Underlying price is unavailable.")
        elif data.price < minimum_price:
            reasons.append(
                f"Underlying price {data.price} is below minimum "
                f"{settings.market_scanner_min_price:g}."
            )

        if data.average_volume is None:
            reasons.append("Required average volume is unavailable.")
        elif data.average_volume < settings.market_scanner_min_avg_volume:
            reasons.append(
                f"Average volume {data.average_volume} is below minimum "
                f"{settings.market_scanner_min_avg_volume}."
            )

        minimum_market_cap = Decimal(str(settings.market_scanner_min_market_cap))
        if data.market_cap is None:
            reasons.append("Required market cap is unavailable.")
        elif data.market_cap < minimum_market_cap:
            reasons.append(
                f"Market cap {data.market_cap} is below minimum "
                f"{settings.market_scanner_min_market_cap}."
            )

        if (
            settings.market_scanner_exclude_earnings
            and not data.is_etf
            and expiration_dates
        ):
            if data.next_earnings_date is None:
                reasons.append(
                    "Required earnings date is unavailable for expiration screening."
                )
            elif any(
                data.next_earnings_date <= expiration
                for expiration in expiration_dates
            ):
                reasons.append(
                    f"Earnings on {data.next_earnings_date.isoformat()} occur "
                    "on or before a candidate expiration."
                )

        priority_score = 0.0
        if watchlist_priority:
            priority_score += 1000.0
        if never_scanned:
            priority_score += 500.0
        priority_score += min(max(staleness_hours, 0.0), 168.0)

        approximate_strike_ceiling = capacity / Decimal("100")
        if (
            data.price is not None
            and approximate_strike_ceiling > 0
            and data.price > approximate_strike_ceiling
        ):
            ratio = data.price / approximate_strike_ceiling
            priority_score -= float(ratio - Decimal("1")) * 10.0

        return EquityScreenResult(
            symbol=data.symbol,
            passed=not reasons,
            reasons=tuple(reasons),
            priority_score=priority_score,
            price=data.price,
            average_volume=data.average_volume,
            market_cap=data.market_cap,
            is_etf=data.is_etf,
        )


equity_prefilter = EquityPrefilter()
