"""Application settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


# Liquid mega-cap subset for options. The full equity universe is too wide
# to support clean options liquidity for every name; this list is the
# starting point for the options scanner and is overridable via
# ``INVESTMENT_APP_OPTIONS_ALLOWED_UNDERLYINGS``.
DEFAULT_OPTIONS_UNDERLYINGS = (
    "SPY,QQQ,IWM,DIA,"
    "AAPL,MSFT,NVDA,AMD,TSLA,META,AMZN,GOOGL,GOOG,AVGO,"
    "NFLX,COIN,MSTR,SMH"
)


DEFAULT_ALLOWED_SYMBOLS = (
    "SPY,QQQ,DIA,IWM,VTI,VOO,SCHD,XLK,XLF,XLV,XLI,XLE,XLP,XLY,SMH,SOXX,"
    "ARKK,ARKW,ARKG,IBB,XBI,KRE,TLT,HYG,LQD,GLD,SLV,USO,"
    "NVDA,AAPL,MSFT,AMZN,GOOGL,GOOG,META,TSLA,AMD,AVGO,ORCL,CRM,ADBE,NFLX,"
    "INTC,QCOM,AMAT,LRCX,KLAC,ASML,MU,TSM,ARM,SMCI,DELL,IBM,NOW,SNOW,PLTR,"
    "SHOP,UBER,ABNB,DASH,COIN,HOOD,SQ,PYPL,ROKU,NET,DDOG,CRWD,PANW,ZS,"
    "TWLO,OKTA,MDB,U,DOCU,"
    "JPM,BAC,WFC,C,GS,MS,V,MA,AXP,BLK,SCHW,COF,SOFI,"
    "UNH,LLY,NVO,MRK,ABBV,JNJ,PFE,AMGN,GILD,REGN,ISRG,TMO,ABT,MDT,"
    "XOM,CVX,COP,SLB,OXY,ENPH,FSLR,NEE,"
    "COST,WMT,TGT,HD,LOW,MCD,SBUX,NKE,LULU,PG,KO,PEP,CL,EL,CHWY,"
    "CAT,DE,GE,BA,LMT,NOC,RTX,HON,UPS,FDX,URI,ETN,EMR,"
    "DIS,CMCSA,T,VZ,TMUS,SPOT,RBLX,PINS,SNAP,"
    "F,GM,RIVN,LCID,NIO,LI,XPEV,"
    "AAL,UAL,DAL,"
    "BABA,JD,PDD,MELI,SE,NU,"
    "GME,SOUN,BBAI,"
    "CVNA,AFRM,UPST,DKNG,RIOT,MARA,MSTR,IONQ,APP,TTD"
)


class Settings(BaseSettings):
    """Centralized runtime settings.

    The scaffold keeps this minimal on purpose so we can add broker, AI,
    database, and queue credentials incrementally with a single source of truth.
    """

    environment: str = "development"
    app_name: str = "Automated Investment API"
    base_currency: str = "USD"
    trading_mode: str = "paper"
    allowed_symbols: str = DEFAULT_ALLOWED_SYMBOLS
    max_symbols_per_cycle: int = 90
    position_size_percent: float = 0.25
    max_open_positions: int = 6
    # Cap each new entry at this fraction of the *currently available* buying
    # power. Prevents the loop from eating 100% of buying power on a single
    # trade once a few positions are open. Default 0.50 = at most half of
    # available buying power per trade, so even with multiple consecutive
    # entries, sizing decays smoothly instead of cliffing to zero.
    max_buying_power_utilization_per_trade: float = 0.5
    # Cash reserve as a fraction of *current portfolio value*. Default 0.10
    # = always keep ~10% of the portfolio in cash before sizing the next
    # entry. Scales with the account: a $10 portfolio reserves $1, a $1000
    # portfolio reserves $100. Prefer this over an absolute dollar floor so
    # the buffer doesn't cliff at Alpaca's $1 minimum as the portfolio grows.
    cash_reserve_percent_of_portfolio: float = 0.10
    max_day_trades_5_business_days: int = 3
    max_daily_loss: float = 2.0
    strategy_breakout_threshold: float = 0.0025
    strategy_min_volume: float = 25_000
    strategy_stop_loss_percent: float = 0.025
    high_upside_breakout_threshold: float = 0.012
    high_upside_min_recent_volume_ratio: float = 3.0
    high_upside_stop_loss_percent: float = 0.04
    high_upside_take_profit_percent: float = 0.12
    high_upside_max_spread_bps: float = 50.0
    high_upside_require_known_market_regime: bool = True
    high_upside_require_known_news_sentiment: bool = False
    ai_min_score: float = 0.55
    max_entry_spread_bps: float = 75.0
    allow_live_trading: bool = False
    allow_outside_market_hours: bool = False
    duplicate_order_lookback_minutes: int = 390
    runtime_data_dir: str = ".runtime"
    autopilot_interval_seconds: int = 30
    autopilot_market_open_only: bool = True
    autopilot_allow_entries: bool = False
    autopilot_allow_exits: bool = False
    autopilot_stop_loss_percent: float = 2.5
    autopilot_small_win_percent: float = 1.5
    autopilot_take_profit_percent: float = 6.0
    minimum_order_notional: float = 1.0
    allow_demo_live_entries: bool = False
    # Options Level 1 foundation. ``options_enabled`` defaults to False so
    # the equity loop is not silently affected; flip via env once the
    # broker adapter and dashboard surface are wired. ``options_max_level``
    # is what Alpaca approved (today: 1 = covered call + cash-secured put
    # only). When Level 2 is granted, set to 2 to unlock long calls/puts.
    options_enabled: bool = False
    options_max_level: int = 1
    options_allowed_underlyings: str = DEFAULT_OPTIONS_UNDERLYINGS
    options_min_open_interest: int = 500
    options_max_bid_ask_spread_percent: float = 0.05
    options_target_dte_min: int = 30
    options_target_dte_max: int = 45
    # Premium received divided by collateral encumbered. 0.005 = 0.5%.
    # Filters out CC/CSP setups whose yield doesn't justify the capital
    # tied up.
    options_min_premium_to_collateral_ratio: float = 0.005
    options_max_open_contracts: int = 2

    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper: bool = True
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-7"
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


def configured_options_underlyings() -> list[str]:
    """Return the uppercase universe approved for options trading."""

    return [
        symbol.strip().upper()
        for symbol in settings.options_allowed_underlyings.split(",")
        if symbol.strip()
    ]
