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
