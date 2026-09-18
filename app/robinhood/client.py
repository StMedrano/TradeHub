from typing import Any

import httpx2
from pydantic import AnyUrl

from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata

from app.config import settings
from app.robinhood.auth import JsonOAuthStorage
from app.robinhood.normalize import mcp_result_to_data


class RobinhoodAuthRequired(RuntimeError):
    pass


async def _reauth_redirect(auth_url: str) -> None:
    raise RobinhoodAuthRequired(
        "Robinhood authorization is required. Run: "
        "docker compose run --rm -it app python -m app.robinhood.auth_cli"
    )


async def _reauth_callback() -> AuthorizationCodeResult:
    raise RobinhoodAuthRequired(
        "Robinhood authorization callback is unavailable in unattended sync mode."
    )


class RobinhoodTradingMCP:
    """TradeHub's only market/account/order integration."""

    def __init__(self, url: str | None = None):
        self.url = url or settings.robinhood_mcp_url
        self.storage = JsonOAuthStorage(settings.robinhood_oauth_store)

    def auth_state_exists(self) -> bool:
        return self.storage.exists()

    def _provider(self) -> OAuthClientProvider:
        return OAuthClientProvider(
            server_url=self.url,
            client_metadata=OAuthClientMetadata(
                client_name="TradeHub",
                redirect_uris=[AnyUrl(settings.robinhood_oauth_redirect_uri)],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
            ),
            storage=self.storage,
            redirect_handler=_reauth_redirect,
            callback_handler=_reauth_callback,
        )

    async def call_raw(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not settings.robinhood_mcp_enabled:
            raise RuntimeError(
                "Robinhood MCP is disabled. Authenticate first, then enable it."
            )
        if not self.auth_state_exists():
            raise RobinhoodAuthRequired(
                "No Robinhood OAuth state exists. Run: "
                "docker compose run --rm -it app python -m app.robinhood.auth_cli"
            )

        oauth = self._provider()
        async with httpx2.AsyncClient(auth=oauth) as http_client:
            transport = streamable_http_client(self.url, http_client=http_client)
            async with Client(transport) as client:
                return await client.call_tool(tool_name, arguments)

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return mcp_result_to_data(await self.call_raw(tool_name, arguments))

    async def list_tools(self) -> Any:
        if not settings.robinhood_mcp_enabled:
            raise RuntimeError("Robinhood MCP is disabled.")
        if not self.auth_state_exists():
            raise RobinhoodAuthRequired("Robinhood OAuth state is missing.")

        oauth = self._provider()
        async with httpx2.AsyncClient(auth=oauth) as http_client:
            transport = streamable_http_client(self.url, http_client=http_client)
            async with Client(transport) as client:
                return await client.list_tools()

    async def accounts(self) -> Any:
        return await self.call("get_accounts", {})

    async def portfolio(self) -> Any:
        return await self.call("get_portfolio", {})

    async def realized_pnl(self, arguments: dict[str, Any]) -> Any:
        return await self.call("get_realized_pnl", arguments)

    async def equity_positions(self, arguments: dict[str, Any] | None = None) -> Any:
        return await self.call("get_equity_positions", arguments or {})

    async def equity_quotes(self, arguments: dict[str, Any]) -> Any:
        return await self.call("get_equity_quotes", arguments)

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
