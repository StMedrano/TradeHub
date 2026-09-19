import ast
import json
import re
from typing import Any


def _decode_json_text(value: Any) -> Any:
    """Decode JSON-ish MCP text without inventing structure for plain text."""
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            body = lines[1:-1]
            if body and body[0].strip().lower() in {"json", "javascript"}:
                body = body[1:]
            text = "\n".join(body).strip()

    decoded: Any = text
    for _ in range(3):
        if not isinstance(decoded, str):
            break

        candidate = decoded.strip()

        # Only deserialize text that actually looks like a serialized
        # structure. Ordinary field values such as "12.34" must remain
        # strings; downstream numeric readers can convert them deliberately.
        if candidate[:1] not in {"{", "[", "(", '"'}:
            break

        parsed: Any = None
        parsed_ok = False

        try:
            parsed = json.loads(candidate)
            parsed_ok = True
        except (json.JSONDecodeError, TypeError):
            # Some MCP implementations serialize Python-style literal
            # structures instead of strict JSON. literal_eval is restricted
            # to Python literals and does not execute arbitrary code.
            if candidate[:1] in {"{", "[", "("}:
                try:
                    parsed = ast.literal_eval(candidate)
                    parsed_ok = isinstance(
                        parsed,
                        (dict, list, tuple, str, int, float, bool, type(None)),
                    )
                except (ValueError, SyntaxError, TypeError):
                    parsed_ok = False

        if not parsed_ok:
            break

        decoded = list(parsed) if isinstance(parsed, tuple) else parsed

    return decoded


def normalize_mcp_data(value: Any) -> Any:
    """Recursively normalize JSON text returned through MCP payloads."""
    decoded = _decode_json_text(value)

    if isinstance(decoded, dict):
        return {
            key: normalize_mcp_data(child)
            for key, child in decoded.items()
        }

    if isinstance(decoded, list):
        return [normalize_mcp_data(child) for child in decoded]

    return decoded


def mcp_result_to_data(result: Any) -> Any:
    """Convert an MCP CallToolResult into ordinary Python data when possible."""
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return normalize_mcp_data(structured)

    blocks = getattr(result, "content", None) or []
    values: list[Any] = []

    for block in blocks:
        text = getattr(block, "text", None)
        if text is None:
            continue
        values.append(_decode_json_text(text))

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
    rows = find_first_list(value, ("results", "positions", "orders", "items", "chains", "instruments"))
    return len(rows) if rows is not None else 0



def extract_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("results", "positions", "orders", "items", "chains", "instruments"):
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



def payload_shape(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Return structure metadata only; never return payload values."""
    if depth >= max_depth:
        if isinstance(value, list):
            return {"type": "list", "length": len(value)}
        if isinstance(value, dict):
            return {"type": "object", "keys": sorted(str(k) for k in value.keys())}
        return {"type": type(value).__name__}

    if isinstance(value, list):
        sample = value[:3]
        return {
            "type": "list",
            "length": len(value),
            "items": [payload_shape(item, depth + 1, max_depth) for item in sample],
        }

    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": sorted(str(k) for k in value.keys()),
            "children": {
                str(key): payload_shape(child, depth + 1, max_depth)
                for key, child in list(value.items())[:20]
                if isinstance(child, (dict, list))
            },
        }

    return {"type": type(value).__name__}



def redacted_text_fingerprint(value: Any, max_lines: int = 16) -> dict[str, Any] | None:
    """Return text structure/labels with numeric and identifier-like values masked."""
    if not isinstance(value, str):
        return None

    lines: list[str] = []
    for raw_line in value.splitlines()[:max_lines]:
        line = raw_line.strip()
        if not line:
            continue

        # Mask UUIDs, long identifier-like tokens, currency/numeric values,
        # percentages, and ISO-ish dates while preserving human-readable labels.
        line = re.sub(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{20,}\b",
            "<id>",
            line,
        )
        line = re.sub(
            r"\b(?=[A-Za-z0-9_-]{10,}\b)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+\b",
            "<id>",
            line,
        )
        line = re.sub(
            r"(?<![A-Za-z])[-+]?\$?\(?\d[\d,]*(?:\.\d+)?\)?%?",
            "<num>",
            line,
        )

        lines.append(line[:240])

    return {
        "type": "plain_text",
        "length": len(value),
        "lines": lines,
    }
