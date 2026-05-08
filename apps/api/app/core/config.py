"""Application settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_ALLOWED_SYMBOLS = (
    "SPY,QQQ,DIA,IWM,VTI,VOO,SCHD,XLK,XLF,XLV,XLI,XLE,XLP,XLY,SMH,SOXX,"
    "ARKK,ARKW,ARKG,IBB,XBI,KRE,TLT,HYG,LQD,GLD,SLV,USO,"
    "NVDA,AAPL,MSFT,AMZN,GOOGL,GOOG,META,TSLA,AMD,AVGO,ORCL,CRM,ADBE,NFLX,"
    "INTC,QCOM,AMAT,LRCX,KLAC,ASML,MU,TSM,ARM,SMCI,DELL,IBM,NOW,SNOW,PLTR,"
    "SHOP,UBER,ABNB,DASH,COIN,HOOD,SQ,PYPL,ROKU,NET,DDOG,CRWD,PANW,ZS,"
    "JPM,BAC,WFC,C,GS,MS,V,MA,AXP,BLK,SCHW,COF,SOFI,"
    "UNH,LLY,NVO,MRK,ABBV,JNJ,PFE,AMGN,GILD,REGN,ISRG,TMO,ABT,MDT,"
    "XOM,CVX,COP,SLB,OXY,ENPH,FSLR,NEE,"
    "COST,WMT,TGT,HD,LOW,MCD,SBUX,NKE,LULU,PG,KO,PEP,CL,EL,"
    "CAT,DE,GE,BA,LMT,NOC,RTX,HON,UPS,FDX,URI,ETN,EMR,"
    "DIS,CMCSA,T,VZ,TMUS,SPOT,RBLX,PINS,SNAP,"
    "F,GM,RIVN,LCID,NIO,LI,XPEV,"
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
    max_symbols_per_cycle: int = 80
    position_size_percent: float = 0.25
    max_open_positions: int = 6
    max_day_trades_5_business_days: int = 3
    max_daily_loss: float = 2.0
    strategy_breakout_threshold: float = 0.0025
    strategy_min_volume: float = 25_000
    strategy_stop_loss_percent: float = 0.025
    high_upside_breakout_threshold: float = 0.012
    high_upside_min_recent_volume_ratio: float = 3.0
    high_upside_stop_loss_percent: float = 0.04
    high_upside_take_profit_percent: float = 0.12
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
