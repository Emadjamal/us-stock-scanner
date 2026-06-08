"""Score stocks and build trade plans (entry, targets, stop, reasons)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from us_stock_scanner.config import SignalSettings, default_signal_settings


@dataclass
class TradeSignal:
    symbol: str
    score: float
    strength: str
    entry: float
    stop_loss: float
    target1: float
    target2: float
    risk_pct: float
    reward1_pct: float
    reward2_pct: float
    reasons: list[str] = field(default_factory=list)
    change_pct: float = 0.0
    rsi: float = 0.0
    rvol: float = 0.0
    adx: float = 0.0
    grade: str = "C"
    setup_type: str = ""
    entry_market: float = 0.0  # last close
    rs_vs_spy: float = 0.0  # 5-day relative strength vs SPY (%)

    @property
    def risk_reward_t1(self) -> float:
        risk = self.entry - self.stop_loss
        if risk <= 0:
            return 0.0
        return (self.target1 - self.entry) / risk


def _trade_levels(
    entry: float, atr_val: float, recent_low: float, *, settings: SignalSettings | None = None
) -> tuple[float, float, float, float]:
    """Stop below entry; targets at R-multiples. Tunable via settings."""
    settings = settings or default_signal_settings()
    atr_mult = settings.atr_stop_multiplier
    t1_r = settings.target1_r_multiple
    t2_r = settings.target2_r_multiple
    min_risk_frac = settings.min_risk_fraction
    max_risk_frac = settings.max_risk_fraction

    stop_atr = entry - (atr_mult * atr_val)
    stop_swing = recent_low * 0.998
    stop = min(stop_atr, stop_swing)
    if stop >= entry:
        stop = entry - (atr_mult * atr_val)
    risk = entry - stop
    if risk < entry * min_risk_frac:
        stop = entry - max(atr_val, entry * 0.01)
        risk = entry - stop
    if risk > entry * max_risk_frac:
        stop = entry - (entry * max_risk_frac)
        risk = entry - stop
    t1 = entry + (risk * t1_r)
    t2 = entry + (risk * t2_r)
    risk_pct = (risk / entry) * 100
    reward1_pct = ((t1 - entry) / entry) * 100
    reward2_pct = ((t2 - entry) / entry) * 100
    return round(stop, 2), round(t1, 2), round(t2, 2), round(risk_pct, 2)


def _strength(score: float) -> str:
    if score >= 70:
        return "Strong"
    if score >= 55:
        return "Moderate"
    return "Weak"


def analyze_symbol(symbol: str, df: pd.DataFrame, market=None, settings: SignalSettings | None = None, interval: str = "1d") -> TradeSignal | None:
    """Delegate to v2 engine (stricter confluence logic)."""
    from us_stock_scanner.signal_engine import analyze_symbol_v2

    return analyze_symbol_v2(symbol, df, market, settings=settings, interval=interval)


def find_all_signals(
    history: dict[str, pd.DataFrame],
    *,
    min_score: float = 45,
    market=None,
    settings: SignalSettings | None = None,
) -> list[TradeSignal]:
    from us_stock_scanner.signal_engine import find_all_signals_v2

    signals = find_all_signals_v2(history, market, settings=settings, interval="1d")
    return [s for s in signals if s.score >= min_score]