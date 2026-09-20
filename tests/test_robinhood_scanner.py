import pytest

from app.market_scanner.robinhood_scanner import RobinhoodScannerService


class FakeScannerClient:
    def __init__(self):
        self.catalog = {
            name: {"name": name, "input_schema": {"type": "object", "properties": {}}}
            for name in {
                "get_scans",
                "get_scanner_filter_specs",
                "create_scan",
                "run_scan",
                "update_scan_filters",
                "update_scan_config",
            }
        }
        self.catalog["run_scan"]["input_schema"] = {
            "type": "object",
            "properties": {"scan_id": {"type": "string"}},
            "required": ["scan_id"],
        }
        self.catalog["create_scan"]["input_schema"] = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "filters": {"type": "array"},
                "sort": {"type": "object"},
            },
            "required": ["name"],
        }
        self.catalog["update_scan_filters"]["input_schema"] = {
            "type": "object",
            "properties": {
                "scan_id": {"type": "string"},
                "filters": {"type": "array"},
            },
            "required": ["scan_id", "filters"],
        }
        self.catalog["update_scan_config"]["input_schema"] = {
            "type": "object",
            "properties": {
                "scan_id": {"type": "string"},
                "sort": {"type": "object"},
            },
            "required": ["scan_id", "sort"],
        }
        self.responses = {
            "get_scans": {"data": []},
            "get_scanner_filter_specs": {
                "data": {
                    "filters": [
                        {"field": "price"},
                        {"field": "average_volume"},
                        {"field": "market_cap"},
                    ]
                }
            },
            "create_scan": {"data": {"id": "created-scan"}},
            "run_scan": {"data": []},
        }
        self.calls = []
        self.catalog_calls = 0

    async def tool_catalog(self):
        self.catalog_calls += 1
        return self.catalog

    async def call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return self.responses.get(tool_name, {"data": {}})


@pytest.mark.asyncio
async def test_filter_specs_requires_robinhood_scanner_tools():
    client = FakeScannerClient()
    client.catalog.pop("get_scanner_filter_specs")
    service = RobinhoodScannerService(client)

    with pytest.raises(RuntimeError, match="get_scanner_filter_specs"):
        await service.filter_specs()


@pytest.mark.asyncio
async def test_ensure_tradehub_scan_reuses_named_scan():
    client = FakeScannerClient()
    client.responses["get_scans"] = {
        "data": [{"id": "scan-1", "name": "TradeHub:market:price-5-50"}]
    }

    service = RobinhoodScannerService(client)
    scan_id = await service.ensure_tradehub_scan(
        "TradeHub:market:price-5-50",
        filters=[{"field": "price", "operator": "between", "value": [5, 50]}],
        sort={"field": "volume", "direction": "desc"},
    )

    assert scan_id == "scan-1"
    assert all(name != "create_scan" for name, _ in client.calls)
    assert (
        "update_scan_filters",
        {
            "scan_id": "scan-1",
            "filters": [{"field": "price", "operator": "between", "value": [5, 50]}],
        },
    ) in client.calls
    assert (
        "update_scan_config",
        {
            "scan_id": "scan-1",
            "sort": {"field": "volume", "direction": "desc"},
        },
    ) in client.calls


@pytest.mark.asyncio
async def test_missing_required_scanner_filter_is_reported_not_silently_skipped():
    client = FakeScannerClient()
    client.responses["get_scanner_filter_specs"] = {
        "data": {"filters": [{"field": "price"}]}
    }

    service = RobinhoodScannerService(client)
    support = await service.resolve_filter_support(
        {"price", "average_volume", "market_cap"}
    )

    assert support.available == {"price"}
    assert support.missing == {"average_volume", "market_cap"}


@pytest.mark.asyncio
async def test_run_scan_normalizes_and_deduplicates_symbols():
    client = FakeScannerClient()
    client.responses["run_scan"] = {
        "data": {
            "results": [
                {"symbol": "aapl"},
                {"ticker": "MSFT"},
                {"instrument": {"symbol": "AAPL"}},
                {"symbol": "BAD SYMBOL"},
            ]
        }
    }

    service = RobinhoodScannerService(client)
    rows = await service.run_scan("scan-1")

    assert [row["symbol"] for row in rows] == ["AAPL", "MSFT"]
    assert client.calls[-1] == ("run_scan", {"scan_id": "scan-1"})



@pytest.mark.asyncio
async def test_existing_scan_fails_closed_when_filters_cannot_be_reconciled():
    client = FakeScannerClient()
    client.catalog.pop("update_scan_filters")
    client.responses["get_scans"] = {
        "data": [{"id": "scan-1", "name": "TradeHub:market:price-5-50"}]
    }
    service = RobinhoodScannerService(client)

    with pytest.raises(RuntimeError, match="update_scan_filters"):
        await service.ensure_tradehub_scan(
            "TradeHub:market:price-5-50",
            filters=[{"field": "price", "operator": "between", "value": [5, 50]}],
            sort={"field": "volume", "direction": "desc"},
        )



@pytest.mark.asyncio
async def test_discovery_pushes_supported_liquidity_filters_into_robinhood_scan():
    client = FakeScannerClient()
    service = RobinhoodScannerService(client)

    await service.discover_slices()

    create_calls = [
        arguments
        for name, arguments in client.calls
        if name == "create_scan"
    ]
    assert create_calls

    first_filters = create_calls[0]["filters"]
    assert any(
        item.get("field") == "price"
        for item in first_filters
    )
    assert any(
        item.get("field") == "average_volume"
        and item.get("operator") == "gte"
        and item.get("value") == 1_000_000
        for item in first_filters
    )
    assert any(
        item.get("field") == "market_cap"
        and item.get("operator") == "gte"
        and item.get("value") == 1_000_000_000
        for item in first_filters
    )



@pytest.mark.asyncio
async def test_scanner_service_reuses_tool_catalog_within_process():
    client = FakeScannerClient()
    service = RobinhoodScannerService(client)

    await service.filter_specs()
    await service.run_scan("scan-1")

    assert client.catalog_calls == 1
