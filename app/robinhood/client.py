from typing import Any
from mcp import Client
from app.config import settings

class RobinhoodTradingMCP:
    """TradeHub's only market/account/order integration."""

    def __init__(self, url: str | None = None):
        self.url = url or settings.robinhood_mcp_url

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not settings.robinhood_mcp_enabled:
            raise RuntimeError(
                "Robinhood MCP is disabled. Enable it only after authentication "
                "and dry-run validation."
            )
        async with Client(self.url) as client:
            return await client.call_tool(tool_name, arguments)

    async def list_tools(self) -> Any:
        if not settings.robinhood_mcp_enabled:
            raise RuntimeError("Robinhood MCP is disabled.")
        async with Client(self.url) as client:
            return await client.list_tools()

    async def equity_positions(self, arguments: dict[str, Any] | None = None) -> Any:
        return await self.call("get_equity_positions", arguments or {})

    async def option_chains(self, arguments: dict[str, Any]) -> Any:
        return await self.call("get_option_chains", arguments)

    async def option_instruments(self, arguments: dict[str, Any]) -> Any:
        return await self.call("get_option_instruments", arguments)

    async def option_quotes(self, arguments: dict[str, Any]) -> Any:
        return await self.call("get_option_quotes", arguments)

    async def option_positions(self, arguments: dict[str, Any] | None = None) -> Any:
        return await self.call("get_option_positions", arguments or {})

    async def option_orders(self, arguments: dict[str, Any] | None = None) -> Any:
        return await self.call("get_option_orders", arguments or {})

    async def review_option_order(self, arguments: dict[str, Any]) -> Any:
        return await self.call("review_option_order", arguments)

    async def place_option_order(self, arguments: dict[str, Any]) -> Any:
        return await self.call("place_option_order", arguments)

    async def cancel_option_order(self, arguments: dict[str, Any]) -> Any:
        return await self.call("cancel_option_order", arguments)
