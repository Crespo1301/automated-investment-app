---
name: morning-report
description: Combined daily home status check. Runs finance-check, mail-check, weather-check, calendar-check, gmail-check, and meal-check in sequence. Use when user says "morning check", "morning report", "home status", "what's going on today", or wants a start-of-day overview.
---

# Morning Report

Assemble the full daily home status by running each home skill in sequence.

## Prerequisites

- BECU MCP server must be running
- Heritage Bank NW MCP server must be running
- USPS MCP server must be running
- Google Workspace MCP server must be running

## Steps

Run each skill fully (all fetch steps + full output) before starting the next.

1. **`/finance-check`** — account balances and recent activity
2. **`/mail-check`** — USPS mail pieces and packages
3. **`/weather-check`** — 3-day NWS forecast for Brier, WA
4. **`/calendar-check`** — upcoming events for the next 7 days
5. **`/gmail-check`** — Gmail inbox grouped by theme
6. **`/meal-check`** — dinner plan for the next 7 days

After all skills complete, offer:

```
Would you like me to:
1. Show full transaction details for an account
2. Show mail piece images for recent mail
3. Get tracking details for a specific package
4. Show more detailed weather information
5. Open or summarize a specific email
6. Show full details for a calendar event
```

## Notes

- Run this at the start of the day for best results
- Each section can also be run independently as its own skill
