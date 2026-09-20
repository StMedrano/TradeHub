from app.config import Settings
from app.market_scanner.types import MarketScanStatus


def test_market_scanner_defaults_are_conservative_and_disabled():
    cfg = Settings(_env_file=None)

    assert cfg.market_scanner_enabled is False
    assert cfg.market_scanner_max_deep_symbols == 100
    assert cfg.market_scanner_option_concurrency == 2
    assert cfg.market_scanner_min_price == 5.0
    assert cfg.market_scanner_min_avg_volume == 1_000_000
    assert cfg.market_scanner_min_market_cap == 1_000_000_000
    assert cfg.market_scanner_exclude_earnings is True

    assert cfg.strategy_min_dte == 21
    assert cfg.strategy_max_dte == 45
    assert cfg.strategy_short_delta_min == 0.15
    assert cfg.strategy_short_delta_max == 0.30
    assert cfg.strategy_min_open_interest == 500
    assert cfg.strategy_min_volume == 50
    assert cfg.liquidity_max_spread_pct == 0.10


def test_market_scan_status_values_are_stable():
    assert MarketScanStatus.QUEUED.value == "queued"
    assert MarketScanStatus.DISCOVERING.value == "discovering"
    assert MarketScanStatus.DEEP_SCANNING.value == "deep_scanning"
    assert MarketScanStatus.COMPLETE.value == "complete"
    assert MarketScanStatus.PARTIAL.value == "partial"
    assert MarketScanStatus.FAILED.value == "failed"
