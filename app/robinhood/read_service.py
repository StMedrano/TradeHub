import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from app.config import settings
from app.robinhood.client import RobinhoodAuthRequired, RobinhoodTradingMCP
from app.robinhood.normalize import count_records, extract_records, find_first_list, find_first_number, is_effectively_empty
from app.robinhood.schema_args import build_arguments


OPEN_ORDER_STATES = {"queued", "confirmed", "partially_filled", "pending", "open"}


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
        self.snapshot = RobinhoodSnapshot()
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
                realized_pnl = find_first_number(
                    realized_payload,
                    (
                        "realized_pnl",
                        "realized_pl",
                        "total_realized_pnl",
                        "realized_profit_loss",
                        "net_realized_pnl",
                        "pnl",
                        "profit_loss",
                        "amount",
                        "total",
                    ),
                )
                if realized_pnl is not None:
                    realized_pnl_authoritative = True
                elif is_effectively_empty(realized_payload):
                    # A successful empty same-day query means no realized P&L yet today.
                    realized_pnl = 0.0
                    realized_pnl_authoritative = True
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
