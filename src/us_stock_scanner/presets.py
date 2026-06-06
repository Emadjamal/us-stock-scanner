"""Built-in scan presets — no YAML or long flags required."""

from __future__ import annotations

from dataclasses import dataclass

from us_stock_scanner.config import SignalSettings
from us_stock_scanner.filters import ScanCriteria


@dataclass(frozen=True)
class Preset:
    key: str
    title: str
    description: str
    criteria: ScanCriteria
    universe: str = "sp500"
    period: str = "3mo"
    limit: int | None = None
    # Optional strategy settings: when used in main (non-expert) scans, overrides
    # the tunable gates/pillars/scores for the primary long engine. Unifies tuning.
    strategy: SignalSettings | None = None


def _p(
    key: str,
    title: str,
    description: str,
    criteria: ScanCriteria,
    *,
    universe: str = "sp500",
    period: str = "3mo",
    limit: int | None = None,
    strategy: SignalSettings | None = None,
) -> Preset:
    return Preset(key, title, description, criteria, universe, period, limit, strategy)


PRESETS: dict[str, Preset] = {
    "movers": _p(
        "movers",
        "Top movers",
        "Stocks up at least 2% today with decent liquidity.",
        ScanCriteria(min_price=5, min_change_pct=2.0, min_avg_volume_20d=500_000),
    ),
    # Example of a main-strategy focused preset (no expert criteria override needed)
    "relaxed-long": _p(
        "relaxed-long",
        "Relaxed long setups",
        "Default long engine but further relaxed for more signals / pullback days (use with main scans).",
        ScanCriteria(min_price=5, min_avg_volume_20d=400_000),  # loose for expert if used
        strategy=SignalSettings(
            min_daily_change_pct=-3.5,
            max_rsi=80.0,
            min_rs_vs_spy=0.3,
            min_confluence=3,
            min_score_default=48,
        ),
    ),
    "gainers": _p(
        "gainers",
        "Top gainers",
        "Same as movers — biggest daily gainers.",
        ScanCriteria(min_price=5, min_change_pct=2.0, min_avg_volume_20d=500_000),
    ),
    "losers": _p(
        "losers",
        "Top losers",
        "Stocks down at least 2% today.",
        ScanCriteria(min_price=5, max_change_pct=-2.0, min_avg_volume_20d=500_000),
    ),
    "volume": _p(
        "volume",
        "Unusual volume",
        "Today’s volume at least 2× the 20-day average.",
        ScanCriteria(min_price=5, min_rvol=2.0, min_avg_volume_20d=300_000),
        period="6mo",
    ),
    "breakout": _p(
        "breakout",
        "Breakout",
        "High volume, big move vs ATR, near 52-week highs, strong trend. (Expert screener + main strategy tuned for momentum leaders)",
        ScanCriteria(
            min_price=10,
            min_avg_volume_20d=1_000_000,
            min_rvol=1.5,
            min_atr_multiple=1.2,
            min_pct_from_high=-3,
            min_adx=25,
        ),
        period="1y",
        strategy=SignalSettings(
            # Relax for strong breakouts on big days
            min_daily_change_pct=-1.0,
            max_rsi=82.0,
            min_rvol_for_volume=1.3,
            bonus_near_high=14,  # slight tweak
        ),
    ),
    "squeeze": _p(
        "squeeze",
        "Bollinger squeeze",
        "Tight Bollinger bands — price coiling before a possible move.",
        ScanCriteria(
            min_price=5,
            min_avg_volume_20d=500_000,
            max_bb_bandwidth_pct=5,
            min_adx=20,
        ),
        period="6mo",
    ),
    "gap-up": _p(
        "gap-up",
        "Gap up",
        "Opened at least 2% above yesterday’s close.",
        ScanCriteria(
            min_price=5,
            min_gap_pct=2.0,
            gap_direction="up",
            min_avg_volume_20d=500_000,
        ),
        period="1mo",
    ),
    "gap-down": _p(
        "gap-down",
        "Gap down",
        "Opened at least 2% below yesterday’s close.",
        ScanCriteria(
            min_price=5,
            min_gap_pct=2.0,
            gap_direction="down",
            min_avg_volume_20d=500_000,
        ),
        period="1mo",
    ),
    "macd": _p(
        "macd",
        "MACD bullish",
        "MACD crossed above signal today with positive histogram.",
        ScanCriteria(
            min_price=10,
            min_avg_volume_20d=1_000_000,
            macd_crossover="bullish",
            min_macd_hist=0,
        ),
        period="6mo",
    ),
    "golden": _p(
        "golden",
        "Golden cross",
        "50-day SMA crossed above 200-day SMA today (slow scan).",
        ScanCriteria(
            min_price=5,
            min_avg_volume_20d=500_000,
            ma_fast=50,
            ma_slow=200,
            ma_crossover="golden",
        ),
        period="1y",
    ),
    "highs": _p(
        "highs",
        "Near 52-week high",
        "Within 3% of the rolling 52-week high.",
        ScanCriteria(
            min_price=10,
            min_avg_volume_20d=500_000,
            min_pct_from_high=-3,
        ),
        period="1y",
    ),
    "oversold": _p(
        "oversold",
        "Oversold (RSI)",
        "RSI below 30 — may be oversold.",
        ScanCriteria(min_price=5, max_rsi=30, min_avg_volume_20d=300_000),
        period="6mo",
    ),
    "overbought": _p(
        "overbought",
        "Overbought (RSI)",
        "RSI above 70 — may be overbought.",
        ScanCriteria(min_price=5, min_rsi=70, min_avg_volume_20d=300_000),
        period="6mo",
    ),
}


def list_presets() -> list[Preset]:
    return [PRESETS[k] for k in sorted(PRESETS)]


def get_preset(name: str) -> Preset:
    key = name.strip().lower().replace("_", "-")
    aliases = {
        "gainer": "gainers",
        "loser": "losers",
        "gaps": "gap-up",
        "gap": "gap-up",
        "vol": "volume",
        "quick": "movers",
    }
    key = aliases.get(key, key)
    if key not in PRESETS:
        keys = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown preset {name!r}. Choose from: {keys}")
    return PRESETS[key]