import pytest
from fastapi import HTTPException

from app.api.routes import _watchlist_symbols
from app.config import settings


def test_watchlist_symbols_normalizes_and_deduplicates(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 5)

    assert _watchlist_symbols("spy, SPY ,qqq") == ["SPY", "QQQ"]


def test_watchlist_symbols_uses_configured_default(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist", "abc,xyz")
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 5)

    assert _watchlist_symbols(None) == ["ABC", "XYZ"]


def test_watchlist_symbols_rejects_invalid_symbol(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 5)

    with pytest.raises(HTTPException) as exc:
        _watchlist_symbols("ABC,$BAD")

    assert exc.value.status_code == 400


def test_watchlist_symbols_enforces_scan_cap(monkeypatch):
    monkeypatch.setattr(settings, "strategy_watchlist_max_symbols", 2)

    with pytest.raises(HTTPException) as exc:
        _watchlist_symbols("AAA,BBB,CCC")

    assert exc.value.status_code == 400
