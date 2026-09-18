from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.robinhood.client import RobinhoodTradingMCP
from app.robinhood.normalize import extract_candidate_records, extract_records, find_first_list, payload_shape
from app.robinhood.schema_args import build_arguments


READ_ONLY_OPTION_TOOLS = {
    "get_option_chains",
    "get_option_instruments",
    "get_option_quotes",
    "get_option_historicals",
}


def _first_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    direct = _first_value(row, names)
    if direct is not None:
        return direct

    for container_name in ("greeks", "market_data", "quote"):
        nested = row.get(container_name)
        if isinstance(nested, dict):
            value = _first_value(nested, names)
            if value is not None:
                return value
    return None


def _quote_records(value: Any) -> list[dict[str, Any]]:
    rows = extract_records(value) or extract_candidate_records(value)
    quotes: list[dict[str, Any]] = []
    for row in rows:
        nested = row.get("quote") if isinstance(row, dict) else None
        if isinstance(nested, dict):
            quotes.append(nested)
        elif isinstance(row, dict):
            quotes.append(row)

    # Some MCP payloads expose only wrapper rows through extract_records();
    # recursively inspect the payload if those wrappers contained no quote data.
    if quotes and all(
        not any(
            key in quote
            for key in (
                "bid_price",
                "ask_price",
                "mark_price",
                "implied_volatility",
                "delta",
                "open_interest",
                "instrument_id",
                "option_id",
                "id",
            )
        )
        for quote in quotes
    ):
        quotes = [
            row
            for row in extract_candidate_records(value)
            if any(
                key in row
                for key in (
                    "bid_price",
                    "ask_price",
                    "mark_price",
                    "implied_volatility",
                    "delta",
                    "open_interest",
                )
            )
        ]
    return quotes


@dataclass
class OptionScanResult:
    symbol: str
    scanned_at: str
    chain_count: int = 0
    instrument_count: int = 0
    quote_count: int = 0
    contracts: list[dict[str, Any]] = field(default_factory=list)
    tool_errors: dict[str, str] = field(default_factory=dict)
    response_shapes: dict[str, Any] = field(default_factory=dict)


