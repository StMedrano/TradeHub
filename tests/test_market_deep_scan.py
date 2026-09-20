import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.domain.models import AccountRiskSnapshot, RiskPolicy
from app.market_scanner.deep_scan import (
    MarketDeepScanService,
    RiskContext,
)
from app.market_scanner.prefilter import EquityReadSnapshot
from app.market_scanner.store import MarketScannerStore
from app.market_scanner.types import EquityScreenResult
from app.robinhood.client import RobinhoodAuthRequired
from app.robinhood.market_data import (
    OptionScanResult,
    READ_ONLY_OPTION_TOOLS,
    RobinhoodMarketDataService,
)
from app.robinhood.read_service import RobinhoodSnapshot


def make_store(symbols):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    store = MarketScannerStore(db)
    run = store.create_run(
        risk_capital_mode="simulation",
        risk_equity=Decimal("750000"),
        config_snapshot={},
    )
    for symbol in symbols:
        store.upsert_symbol(run.id, symbol, "test", False)
        store.mark_equity_screen(
            run.id,
            symbol,
            EquityScreenResult(
                symbol=symbol,
                passed=True,
                reasons=(),
                priority_score=10,
                price=Decimal("100"),
                average_volume=2_000_000,
                market_cap=Decimal("5000000000"),
                is_etf=True,
            ),
        )
    return store, run


def contract(
    symbol,
    *,
    option_id,
    strike,
    bid,
    multiplier=100,
    delta=-0.20,
):
    return {
        "option_id": option_id,
        "symbol": symbol,
        "expiration_date": (date.today() + timedelta(days=30)).isoformat(),
        "strike_price": str(strike),
        "option_type": "put",
        "trade_value_multiplier": str(multiplier),
        "bid": float(bid),
        "ask": float(Decimal(str(bid)) + Decimal("0.10")),
        "mark": float(Decimal(str(bid)) + Decimal("0.05")),
        "spread_pct": 2.0,
        "volume": 100,
        "open_interest": 1000,
        "implied_volatility": 0.30,
        "delta": delta,
        "theta": -0.03,
    }


def scan(symbol, rows):
    return OptionScanResult(
        symbol=symbol,
        scanned_at="2026-09-19T16:00:00+00:00",
        chain_count=1,
        instrument_count=len(rows),
        quote_count=len(rows),
        selected_expirations=[(date.today() + timedelta(days=30)).isoformat()],
        contracts=rows,
    )


class FakeMarketData:
    def __init__(self, results, fail_symbols=None, tracker=None):
        self.results = results
        self.fail_symbols = set(fail_symbols or [])
        self.tracker = tracker

    async def scan_symbol(self, symbol):
        if self.tracker is not None:
            self.tracker.active += 1
            self.tracker.max_seen = max(self.tracker.max_seen, self.tracker.active)
            await asyncio.sleep(0.01)
            self.tracker.active -= 1
        if symbol in self.fail_symbols:
            raise RuntimeError("transient MCP failure")
        return self.results[symbol]


class FakeRiskContextProvider:
    async def get(self):
        return RiskContext(
            authoritative=True,
            snapshot=AccountRiskSnapshot(
                equity=Decimal("750000"),
                open_position_max_loss=Decimal("0"),
                realized_pnl_today=Decimal("0"),
                concurrent_positions=0,
                paused_underlyings=frozenset(),
            ),
            strategy_snapshot=RobinhoodSnapshot(
                connection_state="connected",
                equity=750000,
                buying_power=750000,
                cash=750000,
                equity_positions=[],
            ),
            policy=RiskPolicy(
                max_trade_loss_pct=Decimal("0.05"),
                max_portfolio_loss_pct=Decimal("0.20"),
                daily_loss_breaker_pct=Decimal("0.10"),
                max_concurrent_positions=1,
                phase=0,
                require_approval=True,
            ),
            mode="simulation",
            reasons=(),
        )


