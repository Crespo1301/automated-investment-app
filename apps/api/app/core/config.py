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

DEFAULT_HIGH_VOL_SYMBOLS = (
    "ARKK,ARKW,ARKG,XBI,KRE,COIN,HOOD,ROKU,NET,DDOG,CRWD,PANW,ZS,TWLO,"
    "OKTA,MDB,U,DOCU,SOFI,ENPH,FSLR,RBLX,PINS,SNAP,RIVN,LCID,NIO,LI,XPEV,"
    "AAL,UAL,DAL,BABA,JD,PDD,MELI,SE,NU,GME,SOUN,BBAI,CVNA,AFRM,UPST,"
    "DKNG,RIOT,MARA,MSTR,IONQ,APP,TTD,PLTR,SMCI,ARM"
)


class Settings(BaseSettings):
    """Centralized runtime settings.

    The scaffold keeps this minimal on purpose so we can add broker, AI,
    database, and queue credentials incrementally with a single source of truth.
    """

    environment: str = "development"
    app_name: str = "Automated Investment API"
    operator_api_token: str | None = None
    base_currency: str = "USD"
    trading_mode: str = "paper"
    allowed_symbols: str = DEFAULT_ALLOWED_SYMBOLS
    max_symbols_per_cycle: int = 90
    # --- Live intraday mover scanner (offense lane, added 2026-06-09) ---
    # Feeds Alpaca's top gainers into the SAME scan -> score -> risk-gate
    # pipeline each cycle so the momentum lane can catch breakouts the static
    # universe would miss. Every existing gate still applies (spread, reserve,
    # min-notional, local_fallback_min_score, kill-switch). Flip
    # ``mover_scanner_enabled`` off for an instant kill.
    mover_scanner_enabled: bool = True
    mover_scanner_top: int = 50            # gainers to pull from Alpaca
    mover_scanner_max_symbols: int = 12    # cap injected into each cycle window
    mover_scanner_min_price: float = 5.0   # skip sub-$5 penny pumps
    mover_scanner_min_change_percent: float = 3.0   # must actually be running
    mover_scanner_max_change_percent: float = 25.0  # skip M&A/halt gaps
    # Rotation cooldown (2026-06-09): after a position is SOLD (stop, take-profit,
    # or manual rotation), block the autopilot from re-buying that same symbol for
    # this many minutes. Stops the dilution loop where freeing a weak name's slot
    # just gets refilled with the same drift name before a real mover can take it.
    reentry_cooldown_minutes_after_sell: int = 90
    # Momentum gate (2026-06-09): the autopilot must not open MECHANICAL
    # positions in flat, drifting names (they just bleed and crowd out movers).
    # An entry candidate's underlying intraday move (vs previous close) must be
    # at least this magnitude. Real movers (+3-25%) clear it; ~0% drift names
    # (NKE/T/CMCSA) are blocked, so freed slots/cash wait for offense. Founded
    # buy-market trades use a separate path and are NOT gated by this.
    min_entry_move_percent: float = 2.0
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
    cash_reserve_percent_of_portfolio: float = 0.30
    max_day_trades_5_business_days: int = 3
    # Trust Alpaca's ``account.daytrade_count`` as the source of truth (v2.0).
    # The local order-derived scan proved to be the stale source — it kept
    # counting day trades that had already aged out of the rolling window,
    # falsely blocking legitimate sells (observed 2026-06-04: local scan said
    # 2/3 while Alpaca reported 0/3). The PDT rule was also eliminated effective
    # 2026-06-04, so the broker count is both authoritative and effectively
    # unconstraining. Set False only to fall back to the local scan.
    pdt_use_broker_daytrade_count: bool = True
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
    # Per-trade sizing for the high-upside hunter lane, expressed as a
    # fraction of portfolio value. Intentionally smaller than the steady
    # ``position_size_percent`` so a losing hunter trade is a smaller
    # drawdown. Note the sizing helper enforces a $1 floor (Alpaca's
    # fractional minimum), so at very small portfolios both lanes
    # converge near $1 and the percent gap only really expresses itself
    # once the account is large enough to make the percentages dollar-
    # different. Example: at $10 portfolio steady sizes at $2.50 and
    # hunter at $1.50; at $100 steady is $25 and hunter is $15.
    # Env override: ``INVESTMENT_APP_HIGH_UPSIDE_POSITION_SIZE_PERCENT``.
    high_upside_position_size_percent: float = 0.15
    ai_min_score: float = 0.55
    # Cap on the deterministic local fallback score. Lowered from 0.88 to
    # 0.80 while Claude/OpenAI are unfunded: the local scorer is the
    # production scorer, and it should never claim model-grade conviction.
    # Env override: ``INVESTMENT_APP_FALLBACK_SCORE_CAP``.
    fallback_score_cap: float = 0.80
    # Minimum AI score the risk gate accepts when score_provenance is
    # "local" (i.e., the deterministic fallback produced the score).
    # Stricter than ``ai_min_score`` so weakly-validated local reads don't
    # squeak through under the global 0.55 floor while a real model is
    # offline. Env override: ``INVESTMENT_APP_LOCAL_FALLBACK_MIN_SCORE``.
    # Raised 0.65 -> 0.70 (2026-06-09): the lower bar let the bot dribble cash
    # into low-conviction drift names (XLP/NEE/KO/AAL) that just bled, crowding
    # out slots/cash for real movers. A higher floor admits only stronger
    # setups; genuine momentum movers clear it easily.
    local_fallback_min_score: float = 0.70
    # Multiplicative haircut applied to the deterministic fallback's blended
    # score when the broader market regime is risk-off or intraday volatility
    # is extreme. The market-context component alone only moved the blended
    # score ~0.01 - not enough to stand the bot down in hostile tape. These
    # dampeners are decisive and tunable: a 0.72 candidate * 0.82 = 0.59,
    # which falls under local_fallback_min_score and is rejected, while a
    # genuinely exceptional setup near the 0.80 cap can still clear. Env
    # overrides: ``INVESTMENT_APP_RISK_OFF_SCORE_MULTIPLIER`` /
    # ``INVESTMENT_APP_EXTREME_VOLATILITY_SCORE_MULTIPLIER``.
    risk_off_score_multiplier: float = 0.82
    extreme_volatility_score_multiplier: float = 0.90
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
    high_vol_stop_loss_percent: float = 7.0
    high_vol_symbols: str = DEFAULT_HIGH_VOL_SYMBOLS
    high_vol_position_size_multiplier: float = 0.5
    high_vol_min_pdt_slots_for_entry: int = 2
    # Entry-notional haircut when the candidate's broader-market regime is
    # risk-off or its volatility regime is extreme. Stacks multiplicatively
    # with ``high_vol_position_size_multiplier``. Both clamp to the $1
    # fractional minimum, so at very small NAV (entries already ~$1) this is
    # a no-op and the scorer's regime dampener carries the defense; it bites
    # once the account is large enough for sizing to matter. Env overrides:
    # ``INVESTMENT_APP_RISK_OFF_POSITION_SIZE_MULTIPLIER`` /
    # ``INVESTMENT_APP_EXTREME_VOL_POSITION_SIZE_MULTIPLIER``.
    risk_off_position_size_multiplier: float = 0.5
    extreme_vol_position_size_multiplier: float = 0.6
    pdt_capped_swing_entry_strategy_ids: str = "opening_range_breakout_v1"
    pdt_capped_swing_min_score: float = 0.78
    pdt_capped_swing_max_spread_bps: float = 40.0
    pdt_capped_swing_position_size_multiplier: float = 0.5
    small_win_min_pdt_slots_to_exit: int = 2
    small_win_min_net_profit_dollars: float = 0.10
    # At low NAV (<= low_portfolio_threshold) spread + fees swallow tiny
    # same-day exits. Raise the bar so a PDT slot is only spent when the
    # net profit estimate clears a more meaningful floor. Env override:
    # ``INVESTMENT_APP_LOW_NAV_SMALL_WIN_MIN_NET_PROFIT_DOLLARS``.
    low_nav_small_win_min_net_profit_dollars: float = 0.18
    low_portfolio_threshold: float = 50.0
    low_portfolio_small_win_percent: float = 2.5
    small_win_min_holding_minutes: int = 1440
    # Intended hard cap on concurrent open positions while the account is
    # under ``low_portfolio_threshold``. NOTE (2026-05-18): the risk-gate
    # enforcement for this setting was removed in commit 069a9ba
    # (2026-05-14); nothing reads this value today, so it is currently
    # INERT. Fragmentation is now bounded only by ``max_open_positions``.
    # Retained as a record of intent — re-add enforcement in
    # ``risk_engine.py`` to make this live again.
    low_nav_max_open_positions: int = 4
    # Positions at or below this market value, held past the configured
    # min holding window, are surfaced as morning-defragmentation
    # candidates. Read-only; the operator decides whether to liquidate.
    defragmentation_max_market_value_dollars: float = 3.0
    # Stale-laggard branch: positions ABOVE the dust floor but held
    # >= ``defragmentation_loss_min_age_minutes`` AND showing an
    # unrealized loss of at least ``defragmentation_loss_min_percent``
    # are ALSO surfaced for defrag. Catches names like T at -1.71%
    # MV $3.46 that drift below the dollar floor.
    defragmentation_loss_min_percent: float = 1.0
    defragmentation_loss_min_age_minutes: int = 2880  # 48h
    minimum_order_notional: float = 1.0
    allow_demo_live_entries: bool = False
    # When the rolling five-business-day day-trade count is at or above the
    # PDT limit, any new same-day intraday entry is "trapped": if its stop
    # fires before midnight ET it cannot be sold without breaching PDT. The
    # May 12 live test logged this exact failure mode (313 IONQ stop-loss
    # exits blocked). Block new entries unless the strategy is explicitly
    # tagged as overnight/swing-safe via ``swing_safe_strategy_ids``.
    block_entries_when_pdt_maxed: bool = True
    swing_safe_strategy_ids: str = ""
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


def configured_swing_safe_strategies() -> set[str]:
    """Strategy IDs whose entries are allowed when PDT is at the cap.

    Empty by default: until a strategy is explicitly tagged as overnight or
    swing-safe, we treat every candidate as same-day risk and block new
    entries once the rolling PDT count reaches the limit.
    """

    return {
        sid.strip()
        for sid in settings.swing_safe_strategy_ids.split(",")
        if sid.strip()
    }


def configured_pdt_capped_swing_strategies() -> set[str]:
    """Strategy IDs that may convert to reduced-size swing entries at PDT cap."""

    return {
        sid.strip()
        for sid in settings.pdt_capped_swing_entry_strategy_ids.split(",")
        if sid.strip()
    }


def configured_high_vol_symbols() -> set[str]:
    """Return symbols treated as high-volatility for PDT and exit posture."""

    return {
        symbol.strip().upper()
        for symbol in settings.high_vol_symbols.split(",")
        if symbol.strip()
    }


def configured_options_underlyings() -> list[str]:
    """Return the uppercase universe approved for options trading."""

    return [
        symbol.strip().upper()
        for symbol in settings.options_allowed_underlyings.split(",")
        if symbol.strip()
    ]
