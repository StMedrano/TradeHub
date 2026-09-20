from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


class MarketScanStatus(StrEnum):
    QUEUED = "queued"
    DISCOVERING = "discovering"
    DEEP_SCANNING = "deep_scanning"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class DiscoveredSymbol:
    symbol: str
    source_slice: str
    watchlist_priority: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EquityScreenResult:
    symbol: str
    passed: bool
    reasons: tuple[str, ...]
    priority_score: float
    price: Decimal | None = None
    average_volume: int | None = None
    market_cap: Decimal | None = None
    is_etf: bool = False


@dataclass(frozen=True)
class MarketOpportunity:
    symbol: str
    option_id: str
    candidate: dict[str, Any]
    risk_approved: bool
    risk_reasons: tuple[str, ...]
    scanned_at: str