@pytest.mark.asyncio
async def test_deep_scan_persists_only_risk_approved_matches():
    store, run = make_store(["AAPL"])
    market_data = FakeMarketData(
        {
            "AAPL": scan(
                "AAPL",
                [
                    contract("AAPL", option_id="pass", strike=325, bid=5),
                    contract("AAPL", option_id="miss", strike=500, bid=1),
                ],
            )
        }
    )
    service = MarketDeepScanService(
        market_data=market_data,
        store=store,
        risk_context_provider=FakeRiskContextProvider(),
    )

    result = await service.scan_symbol(run.id, "AAPL")

    assert result.match_count == 1
    assert [row.option_id for row in store.latest_opportunities("AAPL")] == ["pass"]
    assert [row.option_id for row in store.latest_near_misses("AAPL")] == ["miss"]


@pytest.mark.asyncio
async def test_deep_scan_uses_contract_multiplier_from_candidate():
    store, run = make_store(["ABC"])
    market_data = FakeMarketData(
        {
            "ABC": scan(
                "ABC",
                [contract("ABC", option_id="mult", strike=10, bid=1, multiplier=50)],
            )
        }
    )
    service = MarketDeepScanService(
        market_data=market_data,
        store=store,
        risk_context_provider=FakeRiskContextProvider(),
    )

    result = await service.scan_symbol(run.id, "ABC")

    assert Decimal(result.candidates[0]["estimated_max_loss"]) == Decimal("450")


@pytest.mark.asyncio
async def test_one_symbol_failure_does_not_discard_other_completed_symbol():
    store, run = make_store(["GOOD", "BAD"])
    market_data = FakeMarketData(
        {
            "GOOD": scan(
                "GOOD",
                [contract("GOOD", option_id="good", strike=100, bid=2)],
            ),
            "BAD": scan("BAD", []),
        },
        fail_symbols={"BAD"},
    )
    service = MarketDeepScanService(
        market_data=market_data,
        store=store,
        risk_context_provider=FakeRiskContextProvider(),
    )

    rows = await service.scan_many(run.id, ["GOOD", "BAD"])

    assert rows["GOOD"].status == "complete"
    assert rows["BAD"].status == "failed"
    assert store.get_symbol(run.id, "GOOD").option_scan_status == "complete"
    assert store.get_symbol(run.id, "BAD").option_scan_status == "failed"


class ConcurrencyTracker:
    def __init__(self):
        self.active = 0
        self.max_seen = 0


@pytest.mark.asyncio
async def test_scan_many_never_exceeds_configured_concurrency(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "market_scanner_option_concurrency", 2)
    symbols = ["A", "B", "C", "D"]
    store, run = make_store(symbols)
    tracker = ConcurrencyTracker()
    market_data = FakeMarketData(
        {
            symbol: scan(
                symbol,
                [contract(symbol, option_id=f"{symbol}-1", strike=100, bid=2)],
            )
            for symbol in symbols
        },
        tracker=tracker,
    )
    service = MarketDeepScanService(
        market_data=market_data,
        store=store,
        risk_context_provider=FakeRiskContextProvider(),
    )

    await service.scan_many(run.id, symbols)

    assert tracker.max_seen <= 2



