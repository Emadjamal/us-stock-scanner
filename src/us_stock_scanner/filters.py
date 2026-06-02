"""Screening rules applied to each symbol's latest bar."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from us_stock_scanner.indicators import rsi


@dataclass(frozen=True)
class ScanCriteria:
    min_price: float | None = None
    max_price: float | None = None
    min_volume: float | None = None
    min_change_pct: float | None = None
    max_change_pct: float | None = None
    min_rsi: float | None = None
    max_rsi: float | None = None
    rsi_period: int = 14
    min_avg_volume_20d: float | None = None


def evaluate_symbol(df: pd.DataFrame, criteria: ScanCriteria) -> dict | None:
    if len(df) < max(criteria.rsi_period + 1, 2):
        return None

    close = df["Close"]
    volume = df["Volume"]
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    last_volume = float(volume.iloc[-1])
    change_pct = ((last_close - prev_close) / prev_close) * 100 if prev_close else 0.0
    avg_volume_20d = float(volume.tail(20).mean())
    last_rsi = float(rsi(close, criteria.rsi_period).iloc[-1])

    if criteria.min_price is not None and last_close < criteria.min_price:
        return None
    if criteria.max_price is not None and last_close > criteria.max_price:
        return None
    if criteria.min_volume is not None and last_volume < criteria.min_volume:
        return None
    if criteria.min_avg_volume_20d is not None and avg_volume_20d < criteria.min_avg_volume_20d:
        return None
    if criteria.min_change_pct is not None and change_pct < criteria.min_change_pct:
        return None
    if criteria.max_change_pct is not None and change_pct > criteria.max_change_pct:
        return None
    if criteria.min_rsi is not None and last_rsi < criteria.min_rsi:
        return None
    if criteria.max_rsi is not None and last_rsi > criteria.max_rsi:
        return None

    return {
        "price": round(last_close, 2),
        "change_pct": round(change_pct, 2),
        "volume": int(last_volume),
        "avg_volume_20d": int(avg_volume_20d),
        "rsi": round(last_rsi, 1),
    }