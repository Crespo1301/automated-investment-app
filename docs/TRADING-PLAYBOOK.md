# TRADING PLAYBOOK — read this first, every session

> **Single source of truth for how this account is traded.** If you are a fresh Claude
> session, read this top to bottom and resume — the operator should NOT have to re-explain
> any of it. Last updated 2026-06-09.

---

## 1. The goal

Grow a small real-money Alpaca account (**LIVE mode**, ~$55 NAV as of 2026-06-09) as fast as
responsible risk allows. The edge we are pressing: **huge percentage moves happen in the
market every day — our job is to catch the right ones early, time the entry and exit, and
rotate to the next one.** This is momentum/mover trading, NOT buy-and-hold.

## 2. The book is two sleeves

| Sleeve | Target | Purpose | Holds |
|---|---|---|---|
| 🛡️ **Safe floor** | ~35% | Ballast so a bad trade can't sink the account | `VOO` + cash |
| 🚀 **Bold mover sleeve** | ~65% | Aggressive daily-mover momentum trades | high-conviction movers, 2–3 names |

Risk appetite chosen by the operator (2026-06-09): **Aggressive concentration** — sell slow
defensives (PFE/WMT/XLV) to fund the bold sleeve; keep only a thin VOO + cash floor.

## 3. The bold sleeve — daily-mover momentum rules

- **Hunt liquid movers with a catalyst.** Price > $5, real volume, a reason it's moving
  (earnings, guidance, sector rotation, breakout, news). Each Claude loop pulls today's
  gainers + breaking catalysts.
- **Skip the traps:** done M&A gap-ups (frozen at deal price — unbuyable for upside, e.g.
  NUVL +39% on 6/9) and sub-$5 penny pumps (CCTG/PAVS-type +600% garbage).
- **Demand a defined stop before entering** — never "it's up today" alone.
- **Timing the exit is half the edge:** autopilot 30s stops lock the downside; swing bands
  scale OUT into strength on the upside. Keep band symbols synced to whatever we hold.
- **Rotate, don't pile:** 8-position fragmentation cap. To add a higher-conviction mover,
  sell the weakest/slowest holding to fund it.
- **Macro gate:** do NOT deploy aggressively INTO a binary print (CPI/FOMC/jobs). Trade
  around it; go aggressive once it clears. (Next: CPI 2026-06-10 8:30 ET — hot consensus
  4.2% headline, zero Fed cuts priced → stay defensive into it, fire on a cool surprise.)

## 4. The three always-on loops

1. **Autopilot — every 30s** (`apps/api` worker `--autopilot-loop`). Mechanical safety floor:
   stop-losses, take-profit/exit signals, mechanical entries on a **fixed ~200-name liquid
   universe** (`apps/api/app/core/config.py` → `DEFAULT_ALLOWED_SYMBOLS`, incl. high-vol movers
   ARM/SMCI/PLTR/COIN/RIOT/etc.), risk gates, kill-switch. Heartbeat: `apps/api/.runtime/autopilot-state.json`.
2. **Cron swing bands — every 3 min** (`crontab` → `scripts/swing_band.py`, log
   `scripts/swing_band_cron.log`, state `scripts/swing_band_state.json`). Deterministic
   per-symbol scale-out/scale-in on the held book. Durable, self-gates to market hours.