class StrictReadOnlyMCP:
    forbidden = {
        "review_option_order",
        "place_option_order",
        "cancel_option_order",
    }

    def __init__(self):
        self.called_tool_names = []
        expiry = (date.today() + timedelta(days=30)).isoformat()
        self.expiry = expiry
        self.catalog = {
            "get_option_chains": {
                "name": "get_option_chains",
                "input_schema": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            },
            "get_equity_quotes": {
                "name": "get_equity_quotes",
                "input_schema": {
                    "type": "object",
                    "properties": {"symbols": {"type": "array"}},
                    "required": ["symbols"],
                },
            },
            "get_option_instruments": {
                "name": "get_option_instruments",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "state": {"type": "string"},
                        "expiration_dates": {"type": "array"},
                    },
                    "required": ["symbol"],
                },
            },
            "get_option_quotes": {
                "name": "get_option_quotes",
                "input_schema": {
                    "type": "object",
                    "properties": {"option_ids": {"type": "array"}},
                    "required": ["option_ids"],
                },
            },
            "review_option_order": {
                "name": "review_option_order",
                "input_schema": {"type": "object", "properties": {}},
            },
            "place_option_order": {
                "name": "place_option_order",
                "input_schema": {"type": "object", "properties": {}},
            },
            "cancel_option_order": {
                "name": "cancel_option_order",
                "input_schema": {"type": "object", "properties": {}},
            },
        }

    async def tool_catalog(self):
        return self.catalog

    async def call(self, tool_name, arguments):
        self.called_tool_names.append(tool_name)
        if tool_name in self.forbidden:
            raise AssertionError(f"Market scanner attempted forbidden order tool {tool_name}.")
        if tool_name not in READ_ONLY_OPTION_TOOLS:
            raise AssertionError(f"Market scanner attempted unapproved tool {tool_name}.")

        if tool_name == "get_option_chains":
            return {
                "data": [
                    {
                        "id": "chain-safe",
                        "symbol": "SAFE",
                        "expiration_dates": [self.expiry],
                    }
                ]
            }
        if tool_name == "get_equity_quotes":
            return {
                "data": [
                    {
                        "symbol": "SAFE",
                        "last_trade_price": "110",
                    }
                ]
            }
        if tool_name == "get_option_instruments":
            return {
                "data": [
                    {
                        "id": "safe-opt",
                        "chain_symbol": "SAFE",
                        "expiration_date": self.expiry,
                        "strike_price": "100",
                        "type": "put",
                        "trade_value_multiplier": "100",
                    }
                ]
            }
        if tool_name == "get_option_quotes":
            return {
                "data": [
                    {
                        "option_id": "safe-opt",
                        "bid_price": "2.00",
                        "ask_price": "2.10",
                        "mark_price": "2.05",
                        "open_interest": 1200,
                        "volume": 250,
                        "implied_volatility": "0.30",
                        "delta": "-0.20",
                        "theta": "-0.03",
                    }
                ]
            }
        raise AssertionError(f"Unhandled test tool {tool_name}.")


@pytest.mark.asyncio
async def test_market_scan_never_calls_robinhood_order_tools():
    store, run = make_store(["SAFE"])
    client = StrictReadOnlyMCP()
    service = MarketDeepScanService(
        market_data=RobinhoodMarketDataService(client),
        store=store,
        risk_context_provider=FakeRiskContextProvider(),
    )

    result = await service.scan_symbol(run.id, "SAFE")

    assert result.status == "complete"
    assert result.match_count == 1
    assert client.forbidden.isdisjoint(set(client.called_tool_names))
    assert set(client.called_tool_names).issubset(READ_ONLY_OPTION_TOOLS)



class ExplodingEquityProvider:
    async def snapshot(self, symbol):
        if symbol == "BAD":
            raise RuntimeError("earnings lookup failed")
        return EquityReadSnapshot(
            symbol=symbol,
            price=Decimal("100"),
            average_volume=2_000_000,
            market_cap=Decimal("5000000000"),
            is_etf=False,
            tradable=True,
            next_earnings_date=date.today() + timedelta(days=60),
        )


@pytest.mark.asyncio
async def test_post_market_data_symbol_failure_does_not_cancel_other_symbols():
    store, run = make_store(["GOOD", "BAD"])
    market_data = FakeMarketData(
        {
            symbol: scan(
                symbol,
                [contract(symbol, option_id=f"{symbol}-1", strike=100, bid=2)],
            )
            for symbol in ("GOOD", "BAD")
        }
    )
    service = MarketDeepScanService(
        market_data=market_data,
        store=store,
        risk_context_provider=FakeRiskContextProvider(),
        equity_provider=ExplodingEquityProvider(),
    )

    rows = await service.scan_many(run.id, ["GOOD", "BAD"])

    assert rows["GOOD"].status == "complete"
    assert rows["BAD"].status == "failed"
    assert store.get_symbol(run.id, "GOOD").option_scan_status == "complete"
    assert store.get_symbol(run.id, "BAD").option_scan_status == "failed"


class AuthMarketData:
    async def scan_symbol(self, symbol):
        raise RobinhoodAuthRequired("authentication required")


@pytest.mark.asyncio
async def test_auth_failure_is_not_downgraded_to_symbol_failure():
    store, run = make_store(["AUTH"])
    service = MarketDeepScanService(
        market_data=AuthMarketData(),
        store=store,
        risk_context_provider=FakeRiskContextProvider(),
    )

    with pytest.raises(RobinhoodAuthRequired):
        await service.scan_symbol(run.id, "AUTH")
