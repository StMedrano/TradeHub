from datetime import date
from decimal import Decimal

import pytest

from app.market_scanner.prefilter import (
    EquityPrefilter,
    EquityReadSnapshot,
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
