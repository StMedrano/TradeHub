import pytest

from app.robinhood.schema_args import build_arguments


def test_build_arguments_uses_live_schema_field_names():
    schema = {
        "type": "object",
        "properties": {
            "chain_symbol": {"type": "string"},
            "option_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["chain_symbol"],
    }

    args = build_arguments(
        schema,
        {
            "symbol": "SPY",
            "option_ids": ["a", "b"],
        },
    )

    assert args == {
        "chain_symbol": "SPY",
        "option_ids": ["a", "b"],
    }


def test_build_arguments_wraps_array_values():
    schema = {
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["symbols"],
    }

    assert build_arguments(schema, {"symbols": "SPY"}) == {"symbols": ["SPY"]}


def test_build_arguments_refuses_missing_required_fields():
    schema = {
        "type": "object",
        "properties": {
            "account_number": {"type": "string"},
        },
        "required": ["account_number"],
    }

    with pytest.raises(ValueError, match="account_number"):
        build_arguments(schema, {"symbol": "SPY"})
