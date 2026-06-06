"""Technical indicators computed from OHLCV history."""

from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def moving_average(series: pd.Series, period: int, ma_type: str = "sma") -> pd.Series:
    if ma_type == "ema":
        return ema(series, period)
    if ma_type == "sma":
        return sma(series, period)
    raise ValueError(f"Unknown MA type: {ma_type!r}. Use sma or ema.")


def macd(
    close: pd.Series,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD line, signal line, and histogram."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": histogram},
        index=close.index,
    )


def gap_pct(open_: pd.Series, prev_close: pd.Series) -> pd.Series:
    """Overnight gap %% = (open - prior close) / prior close * 100."""
    base = prev_close.replace(0, pd.NA)
    return ((open_ - prev_close) / base) * 100


def crossed_above(fast: pd.Series, slow: pd.Series) -> bool:
    """Fast crossed above slow on the latest bar."""
    if len(fast) < 2 or len(slow) < 2:
        return False
    prev_fast, last_fast = float(fast.iloc[-2]), float(fast.iloc[-1])
    prev_slow, last_slow = float(slow.iloc[-2]), float(slow.iloc[-1])
    return prev_fast <= prev_slow and last_fast > last_slow


def crossed_below(fast: pd.Series, slow: pd.Series) -> bool:
    if len(fast) < 2 or len(slow) < 2:
        return False
    prev_fast, last_fast = float(fast.iloc[-2]), float(fast.iloc[-1])
    prev_slow, last_slow = float(slow.iloc[-2]), float(slow.iloc[-1])
    return prev_fast >= prev_slow and last_fast < last_slow


def bollinger_bands(
    close: pd.Series,
    *,
    period: int = 20,
    std_dev: float = 2.0,
) -> pd.DataFrame:
    middle = sma(close, period)
    rolling_std = close.rolling(window=period, min_periods=period).std()
    upper = middle + (std_dev * rolling_std)
    lower = middle - (std_dev * rolling_std)
    width = upper - lower
    pct_b = (close - lower) / width.replace(0, pd.NA)
    bandwidth_pct = (width / middle.replace(0, pd.NA)) * 100
    return pd.DataFrame(
        {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "pct_b": pct_b * 100,
            "bandwidth_pct": bandwidth_pct,
        },
        index=close.index,
    )


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def relative_volume(volume: pd.Series, lookback: int = 20) -> pd.Series:
    avg = volume.rolling(window=lookback, min_periods=lookback).mean()
    return volume / avg.replace(0, pd.NA)


def pct_from_rolling_high(close: pd.Series, lookback: int = 252) -> pd.Series:
    """Percent distance below rolling high (0 = at high, -5 = 5%% below)."""
    rolling_high = close.rolling(window=lookback, min_periods=lookback).max()
    return ((close / rolling_high.replace(0, pd.NA)) - 1) * 100


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    lowest = low.rolling(window=k_period, min_periods=k_period).min()
    highest = high.rolling(window=k_period, min_periods=k_period).max()
    span = (highest - lowest).replace(0, pd.NA)
    pct_k = ((close - lowest) / span) * 100
    pct_d = pct_k.rolling(window=d_period, min_periods=d_period).mean()
    return pd.DataFrame({"stoch_k": pct_k, "stoch_d": pct_d}, index=close.index)


def n_day_return(close: pd.Series, days: int = 5) -> float:
    if len(close) <= days:
        return 0.0
    base = float(close.iloc[-days - 1])
    if base <= 0:
        return 0.0
    return ((float(close.iloc[-1]) / base) - 1) * 100


def relative_strength_vs(
    stock_close: pd.Series,
    benchmark_close: pd.Series,
    days: int = 5,
) -> float:
    """Stock return minus benchmark return over N days (%)."""
    return n_day_return(stock_close, days) - n_day_return(benchmark_close, days)


def bearish_rsi_divergence(close: pd.Series, rsi_series: pd.Series, lookback: int = 14) -> bool:
    """Price firm/higher while RSI rolls over — distribution risk."""
    if len(close) < lookback + 2:
        return False
    price_near_high = float(close.iloc[-1]) >= float(close.tail(lookback).max()) * 0.995
    rsi_falling = float(rsi_series.iloc[-1]) < float(rsi_series.iloc[-4])
    rsi_lower_high = float(rsi_series.iloc[-1]) < float(rsi_series.tail(lookback).max()) - 3
    return price_near_high and rsi_falling and rsi_lower_high


def bearish_macd_divergence(close: pd.Series, hist: pd.Series, lookback: int = 14) -> bool:
    """Price near highs but MACD histogram fading."""
    if len(close) < lookback + 2:
        return False
    price_near_high = float(close.iloc[-1]) >= float(close.tail(lookback).max()) * 0.995
    hist_tail = hist.dropna().tail(6)
    if len(hist_tail) < 4:
        return False
    hist_fading = float(hist_tail.iloc[-1]) < float(hist_tail.iloc[0])
    return price_near_high and hist_fading and float(hist.iloc[-1]) < float(hist.tail(lookback).max())


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average Directional Index (trend strength)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr_vals = atr(high, low, close, period)
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_vals)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_vals)
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100
    return dx.ewm(alpha=1 / period, adjust=False).mean()