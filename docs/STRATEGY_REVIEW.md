# Strategy Filters & Presets Review (2026-06)

**Date:** Current session review of main long-setup strategy and expert presets/filters.  
**Scope:** Primary engine (`signal_engine.py` + supporting), expert path (`filters.py`, `presets.py`, `config.py`, `scanner.py`), docs, usage in auto_pick/UI/CLI, live behavior via scans + journal.

## Executive Summary

The scanner has **two distinct screening systems**:

1. **Primary "Auto Long Trade Finder"** (default in UI + `python -m us_stock_scanner`, `scan.ps1`): Hard-coded rules in `analyze_symbol_v2` producing graded `TradeSignal`s with entry/stop/targets + journal integration. This is the core value ("one click best long trades").
2. **Expert / Preset Screener**: Flexible `ScanCriteria` (many indicators) + `evaluate_symbol`. Used only via `--expert` / presets / `--config` in CLI. Produces raw match tables, **no** trade plans, grades, or journal.

**Main strategy is selective**: In a live test (bullish SPY regime, first ~30 SP500 names) only 1 signal emerged. Common rejects: down day, weak 5d RS, bearish div, overbought RSI. Journal shows exclusively B-grades so far, several "not_filled".

**Needs improvement? Yes.** Several high-impact, low-risk tweaks to gates + better unification of the two paths would increase usability and signal quality without losing the "quality over quantity" philosophy.

## Primary Strategy Deep Dive (`signal_engine.py` + `timeframes.py` + `market_regime.py`)

### Alignment with Docs
`docs/SIGNAL_LOGIC.md` accurately describes:
- Weekly trend gate
- 5d RS >= +0.5% vs SPY
- Max 15% extension
- No bearish div (RSI/MACD)
- Liquidity 750k
- 6 pillars (need 4)
- Pullback-aware limit entry
- Score/grade + RR >=1.2 filter

Code matches the documented intent.

### Strengths
- **Multi-layer defense**: Hard gates → confluence (4/6) → score threshold (regime-adjusted) → RR min. Reduces junk.
- **Context aware**: Weekly structure + market regime + RS + divergences (better than most simple scanners).
- **Actionable output**: Real trade plan (limit entry, ATR/swing stop, 1.5R/2.5R targets) with human reasons.
- **Regime adjustment**: Lower bar (48) in strong markets, higher (58) in weak — smart.
- **Clean indicators**: Custom `bearish_*_divergence`, `relative_strength_vs`, `_higher_highs`, etc. No TA-Lib dep.
- Good safety: price >=5, avg vol, ATR>0 checks, RR validation.

### Key Issues & Observations (from code + live runs)

#### 1. Hard "No Long Bias on Down Day" Gate (change_pct < -0.5%)
```python
if change_pct < -0.5:
    return None
```
- **Impact**: Extremely high. Live scans frequently hit "Down X% today — no long bias" (NVDA -0.7, MSFT -4.2, PLTR -5.3, many in 30-name slice).
- Even strong multi-day setups with good weekly/RS get discarded if today is red (common in normal markets).
- Contradicts "pullback" setup_type which is explicitly supported in entry logic and classification.
- **Recommendation**: Soften to `change_pct < -2.5` or `-3`, or remove hard gate entirely. Let the Momentum pillar + scoring (controlled +1..6% bonus) + "Not overextended" penalize weak closes. Add as warning instead.

#### 2. RSI Hard Cap (>75) + Combo Gate
```python
if last_rsi > 75: return None
if change_pct > 8 and last_rsi > 68: return None
...
not_extended = last_rsi <= 68 and ...
```
- **Live example**: SMCI +7% (strong breakout candidate) → "RSI 83 — overbought". TQQQ also rejected at 79.
- Suppresses exactly the high-conviction momentum/breakout names the "Breakout / demand" pillar is meant to reward.
- 75 is conservative; many healthy leaders run with RSI 70-80 in strong trends.
- **Rec**: Raise hard cap to 78-80, or make conditional (allow if rvol>2.0 + near high + adx>25 + macd strong). Move the 68 into "not_extended" pillar only (no hard kill).

#### 3. Extension / Below MA Gates
- `extension_pct > 15.0` hard reject (good).
- `last < last_ma50 * 0.97` (below 50MA by 3%+ kills).
- These + not_extended (<=12%) are reasonable but overlap.
- Pullback setups can legitimately be >4% extended and still want limit-to-MA entry.

