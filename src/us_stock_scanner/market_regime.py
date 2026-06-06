"""Broad market context — only favor longs when conditions support them."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from us_stock_scanner.indicators import moving_average, rsi


@dataclass(frozen=True)
class MarketRegime:
    symbol: str
    bullish: bool
    risk_on_score: int  # 0–3
    summary: str
    spy_change_pct: float
    above_ma50: bool
    above_ma200: bool


def analyze_market_regime(spy_df: pd.DataFrame) -> MarketRegime:
    """Score SPY trend for long-bias scans."""
    if len(spy_df) < 50:
        return MarketRegime("SPY", False, 0, "Insufficient SPY history", 0.0, False, False)

    close = spy_df["Close"]
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    change = ((last - prev) / prev) * 100 if prev else 0.0
    ma50 = moving_average(close, 50, "sma")
    ma200 = moving_average(close, min(200, len(close) - 1), "sma")
    above50 = last > float(ma50.iloc[-1])
    above200 = last > float(ma200.iloc[-1])
    last_rsi = float(rsi(close).iloc[-1])

    score = 0
    parts: list[str] = []

    if above50:
        score += 1
        parts.append("SPY above 50-day MA")
    if above200:
        score += 1
        parts.append("SPY above 200-day MA")
    if change >= 0:
        score += 1
        parts.append("SPY green today")
    if 40 <= last_rsi <= 65:
        parts.append("SPY RSI healthy")

    bullish = score >= 2 and above50
    summary = " · ".join(parts) if parts else "SPY weak / unclear"

    if not bullish:
        summary = f"[caution] {summary} — long setups need extra confirmation"

    return MarketRegime(
        symbol="SPY",
        bullish=bullish,
        risk_on_score=score,
        summary=summary,
        spy_change_pct=round(change, 2),
        above_ma50=above50,
        above_ma200=above200,
    )