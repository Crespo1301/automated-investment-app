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
