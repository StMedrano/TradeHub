import asyncio
from urllib.parse import parse_qs, urlparse

import httpx2
from pydantic import AnyUrl

from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata

from app.config import settings
from app.robinhood.auth import JsonOAuthStorage


async def redirect_handler(auth_url: str) -> None:
    print("\nOpen this URL on a desktop browser and authorize TradeHub:\n")
    print(auth_url)
    print(
        "\nAfter Robinhood redirects to localhost, the browser may show that the "
        "page cannot be reached. Copy the FULL URL from the browser address bar."
    )


async def callback_handler() -> AuthorizationCodeResult:
    callback_url = await asyncio.to_thread(
        input, "\nPaste the full callback URL here: "
    )
    params = parse_qs(urlparse(callback_url.strip()).query)
    if "code" not in params:
        raise RuntimeError("Callback URL does not contain an authorization code.")

    return AuthorizationCodeResult(
        code=params["code"][0],
        state=params.get("state", [None])[0],
        iss=params.get("iss", [None])[0],
    )


async def authenticate() -> None:
    storage = JsonOAuthStorage(settings.robinhood_oauth_store)

    oauth = OAuthClientProvider(
        server_url=settings.robinhood_mcp_url,
        client_metadata=OAuthClientMetadata(
            client_name="TradeHub",
            redirect_uris=[AnyUrl(settings.robinhood_oauth_redirect_uri)],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    async with httpx2.AsyncClient(auth=oauth) as http_client:
        transport = streamable_http_client(
            settings.robinhood_mcp_url,
            http_client=http_client,
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            names = [tool.name for tool in tools.tools]
            print("\nRobinhood authentication succeeded.")
            print(f"Discovered {len(names)} MCP tools.")
            read_tools = [
                name
                for name in names
                if name.startswith("get_") or name == "search"
            ]
            print("Read tools:", ", ".join(sorted(read_tools)))

    print(f"\nOAuth state saved to {settings.robinhood_oauth_store}.")
    print(
        "Set ROBINHOOD_MCP_ENABLED=true in .env, then restart TradeHub. "
        "Keep TRADING_MODE=dry_run and PHASE=0."
    )


def main() -> None:
    asyncio.run(authenticate())


if __name__ == "__main__":
    main()
