from typing import Any


ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "chain_symbol", "underlying", "underlying_symbol", "ticker"),
    "symbols": ("symbols", "tickers", "underlyings"),
    "chain_id": ("chain_id", "option_chain_id"),
    "option_ids": ("option_ids", "instrument_ids", "ids", "option_instrument_ids"),
    "expiration_date": ("expiration_date", "expiry", "expiration"),
    "option_type": ("option_type", "type", "side"),
    "account_number": ("account_number", "account_id", "rhs_account_number"),
    "start_date": ("start_date", "from_date", "start"),
    "end_date": ("end_date", "to_date", "end"),
}


def _schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _required(schema: dict[str, Any]) -> set[str]:
    raw = schema.get("required", []) if isinstance(schema, dict) else []
    return {str(x) for x in raw if isinstance(x, str)}


def _lookup_context(field: str, context: dict[str, Any]) -> Any:
    if field in context:
        return context[field]
    for canonical, names in ALIASES.items():
        if field in names and canonical in context:
            return context[canonical]
    return None


def build_arguments(schema: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Build a tool call only from fields advertised by the live MCP schema."""
    props = _schema_properties(schema)
    required = _required(schema)
    args: dict[str, Any] = {}

    for field, spec in props.items():
        value = _lookup_context(field, context)
        if value is None:
            continue

        if isinstance(spec, dict) and spec.get("type") == "array" and not isinstance(value, list):
            value = [value]

        args[field] = value

    missing = [field for field in required if field not in args]
    if missing:
        raise ValueError(
            "Cannot satisfy Robinhood tool schema; missing context for: "
            + ", ".join(sorted(missing))
        )

    return args
