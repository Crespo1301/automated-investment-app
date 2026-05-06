# Strategy: Micro Breakout V1

## Purpose

`micro_breakout_v1` is the first starter strategy for a small account. It is deliberately simple and high-variance, but bounded by strict risk limits.

## Current Symbol Universe

- `SPY`
- `QQQ`
- `NVDA`
- `TSLA`
- `AAPL`

## Candidate Criteria

The strategy emits a buy candidate only when:

- the symbol is in the allowed universe
- the event is a normalized bar
- previous close is present
- current price is at least `0.4%` above previous close
- observed volume is at least `100,000`

## Risk Treatment

The strategy only proposes a trade. It does not approve the trade.

Risk engine checks still decide whether a broker-facing execution intent is created.

Current hard limits:

- proposed notional cannot exceed `$2`
- only one open position is allowed
- daily live trade limit is `3`
- daily loss pause is `$2`
- live trading is disabled by default

## AI Treatment

OpenAI scoring is advisory. It may lower confidence or add concerns, but it cannot:

- increase position size
- override symbol limits
- bypass live-trading locks
- create broker orders directly