3. **Claude — every ~15 min** (`/loop`, cron prompt encodes the protocol below). The ALPHA
   layer: live mover hunt + founded entries/exits the bots can't reason about. **Claude's
   research-driven calls OVERRIDE the bots** (Claude has live info they don't). Act
   decisively, no confirm-menu; founded trades go through `buy-market` / `sell-market`
   (still honor all risk gates).

### Division of labor for "catching daily movers early"
- **Dynamic layer = the 15-min Claude loop.** It pulls the live daily-gainers feed the bots
  cannot see. This is the designed home for catching off-universe movers.
- **Mechanical layer = autopilot.** Scans its fixed universe **plus a live intraday-mover
  feed** (shipped 2026-06-09). Every cycle, `AlpacaBroker.list_intraday_movers` (Alpaca
  `ScreenerClient`) pulls top gainers, filters to liquid momentum candidates (price ≥ $5,
  +3% to +25% so it skips penny pumps and M&A/halt gaps), and `local_worker._get_cycle_events`
  injects them into the same scan→score→risk-gate pipeline. They only get bought if they ALSO
  clear the score threshold + spread/reserve/min-notional/kill-switch. Tunable via
  `mover_scanner_*` settings; flip `mover_scanner_enabled=False` for an instant kill.
- **Dilution control:** `local_fallback_min_score` raised 0.65→0.70 (2026-06-09) so the bot
  stops dribbling cash into low-conviction drift names (XLP/NEE/KO/AAL) — freeing slots/cash
  for real movers, which score higher and still clear the bar.
- **Same-day exits work** (PDT exit-guard bug fixed 2026-06-09): autopilot stops now cut
  same-day losers instantly; no more `exit_signal_locked` deadlock. See [[pdt-rule-elimination]].

## 5. The 15-min loop protocol (what each tick does)

The recurring `/loop` cron prompt enforces this every 15 min:
1. **Health:** autopilot heartbeat fresh? kill switch OFF? pull live book+cash
   (`/api/broker/reconciliation`); check latest `swing_band_cron.log` line.
2. **Mover hunt:** scan today's liquid big movers + catalysts (stockanalysis.com/markets/gainers,
   premarket movers, sector news) for timely entries into moves still running.
3. **Decide:** apply the bold-sleeve rules in §3.
4. **Act** decisively; let autopilot stops + bands manage exits; sync band symbols to held movers.
5. Report the tick's call + book in plain language; if no clean setup, HOLD and say why.

## 6. Startup checklist (fresh session)

```bash
# 1. API up?  (port 8000)
curl -s http://127.0.0.1:8000/ ; echo
# 2. Autopilot heartbeat fresh + kill switch off?
curl -s http://127.0.0.1:8000/api/autopilot/status
curl -s http://127.0.0.1:8000/api/safety/status
# 3. Band cron installed?
crontab -l | grep swing_band
# 4. Web dashboard up?  (NOTE: moved off :3000 → :3007)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3007
# 5. Live book
curl -s http://127.0.0.1:8000/api/broker/reconciliation
```
If anything is down, (re)launch: API → autopilot loop → web (`npm run dev:web`, serves :3007).
If kill switch tripped overnight (transient DNS), clear + re-arm. Then start `/loop 15m`.

## 7. Key facts & gotchas

- **Web dashboard runs on :3007** (not 3000 — operator's other apps squat 3000). Set durably
  in `apps/web/package.json` (`next dev -p 3007`). API↔web link via `INVESTMENT_WEB_API_BASE_URL`.
- **PDT cap eliminated** — same-day enter/exit is allowed (use it for movers).
- `/api/broker/alpaca/account` 500 is **benign** — it's the *paper* endpoint refusing in live mode.
- The dashboard `/api/dashboard/snapshot` shows **scaffold/demo numbers** — the REAL book is
  `/api/broker/reconciliation` (live Alpaca).
- Swing-band state may list exited symbols — **inert** (the script skips names not held), so no
  re-buy risk, but sync it when convenient.
- Kill switch = the pause control. Disabling autopilot EXITS the loop process; re-enabling does
  NOT restart it — verify heartbeat freshness, don't disable to "take over."

## 8. Related docs & memory

- `docs/v2.0-operating-model.md` — fuller v2 design context.
- `CLAUDE.md` — repo-level instructions (points here).
- Auto-memory: `bold-sleeve-mover-strategy`, `v2-operating-model`, `swing-band-tool`,
  `session-*-posture`, `primary-goal-grow-value`, `pdt-rule-elimination`.
