# Signal logic (core)

## Pipeline

1. **SPY regime** — broad market support  
2. **Required gates** — must all pass (no signal if any fail)  
3. **6 confluence pillars** — need **4 of 6**  
4. **Score + grade** — A / B / C  
5. **Trade plan** — from **limit entry** (pullback when applicable), min 1.2:1 R:R  

## Required gates (hard)

| Gate | Rule |
|------|------|
| Weekly trend | Weekly close above 10-week MA, 4-week base intact |
| Relative strength | Stock 5-day return ≥ SPY 5-day return + **0.5%** |
| Extension | Not more than **15%** above 50-day MA |
| Divergence | No bearish RSI or MACD divergence at highs |
| Liquidity | 20-day avg volume ≥ 750k |

## Six pillars

Trend · Momentum · Structure · Volume · Not overextended · Breakout/demand  

## Entry logic

| Situation | Entry shown |
|-----------|-------------|
| Pullback setup or >4% above 50-MA | **Limit** between 20-MA and last price |
| Otherwise | Entry at last close |

Stop and targets are calculated from the **limit entry**, not last close.

## Divergence (reject)

- **RSI:** price near 14-day high but RSI falling and below prior RSI peak  
- **MACD:** price near high but histogram fading over recent bars  

## Tuning (not hard-coded) + Modes

All core gates, pillar thresholds, score bonuses/penalties, trade plan (ATR mult, R multiples, risk caps), and grade levels live in `SignalSettings`.

### High-level Modes (recommended)
Use `--mode` (CLI) or the **Strategy Mode** dropdown in the UI:

- `default` — Balanced relaxed (current sensible defaults)
- `conservative` — Strict quality filters, higher min confluence/score, tighter risk
- `swing` — Pullback-friendly, allows deeper retracements & extensions, favors structure
- `aggressive` — Looser gates for more signals, early momentum, wider stops
- `breakout` — Biased toward volume surges + stocks near 52w highs

Modes set a full profile (including trade plan and scoring weights). After selecting a mode you can still fine-tune individual parameters (this switches the UI to "Custom").

### Other tuning methods
- `-c config.yaml` with top-level `mode: aggressive` + optional `strategy:` overrides
- `--preset breakout` or `relaxed-long` (some presets ship with their own strategy overrides)
- Direct `settings=...` when calling the Python API

Example config.yaml:
```yaml
mode: swing
strategy:
  min_daily_change_pct: -4.0
  max_rsi: 82
```

See `src/us_stock_scanner/config.py:get_mode_settings` for the exact values per mode, and `docs/STRATEGY_REVIEW.md` for the original rationale behind the parameters.

Example in config.yaml:
```yaml
strategy:
  min_daily_change_pct: -3.0
  max_rsi: 80
  min_confluence: 4
  # ... see SignalSettings for full list (min_rvol_for_volume, bonuses, atr_stop_multiplier, etc.)
```

The expert screener path (`filters` / old presets) remains separate for raw screening.

See `docs/STRATEGY_REVIEW.md` for rationale and the full list of tunables.