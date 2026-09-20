from enum import StrEnum
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class TradingMode(StrEnum):
    DRY_RUN = "dry_run"
    LIVE = "live"

class RiskCapitalMode(StrEnum):
    LIVE_ACCOUNT = "live_account"
    SIMULATION = "simulation"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    app_name: str = "TradeHub"
    database_url: str = "sqlite:///./tradehub.db"

    trading_mode: TradingMode = TradingMode.DRY_RUN
    risk_capital_mode: RiskCapitalMode = RiskCapitalMode.LIVE_ACCOUNT
    simulation_capital: float = Field(default=10000.0, gt=0)
    phase: int = Field(default=0, ge=0, le=2)
    require_approval: bool = True
    max_concurrent_positions: int = Field(default=1, ge=1)

    max_trade_loss_pct: float = Field(default=0.05, gt=0, le=1)
    max_portfolio_loss_pct: float = Field(default=0.20, gt=0, le=1)
    daily_loss_breaker_pct: float = Field(default=0.10, gt=0, le=1)

    liquidity_max_spread_pct: float = Field(default=0.10, gt=0, le=1)
    strategy_min_open_interest: int = Field(default=500, ge=0)
    strategy_min_volume: int = Field(default=50, ge=0)
    strategy_min_dte: int = Field(default=21, ge=0, le=3650)
    strategy_max_dte: int = Field(default=45, ge=1, le=3650)
    strategy_short_delta_min: float = Field(default=0.15, ge=0, le=1)
    strategy_short_delta_max: float = Field(default=0.30, ge=0, le=1)
    strategy_watchlist: str = ""
    strategy_watchlist_max_symbols: int = Field(default=5, ge=1, le=20)

    market_scanner_enabled: bool = False
    market_scanner_max_deep_symbols: int = Field(default=100, ge=1, le=1000)
    market_scanner_option_concurrency: int = Field(default=2, ge=1, le=10)
    market_scanner_min_price: float = Field(default=5.0, ge=0)
    market_scanner_min_avg_volume: int = Field(default=1_000_000, ge=0)
    market_scanner_min_market_cap: int = Field(default=1_000_000_000, ge=0)
    market_scanner_exclude_earnings: bool = True
    entry_timeout_seconds: int = Field(default=90, ge=1)
    price_walk_increment: float = Field(default=0.01, gt=0)
    max_slippage_pct: float = Field(default=0.08, ge=0, le=1)

    robinhood_mcp_url: str = "https://agent.robinhood.com/mcp/trading"
    robinhood_mcp_enabled: bool = False
    robinhood_spreads_enabled: bool = False
    robinhood_oauth_store: str = "/data/robinhood_oauth.json"
    robinhood_account_store: str = "/data/robinhood_account.json"
    robinhood_oauth_redirect_uri: str = "http://localhost:33418/callback"
    robinhood_sync_interval_seconds: int = Field(default=30, ge=10, le=3600)
    alert_provider: str = "disabled"

settings = Settings()
