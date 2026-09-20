from datetime import date
from decimal import Decimal

import pytest

from app.market_scanner.prefilter import (
    EquityPrefilter,
    EquityReadSnapshot,
    RobinhoodEquityReadProvider,
)


class FakeEquityProvider:
    def __init__(self):
        self.value = EquityReadSnapshot(
            symbol="ABC",
            price=Decimal("50"),
            average_volume=2_000_000,
            market_cap=Decimal("5000000000"),
            is_etf=False,
            tradable=True,
            next_earnings_date=None,
        )

    async def snapshot(self, symbol: str):
        data = self.value
        return EquityReadSnapshot(
            symbol=symbol,
            price=data.price,
            average_volume=data.average_volume,
            market_cap=data.market_cap,
            is_etf=data.is_etf,
            tradable=data.tradable,
            next_earnings_date=data.next_earnings_date,
        )


@pytest.mark.asyncio
async def test_untradable_symbol_fails_even_when_watchlist_priority():
    provider = FakeEquityProvider()
    provider.value = EquityReadSnapshot(
        symbol="ABC",
        price=Decimal("50"),
        average_volume=2_000_000,
        market_cap=Decimal("5000000000"),
        is_etf=False,
        tradable=False,
        next_earnings_date=None,
    )
    prefilter = EquityPrefilter(provider)

    result = await prefilter.screen(
        "ABC",
        watchlist_priority=True,
        capacity=Decimal("37500"),
    )

    assert result.passed is False
    assert "Robinhood reports the symbol is not tradable." in result.reasons


@pytest.mark.asyncio
async def test_price_below_five_fails():
    provider = FakeEquityProvider()
    provider.value = EquityReadSnapshot(
        symbol="ABC",
        price=Decimal("4.99"),
        average_volume=2_000_000,
        market_cap=Decimal("5000000000"),
        is_etf=False,
        tradable=True,
        next_earnings_date=None,
    )
    result = await EquityPrefilter(provider).screen(
        "ABC", False, Decimal("37500")
    )

    assert result.passed is False
    assert any("minimum 5" in reason for reason in result.reasons)


@pytest.mark.asyncio
async def test_missing_required_average_volume_fails_closed():
    provider = FakeEquityProvider()
    provider.value = EquityReadSnapshot(
        symbol="ABC",
        price=Decimal("50"),
        average_volume=None,
        market_cap=Decimal("5000000000"),
        is_etf=False,
        tradable=True,
        next_earnings_date=None,
    )
    result = await EquityPrefilter(provider).screen(
        "ABC", False, Decimal("37500")
    )

    assert result.passed is False
    assert any("average volume" in reason.lower() for reason in result.reasons)


@pytest.mark.asyncio
async def test_market_cap_below_minimum_fails():
    provider = FakeEquityProvider()
    provider.value = EquityReadSnapshot(
        symbol="ABC",
        price=Decimal("50"),
        average_volume=2_000_000,
        market_cap=Decimal("999999999"),
        is_etf=False,
        tradable=True,
        next_earnings_date=None,
    )
    result = await EquityPrefilter(provider).screen(
        "ABC", False, Decimal("37500")
    )

    assert result.passed is False
    assert any("market cap" in reason.lower() for reason in result.reasons)


@pytest.mark.asyncio
async def test_single_stock_with_earnings_before_expiration_fails():
    provider = FakeEquityProvider()
    provider.value = EquityReadSnapshot(
        symbol="ABC",
        price=Decimal("50"),
        average_volume=2_000_000,
        market_cap=Decimal("5000000000"),
        is_etf=False,
        tradable=True,
        next_earnings_date=date(2026, 10, 12),
    )
    result = await EquityPrefilter(provider).screen(
        "ABC",
        False,
        Decimal("37500"),
        expiration_dates=[date(2026, 10, 16)],
    )

    assert result.passed is False
    assert any("earnings" in reason.lower() for reason in result.reasons)


@pytest.mark.asyncio
async def test_etf_does_not_require_corporate_earnings():
    provider = FakeEquityProvider()
    provider.value = EquityReadSnapshot(
        symbol="ETF",
        price=Decimal("50"),
        average_volume=2_000_000,
        market_cap=Decimal("5000000000"),
        is_etf=True,
        tradable=True,
        next_earnings_date=None,
    )
    result = await EquityPrefilter(provider).screen(
        "ETF", False, Decimal("37500")
    )

    assert result.passed is True


@pytest.mark.asyncio
async def test_high_spot_price_lowers_priority_without_rejecting():
    provider = FakeEquityProvider()
    prefilter = EquityPrefilter(provider)

    provider.value = EquityReadSnapshot(
        symbol="LOW",
        price=Decimal("25"),
        average_volume=2_000_000,
        market_cap=Decimal("5000000000"),
        is_etf=True,
        tradable=True,
        next_earnings_date=None,
    )
    low = await prefilter.screen("LOW", False, Decimal("37500"))

    provider.value = EquityReadSnapshot(
        symbol="HIGH",
        price=Decimal("750"),
        average_volume=2_000_000,
        market_cap=Decimal("5000000000"),
        is_etf=True,
        tradable=True,
        next_earnings_date=None,
    )
    high = await prefilter.screen("HIGH", False, Decimal("37500"))

    assert low.passed is True
    assert high.passed is True
    assert high.priority_score < low.priority_score



class EtfReadClient:
    def __init__(self):
        self.calls = []
        self.catalog = {
            "get_equity_quotes": {
                "name": "get_equity_quotes",
                "input_schema": {
                    "type": "object",
                    "properties": {"symbols": {"type": "array"}},
                    "required": ["symbols"],
                },
            },
            "get_equity_fundamentals": {
                "name": "get_equity_fundamentals",
                "input_schema": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            },
            "get_equity_tradability": {
                "name": "get_equity_tradability",
                "input_schema": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            },
        }

    async def tool_catalog(self):
        return self.catalog

    async def call(self, tool_name, arguments):
        self.calls.append(tool_name)
        if tool_name == "get_equity_quotes":
            return {"data": [{"symbol": "ETF", "last_trade_price": "50"}]}
        if tool_name == "get_equity_fundamentals":
            return {
                "data": [{
                    "symbol": "ETF",
                    "security_type": "ETF",
                    "average_volume": 2_000_000,
                    "market_cap": 5_000_000_000,
                }]
            }
        if tool_name == "get_equity_tradability":
            return {"data": [{"symbol": "ETF", "tradable": True}]}
        raise AssertionError(f"Unexpected tool call: {tool_name}")


@pytest.mark.asyncio
async def test_robinhood_provider_does_not_require_earnings_tool_for_etf():
    client = EtfReadClient()
    snapshot = await RobinhoodEquityReadProvider(client).snapshot("ETF")

    assert snapshot.is_etf is True
    assert snapshot.next_earnings_date is None
    assert "get_earnings_calendar" not in client.calls
