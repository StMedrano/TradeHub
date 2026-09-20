from dataclasses import dataclass
from typing import Any

from app.market_scanner.types import DiscoveredSymbol
from app.robinhood.client import RobinhoodTradingMCP
from app.robinhood.schema_args import build_arguments


SCANNER_TOOLS = {
    "get_scans",
    "get_scanner_filter_specs",
    "create_scan",
    "run_scan",
    "update_scan_filters",
    "update_scan_config",
}

_PRICE_BANDS = (
    ("5-25", 5, 25),
    ("25-50", 25, 50),
    ("50-100", 50, 100),
    ("100-250", 100, 250),
    ("250-500", 250, 500),
    ("500-plus", 500, None),
)


@dataclass(frozen=True)
class FilterSupport:
    available: set[str]
    missing: set[str]


def _dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _dicts(item)


def _first_value(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _scan_id(payload: Any) -> str | None:
    for row in _dicts(payload):
        value = _first_value(row, ("id", "scan_id"))
        if value:
            return str(value)
    return None


def _scan_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _dicts(payload):
        symbol = _first_value(row, ("symbol", "ticker"))
        if symbol is None and isinstance(row.get("instrument"), dict):
            symbol = _first_value(row["instrument"], ("symbol", "ticker"))
        if symbol is None:
            continue

        normalized = str(symbol).strip().upper()
        if not normalized or len(normalized) > 12:
            continue
        if not all(ch.isalnum() or ch in ".-" for ch in normalized):
            continue

        copy = dict(row)
        copy["symbol"] = normalized
        rows.append(copy)

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(str(row["symbol"]), row)
    return list(unique.values())


class RobinhoodScannerService:
    """Schema-aware Robinhood saved scanner adapter.

    Scanner management is intentionally isolated from option/order execution.
    """

    def __init__(self, client: RobinhoodTradingMCP | None = None):
        self.client = client or RobinhoodTradingMCP()

    async def _catalog(self) -> dict[str, dict[str, Any]]:
        return await self.client.tool_catalog()

    @staticmethod
    def _require_tool(
        catalog: dict[str, dict[str, Any]],
        tool_name: str,
    ) -> dict[str, Any]:
        if tool_name not in SCANNER_TOOLS:
            raise RuntimeError(f"{tool_name} is not an approved scanner tool.")
        tool = catalog.get(tool_name)
        if tool is None:
            raise RuntimeError(f"Robinhood MCP did not advertise {tool_name}.")
        return tool

    async def _call(
        self,
        tool_name: str,
        context: dict[str, Any],
        catalog: dict[str, dict[str, Any]] | None = None,
    ) -> Any:
        catalog = catalog or await self._catalog()
        tool = self._require_tool(catalog, tool_name)
        args = build_arguments(tool.get("input_schema") or {}, context)
        return await self.client.call(tool_name, args)

    async def filter_specs(self) -> Any:
        catalog = await self._catalog()
        return await self._call("get_scanner_filter_specs", {}, catalog)

    async def resolve_filter_support(self, desired: set[str]) -> FilterSupport:
        payload = await self.filter_specs()
        advertised: set[str] = set()
        for row in _dicts(payload):
            name = _first_value(row, ("field", "name", "key", "id"))
            if isinstance(name, str):
                advertised.add(name)
        return FilterSupport(
            available=desired & advertised,
            missing=desired - advertised,
        )

    async def ensure_tradehub_scan(
        self,
        name: str,
        filters: list[dict[str, Any]],
        sort: dict[str, Any] | None = None,
    ) -> str:
        catalog = await self._catalog()
        scans = await self._call("get_scans", {}, catalog)
        for row in _dicts(scans):
            if str(row.get("name") or "") != name:
                continue
            existing_id = _first_value(row, ("id", "scan_id"))
            if not existing_id:
                continue

            scan_id = str(existing_id)
            filter_context = {
                "scan_id": scan_id,
                "id": scan_id,
                "filters": filters,
            }
            await self._call(
                "update_scan_filters",
                filter_context,
                catalog,
            )

            if sort is not None:
                sort_field = sort.get("field")
                sort_direction = sort.get("direction")
                config_context = {
                    "scan_id": scan_id,
                    "id": scan_id,
                    "sort": sort,
                    "sort_config": sort,
                    "config": {"sort": sort},
                    "sort_field": sort_field,
                    "sort_by": sort_field,
                    "field": sort_field,
                    "direction": sort_direction,
                    "sort_direction": sort_direction,
                }
                await self._call(
                    "update_scan_config",
                    config_context,
                    catalog,
                )

            return scan_id

        created = await self._call(
            "create_scan",
            {"name": name, "filters": filters, "sort": sort},
            catalog,
        )
        created_id = _scan_id(created)
        if not created_id:
            raise RuntimeError("Robinhood create_scan returned no scan identifier.")
        return created_id

    async def run_scan(self, scan_id: str) -> list[dict[str, Any]]:
        catalog = await self._catalog()
        payload = await self._call(
            "run_scan",
            {"scan_id": scan_id},
            catalog,
        )
        return _scan_rows(payload)

    async def discover_slices(self) -> list[DiscoveredSymbol]:
        support = await self.resolve_filter_support(
            {"price", "average_volume", "market_cap", "volume"}
        )

        discovered: dict[str, DiscoveredSymbol] = {}
        if "price" in support.available:
            for label, minimum, maximum in _PRICE_BANDS:
                value: list[float | int] = [minimum]
                if maximum is not None:
                    value.append(maximum)
                filters = [
                    {
                        "field": "price",
                        "operator": "between" if maximum is not None else "gte",
                        "value": value if maximum is not None else minimum,
                    }
                ]
                sort_field = (
                    "average_volume"
                    if "average_volume" in support.available
                    else "volume"
                    if "volume" in support.available
                    else "price"
                )
                scan_id = await self.ensure_tradehub_scan(
                    f"TradeHub:market:price-{label}",
                    filters=filters,
                    sort={"field": sort_field, "direction": "desc"},
                )
                for row in await self.run_scan(scan_id):
                    symbol = str(row["symbol"])
                    discovered.setdefault(
                        symbol,
                        DiscoveredSymbol(
                            symbol=symbol,
                            source_slice=f"price-{label}",
                            raw=row,
                        ),
                    )
        else:
            scan_id = await self.ensure_tradehub_scan(
                "TradeHub:market:broad",
                filters=[],
                sort=None,
            )
            for row in await self.run_scan(scan_id):
                symbol = str(row["symbol"])
                discovered.setdefault(
                    symbol,
                    DiscoveredSymbol(
                        symbol=symbol,
                        source_slice="broad",
                        raw=row,
                    ),
                )

        return list(discovered.values())


robinhood_scanner_service = RobinhoodScannerService()
