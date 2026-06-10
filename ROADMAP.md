# US Stock Scanner — Roadmap

**Last updated:** June 2026 (after journal display fix + scan diagnostics)

## Guiding Principles
- Make local and cloud (Streamlit + Turso) produce **identical, reproducible** results.
- Keep the engine fully tunable via "Modes" (no hard-coded magic).
- Good visual explanations for why a stock was picked.
- Persistence that survives deploys (Turso for everything).
- Useful both as a nice UI and as a practical daily tool (Telegram bot + monitoring).

## Completed (Major Milestones)
- Full tunable `SignalSettings` + unified engine (no more separate "expert" hard-coded path for main use)
- Custom Modes with full CRUD (UI + persistence, like watchlist)
- Configurable **Scan Period** + **Timeframe** + **Top Picks** slider (sidebar + per-mode)
- Real candlestick charts with EMAs, SMAs, golden cross, trade levels, volume
- Complete SQLite (local) + Turso/libsql (cloud) persistence for watchlist, journal, custom_modes, active_trades
- Secrets bridge for Streamlit Cloud
- Rich per-scan diagnostics (Effective params, Gates used, signals_found, rejection breakdown)
- Journal display bug fixed ("all fields none")

## Prioritized Remaining Work

### P0 — Local vs Cloud Parity (Current Active Pain Point)
- User still sees different pass rates (e.g. 132 vs 150 skipped on sp500 limit=150).
- **Status**: Rich diagnostics added and further improved:
  - `attempted` / `fetched` counts
  - `market_summary`
  - Dedicated "📋 Scan Diagnostics" expander with copyable block + top rejection reasons
- **Next actions**:
  - User to re-run identical scans on both sides (with latest code) and share the full diagnostics block from the expander.
  - Use the data to decide on targeted fixes (yfinance variance, weekly on marginal data, settings, etc.).

### P1 — Deployment & "Always Useful" Experience
- Make Streamlit Cloud + Turso feel reliable (after secrets bridge).
- Improve Telegram bot + Railway path (recommended for background monitoring).
- Better guidance for common issues (cold starts, yf rate limits, libsql package).
- Document exact "add Turso secrets after first deploy" flow (user requested this before).

### P2 — Active Trades & Monitoring
- On-demand monitor works (UI + bot).
- Make background / scheduled monitoring more robust and automatic (especially for the bot on hosting platforms).
- Improve recommendations and notifications when stops/targets are hit.

### P3 — CLI Parity with UI
- Main CLI (`python -m us_stock_scanner`) should support `--period`, `--timeframe`, `--top-picks`.
- Better support for listing/using custom modes from CLI.
- Keep the old expert preset path clearly separated or deprecate it.

### P4 — Polish & Documentation
- Update `docs/SIGNAL_LOGIC.md`, `STRATEGY_REVIEW.md`, and README examples to match current reality (modes, period/timeframe, visuals, Turso).
- Add more tests around storage, custom modes persistence, and period/timeframe effects.
- yfinance reliability / caching improvements (to reduce "no data" differences between environments).
- Minor UX: easier "reset to defaults", better warnings for non-1d scans, copyable full debug report.

### Nice-to-Haves / Future
- Caching layer for yfinance within a scan session. **(done)**
- More pattern detection visuals in the candlestick expander. **(done: HH markers, swing low, setup annotations)**
- True scheduled background jobs (without relying on hosting "always on").
- Performance improvements for full-index scans. **(done: module-level per-ticker+period+interval cache + chart now uses cached fetch)**
- Optional "paper trading" simulation mode.

## How to Work on This Roadmap
- Parity issues → run scans with the diagnostics visible and report the full block.
- New features → prefer adding them to the main tunable engine + Modes system.
- Persistence → everything must work through `storage.py` (Turso + local).
- Always keep local (pure SQLite, no TURSO vars) and cloud (with Turso) in mind.

---

**Current focus (as of this update):** Finish P0 (parity) using the new diagnostics, then stabilize deployment (P1).