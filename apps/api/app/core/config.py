"""Application settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized runtime settings.

    The scaffold keeps this minimal on purpose so we can add broker, AI,
    database, and queue credentials incrementally with a single source of truth.
    """

    environment: str = "development"
    app_name: str = "Automated Investment API"
    base_currency: str = "USD"
    trading_mode: str = "paper"
    allowed_symbols: str = "SPY,QQQ,NVDA,TSLA,AAPL"
    max_notional_per_trade: float = 2.0
    max_open_positions: int = 1
    max_live_trades_per_day: int = 3
    max_daily_loss: float = 2.0
    allow_live_trading: bool = False
    allow_outside_market_hours: bool = False
    duplicate_order_lookback_minutes: int = 390
    runtime_data_dir: str = ".runtime"
    autopilot_interval_seconds: int = 300
    autopilot_market_open_only: bool = True
    autopilot_allow_entries: bool = False
    autopilot_allow_exits: bool = False
    autopilot_stop_loss_percent: float = 2.0
    autopilot_take_profit_percent: float = 3.0
    allow_demo_live_entries: bool = False
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper: bool = True
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"

    model_config = SettingsConfigDict(
        env_prefix="INVESTMENT_APP_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()


def configured_symbols() -> list[str]:
    """Return the uppercase symbol universe allowed for automated trading."""

    return [
        symbol.strip().upper()
        for symbol in settings.allowed_symbols.split(",")
        if symbol.strip()
    ]