#### 4. Weekly Trend Gate (timeframes.weekly_trend_bullish)
```python
above_ma = last > last_wma  # 10-week SMA
higher_than_month = last >= four_weeks_ago * 0.99
```
- Strong filter (matches doc: "Weekly close above 10-week MA, 4-week base intact").
- **Risk**: In strong but choppy uptrends or after shallow corrections, many quality names sit below their 10w MA temporarily while daily structure is fine. This gate alone eliminates a lot before pillars even run.
- "4-week base" is very loose (only vs 4w ago, allows big drops then recover).
- **Rec**: Consider making configurable, or add a "relaxed weekly" mode, or use 20-week for longer-term trend + daily/weekly confluence. Or change to "price above 10w OR strong daily trend + sector RS".

#### 5. Relative Strength (only 5 days)
- `MIN_RS_VS_SPY = 0.5`
- Captures short-term outperformance well for momentum.
- **Weakness**: One bad day tanks 5d RS. Longer leadership (20d/60d) ignored.
- In live: many "Underperforming SPY" skips.
- **Rec**: Require 5d RS >=0.5 **OR** 20d RS >=1.0 (or similar). Weight longer in scoring.

#### 6. 6 Pillars & Confluence (MIN_CONFLUENCE=4)
Pillars (current):
- Trend (above 20/50 + ma20_slope>0)
- Momentum (hist>0 + rising or fresh bull cross)
- Structure (_higher_highs on last 20 bars — crude split-half max compare)
- Volume (rvol >= **1.15**)
- Not overextended (rsi<=68 + ext<=12 + bb<=92)
- Breakout/demand (near 52w high -3% **or** chg>=1% + rvol>=1.2)

**Issues**:
- Volume bar is low (1.15x). Expert presets use 1.5-2.0 for "unusual". In live AMAT example run, one pick had rvol~1.0.
- Structure detector is naive (no requirement for prior higher low, just recent max comparison).
- "Not overextended" + hard gates have redundancy.
- Pillars are not independent (trend + momentum + breakout highly correlated on good days).
- In practice (journal + limited scan): very hard to get 5+ confluence for "A" grade (72+ score). Mostly B's at 62-84.

**Recs**:
- Raise volume pillar to 1.25-1.3x baseline.
- Improve `_higher_highs` (require HH + HL or use argrelextrema style).
- Make pillar weights or min_rvol exposed (perhaps via a StrategyConfig later).
- Consider 5th pillar "Trend strength (ADX>=22)" as separate from Trend.

#### 7. Scoring & Grading
Raw points heavily favor certain pillars (+14 trend, +14 mom, +12 vol, +12 near-high, +10 controlled chg, +10 struct, +8 adx/rsi-sweet/rs-big).
- Confluence base: min(15, conf*3)
- Penalties: warnings*6 + weak market*6 + rsi>65*4 + ext>8*4
- Grade: A needs 5+ conf **and** >=72; B 4+ & >=62; else C if min met.
- Regime lowers the final min score bar in bull markets.

**Observations**:
- Heavily heuristic / tuned by eye. Easy to rack points.
- Journal (6 entries): all B, avg ~76. No As yet.
- "Worth watching" threshold (WATCH_MIN_SCORE=58) separate from pass bar.
- **Rec**: Add diminishing returns for correlated pillars. Or introduce a small "setup bonus" table. Expose score components in debug/verbose mode. Consider A only on very rare perfect storms.

#### 8. Market Regime (market_regime.py)
Simple:
- +1 above50, +1 above200, +1 green day, + "healthy RSI 40-65"
- bullish = score>=2 **and** above50
- Used for: penalty if not bullish, and min_score adjustment.

**Weak** for a "regime" filter:
- No breadth, no VIX, no leadership concentration (e.g. equal-weight vs cap), no put/call or credit spreads.
- On days with "SPY green + above MAs but only 5 names carrying the market", it still gives full credit.
- **Rec**: 
  - Add VIX context (if yf can get ^VIX): high VIX + rising = caution.
  - Simple internal breadth: when scanning universe, compute % of tickers above their 50ma as a secondary score (low cost if already fetching).
  - Or hardcode a few sector ETFs (XLK, XLV...) for risk-on confirmation.

