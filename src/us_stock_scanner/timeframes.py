"""Higher timeframe helpers."""

from __future__ import annotations

import pandas as pd

from us_stock_scanner.indicators import moving_average


def to_weekly_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly."""
    data = df.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index)
    weekly = data.resample("W").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    return weekly.dropna(subset=["Close"])


def weekly_trend_bullish(df: pd.DataFrame, ma_period: int = 10) -> tuple[bool, str]:
    """
    Weekly trend OK for longs: close above weekly MA and not making lower lows.
    Returns (passed, detail).
    """
    weekly = to_weekly_bars(df)
    if len(weekly) < ma_period + 2:
        return False, "Not enough weekly history"

    close = weekly["Close"]
    last = float(close.iloc[-1])
    wma = moving_average(close, ma_period, "sma")
    last_wma = float(wma.iloc[-1])
    four_weeks_ago = float(close.iloc[-5]) if len(close) >= 5 else float(close.iloc[0])

    above_ma = last > last_wma
    higher_than_month = last >= four_weeks_ago * 0.99

    if above_ma and higher_than_month:
        return True, f"Weekly close above {ma_period}-W MA, 4-week base intact"
    if above_ma:
        return False, "Above weekly MA but 4-week structure soft"
    return False, "Weekly close below MA — avoid longs"