import json
from typing import Any


def mcp_result_to_data(result: Any) -> Any:
    """Convert an MCP CallToolResult into ordinary Python data when possible."""
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured

    blocks = getattr(result, "content", None) or []
    values: list[Any] = []

    for block in blocks:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            values.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            values.append(text)

    if len(values) == 1:
        return values[0]
    return values


def find_first_number(value: Any, keys: tuple[str, ...]) -> float | None:
    """Recursively find the first numeric value for one of the requested keys."""
    wanted = {key.lower() for key in keys}

    def walk(node: Any) -> float | None:
        if isinstance(node, dict):
            for key, child in node.items():
                if str(key).lower() in wanted:
                    try:
                        return float(child)
                    except (TypeError, ValueError):
                        pass
            for child in node.values():
                found = walk(child)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for child in node:
                found = walk(child)
                if found is not None:
                    return found
        return None

    return walk(value)


def find_first_list(value: Any, keys: tuple[str, ...]) -> list[Any] | None:
    wanted = {key.lower() for key in keys}

    def walk(node: Any) -> list[Any] | None:
        if isinstance(node, dict):
            for key, child in node.items():
                if str(key).lower() in wanted and isinstance(child, list):
                    return child
            for child in node.values():
                found = walk(child)
                if found is not None:
                    return found
        return None

    return walk(value)


def count_records(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    rows = find_first_list(value, ("results", "positions", "orders", "items"))
    return len(rows) if rows is not None else 0



def extract_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("results", "positions", "orders", "items"):
            rows = find_first_list(value, (key,))
            if rows is not None:
                return [row for row in rows if isinstance(row, dict)]
    return []


def is_effectively_empty(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, (list, tuple, set, dict)):
        if not value:
            return True
        if isinstance(value, dict):
            return all(is_effectively_empty(child) for child in value.values())
        return all(is_effectively_empty(child) for child in value)
    return False


def extract_candidate_records(value: Any) -> list[dict[str, Any]]:
    """Recursively collect record-like dictionaries from MCP payloads.

    Robinhood tool responses may wrap arrays under names other than results/items,
    or return a single contract/chain object. We collect leaf-ish dictionaries
    that contain common market/account record fields.
    """
    records: list[dict[str, Any]] = []

    record_keys = {
        "id", "chain_id", "option_chain_id", "option_id", "instrument_id",
        "symbol", "chain_symbol", "underlying_symbol", "expiration_date",
        "strike_price", "type", "option_type", "bid_price", "ask_price",
        "mark_price", "delta", "gamma", "theta", "vega", "rho",
        "open_interest", "volume", "quantity", "state"
    }

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return

        if not isinstance(node, dict):
            return

        lowered = {str(k).lower() for k in node.keys()}
        if lowered & record_keys:
            records.append(node)

        for child in node.values():
            if isinstance(child, (dict, list)):
                walk(child)

    walk(value)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in records:
        try:
            marker = json.dumps(row, sort_keys=True, default=str)
        except TypeError:
            marker = str(row)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped
