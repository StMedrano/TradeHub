from types import SimpleNamespace

import pytest

from app.robinhood import client as client_module
from app.robinhood.client import RobinhoodTradingMCP


class FlakyCatalogClient(RobinhoodTradingMCP):
    def __init__(self):
        self.calls = 0

    async def list_tools(self):
        self.calls += 1
        if self.calls == 1:
            raise ExceptionGroup(
                "transient MCP transport failure",
                [RuntimeError("SSE stream ended without a response")],
            )
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="get_equity_quotes",
                    description="Equity quotes",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]
        )


class FatalCatalogClient(RobinhoodTradingMCP):
    def __init__(self):
        self.calls = 0

    async def list_tools(self):
        self.calls += 1
        raise RuntimeError("invalid tool schema")


@pytest.mark.asyncio
async def test_tool_catalog_retries_transient_sse_failure(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", no_sleep)
    client = FlakyCatalogClient()

    catalog = await client.tool_catalog()

    assert client.calls == 2
    assert "get_equity_quotes" in catalog


@pytest.mark.asyncio
async def test_tool_catalog_does_not_retry_non_transient_failure(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", no_sleep)
    client = FatalCatalogClient()

    with pytest.raises(RuntimeError, match="invalid tool schema"):
        await client.tool_catalog()

    assert client.calls == 1
