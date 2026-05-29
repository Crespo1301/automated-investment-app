# v1 Lane Edge Analysis

Generated from 15 order-event files (132 distinct filled orders: 70 buys, 62 sells).

FIFO round-trip matching by `symbol`. Lane attribution comes from the BUY's `client_order_id` prefix.

Open-lot unrealized P&L sourced from portfolio snapshot at `2026-05-28T15:34:39.079358Z`.

## Realized round-trips by lane

| Lane | Trips | Notional | Realized P&L | P&L % | Win rate | Avg win | Avg loss | Biggest win | Biggest loss | Avg hold |
|------|------:|---------:|-------------:|------:|---------:|--------:|---------:|------------:|-------------:|---------:|
| `vwap_reclaim_v1` | 8 | $29.6400 | $0.3585 | +1.21% | 62.5% | $0.1025 | $-0.0513 | $0.2500 | $-0.0715 | 3.3d |
| `opening_range_breakout_v1` | 29 | $78.3500 | $0.3007 | +0.38% | 55.2% | $0.0683 | $-0.0609 | $0.1688 | $-0.1609 | 1.9d |
| `micro_breakout_v1` | 11 | $33.5900 | $0.2892 | +0.86% | 54.5% | $0.1110 | $-0.0754 | $0.3819 | $-0.1912 | 1.6d |
| `pullback_continuation_v1` | 8 | $23.2000 | $0.2770 | +1.19% | 100.0% | $0.0346 | $0.0000 | $0.1005 | $0.0023 | 2.6d |
| `relative_volume_spike_v1` | 5 | $15.0200 | $0.0222 | +0.15% | 40.0% | $0.0874 | $-0.0509 | $0.1096 | $-0.1149 | 3.5d |
| `unknown` | 1 | $1.5759 | $0.0141 | +0.89% | 100.0% | $0.0141 | $0.0000 | $0.0141 | $0.0141 | 2.0d |
| `manual_buy` | 2 | $12.6000 | $-0.2973 | -2.36% | 0.0% | $0.0000 | $-0.1487 | $-0.0270 | $-0.2704 | 5.0d |
| **TOTAL** | **64** | **$193.9759** | **$0.9643** | **+0.50%** | — | — | — | — | — | — |

## Still-open lots (unrealized)

| Lane | Symbol | Open qty | Avg cost | Current px | Cost basis | Mkt value | Unrealized P&L | P&L % |
|------|--------|---------:|---------:|-----------:|-----------:|----------:|---------------:|------:|
| `unknown` | QQQ | 0.012254 | $728.2460 | $735.1200 | $8.9241 | $9.0084 | $0.0842 | +0.94% |
| `opening_range_breakout_v1` | PFE | 0.241892 | $25.8380 | $26.1700 | $6.2500 | $6.3303 | $0.0803 | +1.28% |
| `opening_range_breakout_v1` | SPY | 0.004142 | $746.0260 | $754.0550 | $3.0900 | $3.1233 | $0.0333 | +1.08% |
| `relative_volume_spike_v1` | VOO | 0.008312 | $692.9520 | $693.2850 | $5.7600 | $5.7628 | $0.0028 | +0.05% |
| `micro_breakout_v1` | RIVN | 0.099417 | $15.0880 | $15.0750 | $1.5000 | $1.4987 | $-0.0013 | -0.09% |
| `micro_breakout_v1` | F | 0.173829 | $16.5680 | $16.5400 | $2.8800 | $2.8751 | $-0.0049 | -0.17% |
| `vwap_reclaim_v1` | XLF | 0.119927 | $51.4480 | $51.1950 | $6.1700 | $6.1397 | $-0.0303 | -0.49% |
| `micro_breakout_v1` | NVDA | 0.027745 | $214.0960 | $212.9000 | $5.9400 | $5.9068 | $-0.0332 | -0.56% |
| **TOTAL** | — | — | — | — | **$40.5141** | **$40.6450** | **$0.1309** | **+0.32%** |

## Interpretation

**Earned edge (positive realized P&L):**
- `vwap_reclaim_v1`: $0.3585 across 8 round-trips (62% win-rate, avg hold 3.3d)
- `opening_range_breakout_v1`: $0.3007 across 29 round-trips (55% win-rate, avg hold 1.9d)
- `micro_breakout_v1`: $0.2892 across 11 round-trips (55% win-rate, avg hold 1.6d)
- `pullback_continuation_v1`: $0.2770 across 8 round-trips (100% win-rate, avg hold 2.6d)
- `relative_volume_spike_v1`: $0.0222 across 5 round-trips (40% win-rate, avg hold 3.5d)
- `unknown`: $0.0141 across 1 round-trips (100% win-rate, avg hold 2.0d)

**Break-even noise (|P&L| ≤ $0.01):**
- _None._

**Lost money (negative realized P&L):**
- `manual_buy`: $-0.2973 across 2 round-trips (0% win-rate, avg hold 5.0d)

_Notional values are tiny by design (this account is a $5-biweekly DCA live-paper scaffold), so dollar P&L should be read as edge signal, not income. Percent-on-notional is the more meaningful column for comparing lanes._