class RobinhoodMarketDataService:
    """Schema-aware, read-only option market data service."""

    def __init__(self, client: RobinhoodTradingMCP | None = None):
        self.client = client or RobinhoodTradingMCP()

    async def _call_schema_aware(
        self,
        tool_name: str,
        context: dict[str, Any],
        catalog: dict[str, dict[str, Any]],
    ) -> Any:
        if tool_name not in READ_ONLY_OPTION_TOOLS:
            raise RuntimeError(f"{tool_name} is not approved for read-only market data.")

        tool = catalog.get(tool_name)
        if not tool:
            raise RuntimeError(f"Robinhood MCP did not advertise {tool_name}.")

        args = build_arguments(tool.get("input_schema") or {}, context)
        return await self.client.call(tool_name, args)

    @staticmethod
    def _eligible_expirations(chains: Any) -> list[str]:
        rows = extract_records(chains) or extract_candidate_records(chains)
        today = datetime.now(timezone.utc).date()
        eligible: set[str] = set()

        for row in rows:
            raw_dates = row.get("expiration_dates")
            if not isinstance(raw_dates, list):
                continue
            for raw in raw_dates:
                try:
                    expiry = datetime.fromisoformat(str(raw)[:10]).date()
                except ValueError:
                    continue
                dte = (expiry - today).days
                if settings.strategy_min_dte <= dte <= settings.strategy_max_dte:
                    eligible.add(expiry.isoformat())

        return sorted(eligible)

    @staticmethod
    def _chain_id(chains: Any) -> str | None:
        rows = extract_records(chains) or extract_candidate_records(chains)
        for row in rows:
            value = _first_value(row, ("id", "chain_id", "option_chain_id"))
            if value:
                return str(value)
        return None

    @staticmethod
    def _option_ids(instruments: Any) -> list[str]:
        ids: list[str] = []
        for row in (extract_records(instruments) or extract_candidate_records(instruments)):
            value = _first_value(
                row,
                ("id", "option_id", "instrument_id", "option_instrument_id"),
            )
            if value:
                ids.append(str(value))
        return ids

    @staticmethod
    def _normalize_contracts(instruments: Any, quotes: Any) -> list[dict[str, Any]]:
        instrument_rows = extract_records(instruments) or extract_candidate_records(instruments)
        quote_rows = _quote_records(quotes)

        quote_map: dict[str, dict[str, Any]] = {}
        for quote in quote_rows:
            qid = _first_value(
                quote,
                ("id", "option_id", "instrument_id", "option_instrument_id"),
            )
            if qid:
                quote_map[str(qid)] = quote

        contracts: list[dict[str, Any]] = []
        for row in instrument_rows:
            option_id = _first_value(
                row,
                ("id", "option_id", "instrument_id", "option_instrument_id"),
            )
            quote = quote_map.get(str(option_id), {}) if option_id else {}

            bid = _as_float(_quote_value(quote, ("bid_price", "bid", "bidPrice")))
            ask = _as_float(_quote_value(quote, ("ask_price", "ask", "askPrice")))
            mark = _as_float(_quote_value(quote, ("mark_price", "adjusted_mark_price", "mark", "markPrice")))
            iv = _as_float(
                _quote_value(
                    quote,
                    ("implied_volatility", "iv", "impliedVolatility"),
                )
            )
            spread_pct = None
            if bid is not None and ask is not None and ask >= bid:
                midpoint = (bid + ask) / 2
                if midpoint > 0:
                    spread_pct = round(((ask - bid) / midpoint) * 100, 4)

            contracts.append(
                {
                    "option_id": str(option_id) if option_id else None,
                    "symbol": _first_value(
                        row, ("chain_symbol", "symbol", "underlying_symbol")
                    ),
                    "expiration_date": _first_value(
                        row, ("expiration_date", "expiry", "expiration")
                    ),
                    "strike_price": _first_value(row, ("strike_price", "strike")),
                    "option_type": _first_value(row, ("type", "option_type")),
                    "trade_value_multiplier": _first_value(
                        row, ("trade_value_multiplier", "multiplier")
                    ),
                    "bid": bid,
                    "ask": ask,
                    "mark": mark,
                    "spread_pct": spread_pct,
                    "volume": _quote_value(quote, ("volume",)),
                    "open_interest": _quote_value(
                        quote, ("open_interest", "openInterest")
                    ),
                    "implied_volatility": iv,
                    "delta": _as_float(_quote_value(quote, ("delta",))),
                    "gamma": _as_float(_quote_value(quote, ("gamma",))),
                    "theta": _as_float(_quote_value(quote, ("theta",))),
                    "vega": _as_float(_quote_value(quote, ("vega",))),
                    "rho": _as_float(_quote_value(quote, ("rho",))),
                }
            )

        contracts.sort(
            key=lambda row: (
                row["spread_pct"] is None,
                row["spread_pct"] if row["spread_pct"] is not None else 999999,
            )
        )
        return contracts

    async def scan_symbol(self, symbol: str) -> OptionScanResult:
        symbol = symbol.strip().upper()
        if not symbol or len(symbol) > 12:
            raise ValueError("Invalid symbol.")

        catalog = await self.client.tool_catalog()
        errors: dict[str, str] = {}

        chains = None
        try:
            chains = await self._call_schema_aware(
                "get_option_chains",
                {"symbol": symbol},
                catalog,
            )
        except Exception as exc:
            errors["get_option_chains"] = str(exc)

        chain_id = self._chain_id(chains)
        eligible_expirations = self._eligible_expirations(chains)
        instrument_context: dict[str, Any] = {
            "symbol": symbol,
            "state": "active",
        }
        if chain_id:
            instrument_context["chain_id"] = chain_id
        if eligible_expirations:
            # build_arguments() only forwards keys actually advertised by the
            # live Robinhood schema, so supplying both singular/plural context
            # remains schema-safe.
            instrument_context["expiration_dates"] = eligible_expirations
            instrument_context["expiration_date"] = eligible_expirations[0]

        instruments = None
        try:
            instruments = await self._call_schema_aware(
                "get_option_instruments",
                instrument_context,
                catalog,
            )
        except Exception as exc:
            errors["get_option_instruments"] = str(exc)

        option_ids = self._option_ids(instruments)
        quotes = None
        if option_ids:
            try:
                quotes = await self._call_schema_aware(
                    "get_option_quotes",
                    {"symbol": symbol, "option_ids": option_ids[:100]},
                    catalog,
                )
            except Exception as exc:
                errors["get_option_quotes"] = str(exc)

        return OptionScanResult(
            symbol=symbol,
            scanned_at=datetime.now(timezone.utc).isoformat(),
            chain_count=len(extract_records(chains) or extract_candidate_records(chains)),
            instrument_count=len(extract_records(instruments) or extract_candidate_records(instruments)),
            quote_count=len(extract_records(quotes) or extract_candidate_records(quotes)),
            contracts=self._normalize_contracts(instruments, quotes),
            tool_errors=errors,
            response_shapes={
                "get_option_chains": payload_shape(chains),
                "get_option_instruments": payload_shape(instruments),
                "get_option_quotes": payload_shape(quotes),
            },
        )


robinhood_market_data = RobinhoodMarketDataService()