#### 9. Trade Plan & Entry Logic (`trade_signal.py` + `_pullback_entry`)
```python
stop_atr = entry - (1.5 * atr_val)
stop_swing = recent_low * 0.998
...
t1 = entry + risk*1.5
t2 = entry + risk*2.5
rr_min = 1.2 else reject
risk cap 8%
```
- Solid ATR + structure stop.
- Limit entry prefers pullback toward 20MA when extended >4% or "pullback" setup.
- In journal: several "not_filled" on day 1 (limits above current? or strong continuation didn't pull back).

**Issues**:
- Fixed 1.5 ATR multiplier + 8% hard cap leads to 6-8% risk_pct on many names (see ACN/AMAT in log).
- Targets are always R-multiples; no "next resistance" or "prior high" logic.
- On high-vol names, 1.5ATR stop can be wide (good for noise but large $ risk).
- **Recs**:
  - Make ATR multiple for stop configurable (or vol-regime dependent: 1.0-2.0x).
  - For T2, take max(2.5R, distance to recent swing high) or use 2*ATR projected.
  - Suggest "risk $ per share" or % of account (needs user capital input in UI).
  - Improve fill model in outcomes: current walks bars assuming limit at entry price touched on low — reasonable.
  - Add "time stop" or "trailing" simulation option later.

#### 10. Other Code Issues
- Double evaluation in `auto_pick.run_scan`: `analyze_symbol_v2` called in skipped loop + again in `find_all_signals_v2`. (History is cached so cheap, but ugly.)
- `diagnose_rejection` re-implements a lot of the gate logic (dupe code — maintenance hazard). If you change a gate in analyze, update diagnose or it lies.
- Magic numbers everywhere (0.5, 1.15, 15, 75, 68, 0.97, 22, 1.2 RR, point values 14/12/10/8). Centralize in a `StrategyParams` dataclass or module constants with comments.
- No error handling around yf failures beyond skips.
- `analyze_symbol` (old wrapper) still exists delegating to v2.

## Expert Filters + Presets Review

### Structure
- `ScanCriteria` dataclass: ~30 tunable fields (price/vol/RSI bands, MACD/MA/gap/BB/52w/rvol/ATR/stoch/ADX + periods).
- `filters.evaluate_symbol`: applies all active checks (only if the *_uses_*() helper says the criterion is set), returns metrics dict or None.
- `scanner.run_scan`: fetch + evaluate + sort by "interesting" column (gap/rvol/atr/high/macd/bb or chg).
- `presets.py`: 15+ canned `Preset`s (movers/gainers/losers/volume/breakout/squeeze/gap-*/macd/golden/highs/oversold/overbought).
- YAML loader for custom.

Matches the example yamls exactly (breakout, gap, ma_cross, macd, squeeze, main example).

### Strengths
- Very flexible for power users ("build your own screener").
- Good indicator coverage (includes stoch, adx, atr multiple, bb squeeze/bandwidth/touch, pct from high).
- Presets have reasonable defaults + periods (e.g. breakout uses 1y + high vol + near high + adx25 + atr1.2 + rvol1.5).

### Weaknesses
- **Disconnected from primary value prop**: No TradeSignal, no grades, no entry/SL/T1/T2, no reasons, no auto journal. When you use `stock-scan breakout` you get a different experience.
- Low overlap with main strategy filters (main has weekly/RS/divergence/higher-highs/market regime that expert completely ignores).
- Some presets are contrary (losers, overbought, gap-down) — fine for screening but not "long trades".
- Golden cross etc. are rare and slow (1y data).
- Duplication: logic in presets.py + 6 separate .example.yaml files. Easy for them to drift.
- Not surfaced in Streamlit UI (sidebar hardcodes the 3 main modes).
- Output in expert CLI is just a pandas table of raw metrics (no rich formatting or "why" like main path).
- `sort_column` heuristic is ok but basic.

**Rec**: 
- Either fully integrate expert criteria as "overrides" or "alternative pillar modes" on top of the v2 engine (so you still get trade plans + journal).
- Or clearly brand expert as "raw technical screener" (different from "find best trades").
- Add a `strategy` or `mode` to main engine that tweaks the hard gates/pillars (e.g. "breakout", "pullback", "momentum").
- Generate the example yamls from the PRESETS dict or vice-versa to avoid drift.
- Expose 3-4 useful presets in the UI (e.g. via advanced sidebar).

## Cross-Cutting & Robustness

- **No tests**: Zero unit tests for core logic (gates, pillars, scoring, trade_levels, divergences, weekly). Hard to refactor safely or validate changes.
- **No backtesting**: Impossible to know historical win rate of the logged signals, false positive rate of gates, or whether params (4/6, 52/62/72, 1.15 rvol, 0.5 RS, etc.) are good out of sample. Journal + outcomes.py is a start for forward tracking but small sample (6 signals).
- **Data sources**: Wikipedia scrape for universes (current constituents only — good for live, bad for true historical). yfinance with auto_adjust is appropriate. Occasional missing bars → skipped.
- **Performance**: Re-downloads 1y daily for 150 names on every scan. Fine for interactive but could use `period="6mo"` default or caching for repeated runs.
- **Outcomes tracking**: Well done forward walk using H/L for hits. Captures "not_filled" correctly for limits. Good for learning (many not_filled suggests entry limits may need tuning or users should use market orders for strong setups).
- **UI/UX**: Main path produces nice cards. But frequent "no setups" or only 1-3 picks on typical days can feel disappointing.

## Prioritized Recommendations

### P0 / High Impact (do these first)
1. **Relax the daily change hard gate** (change_pct < -0.5). Proposal: >= -2.0 or remove + add "weak close" warning/penalty. This will dramatically increase signal frequency on normal trading days while still favoring positive momentum via pillars/scoring.
2. **Soften RSI overbought gate**. Raise to 80 or condition it. Allow strong breakouts (high rvol + near high + macd) even if RSI 76-82.
3. **Centralize magic numbers** into `signal_engine.py` (or new `params.py`): `HARD_MAX_RSI=78`, `MIN_RVOL_PILLAR=1.25`, `MIN_CONFLUENCE=4`, `RS_LOOKBACKS=(5,20)`, point bonuses as dict, etc. Add comments explaining rationale.
4. **De-dupe gate logic** between `analyze_symbol_v2` and `diagnose_rejection`. Extract a `_passes_hard_gates(...)` helper that both use (and that returns the failing reason when it fails).
5. **Document + expose strategy "flavors"** in UI/CLI (Standard, Breakout-friendly, Conservative) that adjust a few of the above thresholds.

### P1 / Medium
- Improve weekly filter or make it one of several options.
- Multi-horizon RS (5d + 20d).
- Better structure pillar.
- Enhance market regime (add simple breadth or VIX).
- Improve trade levels (configurable ATR mult, better T2, risk % suggestion).
- Unify or bridge expert presets into main engine so they still produce TradeSignals.
- Write tests for pure functions + a few golden-path + rejection cases (synthetic small DataFrames).
- Add a `--debug` or verbose that dumps all 6 pillar booleans + raw score components for a symbol.

### P2 / Polish & Future
- Backtest harness (simple vectorized or event loop over past periods) + metrics (winrate on T1, expectancy, max DD of signals).
- Earnings awareness (skip or warn if earnings within N days).
- Cache yf downloads (simple disk or in-mem with TTL).
- Optional sector RS or industry filter.
- Make scoring / pillar definitions data-driven (YAML or Strategy dataclass) for easier experimentation.
- Consider a "relaxed" mode for watchlist (lower bars) vs broad index scans.

## Suggested Next Steps
- Implement P0 items above (start with change gate + RSI + constants refactor).
- Run a forward test period (enable journal, update outcomes daily for 2-4 weeks) and review actual fill rates / win rates before/after tweaks.
- Add 5-10 pytest cases for the engine.
- Update SIGNAL_LOGIC.md + README with any param changes + rationale.
- Decide on long-term: keep two paths or converge on one extensible engine?

## Appendix: Live Behavior Notes (this session)
- Market regime: bullish on test days.
- Signal rate: low (~3% of names in slice).
- Grades: exclusively B in current journal.
- Frequent rejects: down day, RSI>75, weak 5d RS, bearish div.
- Picks that do appear: large caps with modest chg, decent but not crazy rvol (~1.0-1.7), RSI 63-73, B scores 64-84.
- Many limit entries not filled on first day (consistent with conservative pullback entry logic on trending days).

This review is based on static code inspection, matching to docs, preset/config files, live CLI/UI paths, journal data, and multiple real yfinance-backed scans/diagnostics.

---
*Review performed interactively with code reads, greps, and live execution in the project venv.*
