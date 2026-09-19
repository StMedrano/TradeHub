import re
import json
import os
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any
from pathlib import Path

from app.config import settings
from app.robinhood.client import RobinhoodAuthRequired, RobinhoodTradingMCP
from app.robinhood.normalize import count_records, extract_records, find_first_list, find_first_number, is_effectively_empty, payload_shape
from app.robinhood.schema_args import build_arguments


OPEN_ORDER_STATES = {"queued", "confirmed", "partially_filled", "pending", "open"}


def _load_persisted_account_number() -> str | None:
    path = Path(settings.robinhood_account_store)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    value = raw.get("agentic_account_number") if isinstance(raw, dict) else None
    return str(value) if value else None


def _persist_account_number(account_number: str) -> None:
    path = Path(settings.robinhood_account_store)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"agentic_account_number": account_number}, indent=2),
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def _exception_message(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts = [_exception_message(child) for child in exc.exceptions]
        parts = [part for part in parts if part]
        return " | ".join(parts) if parts else str(exc)
    return str(exc)


def _is_transient_mcp_error(exc: BaseException) -> bool:
    message = _exception_message(exc).lower()
    return any(
        token in message
        for token in (
            "sse stream ended without a response",
            "connection reset",
            "connection closed",
            "server disconnected",
            "timed out",
            "timeout",
        )
    )


def _find_labeled_pnl_text(value: Any) -> float | None:
    if not isinstance(value, str):
        return None

    patterns = (
        r'(?im)^\s*(?:total[_\s-]*returns?|total[_\s-]*realized[_\s-]*(?:p&l|pnl|gain(?:_loss)?))\s*[:=|]\s*\$?\(?\s*([-+]?\d[\d,]*(?:\.\d+)?)',
        r'(?im)^\s*(?:realized[_\s-]*(?:p&l|pnl|gain(?:_loss)?))\s*[:=|]\s*\$?\(?\s*([-+]?\d[\d,]*(?:\.\d+)?)',
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        raw = match.group(1).replace(",", "")
        try:
            parsed = float(raw)
        except ValueError:
            continue
        # Parentheses after the label are commonly used for negative currency.
        line = match.group(0)
        if "(" in line and ")" in line and parsed > 0:
            parsed = -parsed
        return parsed
    return None


def _parse_realized_pnl(payload: Any) -> tuple[float | None, bool]:
    explicit_total_keys = (
        "total_returns",
        "total_return",
        "total_realized_gain_loss",
        "total_realized_pnl",
        "total_realized_gain",
        "net_realized_pnl",
    )
    component_keys = (
        "realized_gain_loss",
        "realized_pnl",
        "realized_gain",
        "realized_pl",
        "realized_profit_loss",
        "profit_loss",
        "pnl",
        "gain_loss",
        "amount",
    )

    # Prefer a server-provided aggregate if one exists anywhere in the payload.
    total = find_first_number(payload, explicit_total_keys)
    if total is not None:
        return total, True

    data_section = (
        payload.get("data")
        if isinstance(payload, dict) and "data" in payload
        else payload
    )
    if is_effectively_empty(data_section):
        return 0.0, True

    # Robinhood documents realized P&L as broken down by asset class. Sum one
    # realized value per result row when no explicit aggregate is provided.
    rows = find_first_list(
        data_section,
        ("results", "asset_classes", "breakdown", "items"),
    )
    if rows:
        values: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = find_first_number(row, component_keys)
            if value is not None:
                values.append(value)
        if values:
            return float(sum(values)), True

    # Fall back to a single recognized component when the payload is not list-shaped.
    value = find_first_number(data_section, component_keys)
    if value is not None:
        return value, True

    text_value = _find_labeled_pnl_text(payload)
    if text_value is not None:
        return text_value, True

    return None, False


def _parse_trade_history_daily_pnl(
    payload: Any,
    *,
    scoped_to_day: bool,
) -> tuple[float | None, bool]:
    data_section = (
        payload.get("data")
        if isinstance(payload, dict) and "data" in payload
        else payload
    )
    rows = find_first_list(
        data_section,
        ("results", "trades", "history", "items", "rows"),
    )

    if rows is not None and not rows:
        return (0.0, True) if scoped_to_day else (None, False)

    component_keys = (
        "realized_gain_loss",
        "realized_pnl",
        "realized_gain",
        "realized_pl",
        "realized_profit_loss",
        "profit_loss",
        "pnl",
        "gain_loss",
        "amount",
    )

    if rows:
        values: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = find_first_number(row, component_keys)
            if value is not None:
                values.append(value)
        if values and scoped_to_day:
            return float(sum(values)), True

    return None, False


@dataclass
class RobinhoodSnapshot:
    connection_state: str = "disabled"
    last_sync: str | None = None
    last_error: str | None = None
    tool_errors: dict[str, str] = field(default_factory=dict)
    agentic_account_number: str | None = None
    equity: float | None = None
    buying_power: float | None = None
    cash: float | None = None
    options_value: float | None = None
    realized_pnl_today: float | None = None
    realized_pnl_authoritative: bool = False
    realized_pnl_shape: Any = None
    realized_pnl_source: str | None = None
    pnl_trade_history_shape: Any = None
    open_equity_positions: int = 0
    open_option_positions: int = 0
    open_orders: int = 0
    raw_portfolio: Any = None
    equity_positions: list[dict[str, Any]] = field(default_factory=list)
    option_positions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def open_positions(self) -> int:
        return self.open_equity_positions + self.open_option_positions


class RobinhoodReadService:
    """Read-only synchronizer.

    This service never calls review_*, place_*, cancel_*, create_*, update_*,
    follow_*, unfollow_*, add_* or remove_* MCP tools.
    """

    def __init__(self, client: RobinhoodTradingMCP | None = None):
        self.client = client or RobinhoodTradingMCP()
        self.snapshot = RobinhoodSnapshot(
            agentic_account_number=_load_persisted_account_number()
        )
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def _call_read_with_retry(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        last_error: BaseException | None = None
        for attempt in range(2):
            try:
                return await self.client.call(tool_name, arguments)
            except BaseException as exc:
                last_error = exc
                if attempt == 0 and _is_transient_mcp_error(exc):
                    await asyncio.sleep(0.35)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{tool_name} failed without an exception.")

    async def _read(
        self,
        tool_name: str,
        *,
        account_number: str | None = None,
    ) -> Any:
        errors: list[BaseException] = []
        argument_options: list[dict[str, Any]] = [{}]
        if account_number:
            argument_options.append({"account_number": account_number})

        for arguments in argument_options:
            try:
                return await self._call_read_with_retry(tool_name, arguments)
            except BaseException as exc:
                errors.append(exc)

        message = " | ".join(_exception_message(exc) for exc in errors)
        raise RuntimeError(message)

    @staticmethod
    def _agentic_account_number(accounts: Any) -> str | None:
        rows = find_first_list(accounts, ("accounts", "results"))
        if not rows:
            return None

        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("agentic_allowed") is True:
                value = row.get("account_number") or row.get("rhs_account_number")
                if value:
                    return str(value)

        for row in rows:
            if isinstance(row, dict):
                value = row.get("account_number") or row.get("rhs_account_number")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _open_order_count(data: Any) -> int:
        rows = find_first_list(data, ("results", "orders", "items"))
        if rows is None:
            return count_records(data)

        count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            state = str(row.get("state", "")).lower()
            if state in OPEN_ORDER_STATES:
                count += 1
        return count

    async def sync_once(self) -> RobinhoodSnapshot:
        if not settings.robinhood_mcp_enabled:
            self.snapshot.connection_state = "disabled"
            self.snapshot.last_error = None
            return self.snapshot

        if not self.client.auth_state_exists():
            self.snapshot.connection_state = "authentication_required"
            self.snapshot.last_error = (
                "Robinhood OAuth state is missing. Run the auth bootstrap command."
            )
            return self.snapshot

        tool_errors: dict[str, str] = {}

        account_number = self.snapshot.agentic_account_number
        try:
            accounts = await self._call_read_with_retry("get_accounts", {})
            discovered_account = self._agentic_account_number(accounts)
            if discovered_account:
                account_number = discovered_account
                _persist_account_number(discovered_account)
        except RobinhoodAuthRequired as exc:
            self.snapshot.connection_state = "authentication_required"
            self.snapshot.last_error = str(exc)
            return self.snapshot
        except BaseException as exc:
            # Preserve a previously verified Agentic account number across
            # transient Robinhood transport failures.
            tool_errors["get_accounts"] = _exception_message(exc)

        async def read_tool(name: str) -> Any:
            try:
                return await self._read(name, account_number=account_number)
            except Exception as exc:
                tool_errors[name] = _exception_message(exc)
                return None

        portfolio = await read_tool("get_portfolio")
        equities = await read_tool("get_equity_positions")
        options = await read_tool("get_option_positions")
        option_orders = await read_tool("get_option_orders")

        realized_pnl = None
        realized_pnl_authoritative = False
        realized_pnl_shape = None
        realized_pnl_source = None
        pnl_trade_history_shape = None
        try:
            catalog = await self.client.tool_catalog()
            tool = catalog.get("get_realized_pnl")
            if tool:
                today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
                pnl_args = build_arguments(
                    tool.get("input_schema") or {},
                    {
                        "account_number": account_number,
                        "start_date": today,
                        "end_date": today,
                        "span": "day",
                    },
                )
                realized_payload = await self.client.call("get_realized_pnl", pnl_args)
                realized_pnl_shape = payload_shape(realized_payload)
                realized_pnl, realized_pnl_authoritative = _parse_realized_pnl(
                    realized_payload
                )
                if realized_pnl_authoritative:
                    realized_pnl_source = "get_realized_pnl"

            if not realized_pnl_authoritative:
                history_tool = catalog.get("get_pnl_trade_history")
                if history_tool:
                    history_schema = history_tool.get("input_schema") or {}
                    history_args = build_arguments(
                        history_schema,
                        {
                            "account_number": account_number,
                            "start_date": today,
                            "end_date": today,
                            "span": "day",
                            "limit": 500,
                        },
                    )
                    date_scope_fields = {
                        "start_date",
                        "from_date",
                        "start",
                        "since",
                        "after",
                        "end_date",
                        "to_date",
                        "end",
                        "until",
                        "before",
                        "span",
                        "period",
                        "window",
                    }
                    scoped_to_day = any(
                        key in history_args for key in date_scope_fields
                    )
                    history_payload = await self.client.call(
                        "get_pnl_trade_history",
                        history_args,
                    )
                    pnl_trade_history_shape = payload_shape(history_payload)
                    fallback_pnl, fallback_authoritative = (
                        _parse_trade_history_daily_pnl(
                            history_payload,
                            scoped_to_day=scoped_to_day,
                        )
                    )
                    if fallback_authoritative:
                        realized_pnl = fallback_pnl
                        realized_pnl_authoritative = True
                        realized_pnl_source = "get_pnl_trade_history"
        except Exception as exc:
            tool_errors["get_realized_pnl"] = _exception_message(exc)

        equity = (
            find_first_number(
                portfolio,
                ("total_value", "equity_value", "portfolio_value", "equity"),
            )
            if portfolio is not None
            else self.snapshot.equity
        )
        buying_power = (
            find_first_number(
                portfolio,
                ("buying_power", "unleveraged_buying_power", "real_time_buying_power"),
            )
            if portfolio is not None
            else self.snapshot.buying_power
        )
        cash = (
            find_first_number(portfolio, ("cash", "cash_value"))
            if portfolio is not None
            else self.snapshot.cash
        )
        options_value = (
            find_first_number(portfolio, ("options_value", "option_value"))
            if portfolio is not None
            else self.snapshot.options_value
        )

        open_equity_positions = (
            count_records(equities)
            if equities is not None
            else self.snapshot.open_equity_positions
        )
        open_option_positions = (
            count_records(options)
            if options is not None
            else self.snapshot.open_option_positions
        )
        open_orders = (
            self._open_order_count(option_orders)
            if option_orders is not None
            else self.snapshot.open_orders
        )
        equity_position_rows = (
            extract_records(equities)
            if equities is not None
            else self.snapshot.equity_positions
        )
        option_position_rows = (
            extract_records(options)
            if options is not None
            else self.snapshot.option_positions
        )

        self.snapshot = RobinhoodSnapshot(
            connection_state="connected" if portfolio is not None and not tool_errors else "degraded",
            last_sync=datetime.now(timezone.utc).isoformat(),
            last_error=None if not tool_errors else "One or more read tools failed.",
            tool_errors=tool_errors,
            agentic_account_number=account_number,
            equity=equity,
            buying_power=buying_power,
            cash=cash,
            options_value=options_value,
            realized_pnl_today=realized_pnl,
            realized_pnl_authoritative=realized_pnl_authoritative,
            realized_pnl_shape=realized_pnl_shape,
            realized_pnl_source=realized_pnl_source,
            pnl_trade_history_shape=pnl_trade_history_shape,
            open_equity_positions=open_equity_positions,
            open_option_positions=open_option_positions,
            open_orders=open_orders,
            raw_portfolio=portfolio if portfolio is not None else self.snapshot.raw_portfolio,
            equity_positions=equity_position_rows,
            option_positions=option_position_rows,
        )
        return self.snapshot

    async def run(self) -> None:
        self._stopping.clear()
        while not self._stopping.is_set():
            try:
                await self.sync_once()
            except Exception as exc:
                self.snapshot.connection_state = "error"
                self.snapshot.last_error = str(exc)

            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=settings.robinhood_sync_interval_seconds,
                )
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            await self._task
            self._task = None


robinhood_read_service = RobinhoodReadService()
