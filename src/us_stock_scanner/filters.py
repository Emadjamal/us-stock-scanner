"""Screening rules applied to each symbol's latest bar."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from us_stock_scanner.indicators import (
    adx,
    atr,
    bollinger_bands,
    crossed_above,
    crossed_below,
    gap_pct,
    macd,
    moving_average,
    pct_from_rolling_high,
    relative_volume,
    rsi,
    stochastic,
)


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

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_crossover: str | None = None
    min_macd_hist: float | None = None
    max_macd_hist: float | None = None

    # Moving averages
    ma_fast: int = 20
    ma_slow: int = 50
    ma_type: str = "sma"
    ma_crossover: str | None = None

    # Gaps
    min_gap_pct: float | None = None
    max_gap_pct: float | None = None
    gap_direction: str | None = None

    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0
    min_bb_pct_b: float | None = None
    max_bb_pct_b: float | None = None
    max_bb_bandwidth_pct: float | None = None  # squeeze: tight bands
    bb_touch: str | None = None  # upper | lower

    # 52-week (rolling) high
    high_lookback: int = 252
    min_pct_from_high: float | None = None  # e.g. -5 = within 5% of high
    max_pct_from_high: float | None = None

    # Relative volume
    rvol_lookback: int = 20
    min_rvol: float | None = None
    max_rvol: float | None = None

    # ATR breakout
    atr_period: int = 14
    min_atr_multiple: float | None = None  # |daily move| / ATR

    # Stochastic
    stoch_k_period: int = 14
    stoch_d_period: int = 3
    min_stoch_k: float | None = None
    max_stoch_k: float | None = None
    stoch_crossover: str | None = None  # bullish | bearish

    # ADX trend strength
    adx_period: int = 14
    min_adx: float | None = None
    max_adx: float | None = None


def _min_bars(criteria: ScanCriteria) -> int:
    need = max(criteria.rsi_period + 1, 2)
    if criteria.ma_crossover:
        need = max(need, criteria.ma_slow + 2)
    if _uses_macd(criteria):
        need = max(need, criteria.macd_slow + criteria.macd_signal + 2)
    if _uses_bb(criteria):
        need = max(need, criteria.bb_period + 2)
    if _uses_high(criteria):
        need = max(need, min(criteria.high_lookback, 252))
    if _uses_rvol(criteria):
        need = max(need, criteria.rvol_lookback + 1)
    if _uses_atr(criteria):
        need = max(need, criteria.atr_period + 2)
    if _uses_stoch(criteria):
        need = max(need, criteria.stoch_k_period + criteria.stoch_d_period)
    if _uses_adx(criteria):
        need = max(need, criteria.adx_period * 2)
    return need


def _uses_macd(c: ScanCriteria) -> bool:
    return bool(c.macd_crossover or c.min_macd_hist is not None or c.max_macd_hist is not None)


def _uses_gap(c: ScanCriteria) -> bool:
    return c.min_gap_pct is not None or c.max_gap_pct is not None or bool(c.gap_direction)


def _uses_bb(c: ScanCriteria) -> bool:
    return (
        c.min_bb_pct_b is not None
        or c.max_bb_pct_b is not None
        or c.max_bb_bandwidth_pct is not None
        or bool(c.bb_touch)
    )


def _uses_high(c: ScanCriteria) -> bool:
    return c.min_pct_from_high is not None or c.max_pct_from_high is not None


def _uses_rvol(c: ScanCriteria) -> bool:
    return c.min_rvol is not None or c.max_rvol is not None


def _uses_atr(c: ScanCriteria) -> bool:
    return c.min_atr_multiple is not None


def _uses_stoch(c: ScanCriteria) -> bool:
    return c.min_stoch_k is not None or c.max_stoch_k is not None or bool(c.stoch_crossover)


def _uses_adx(c: ScanCriteria) -> bool:
    return c.min_adx is not None or c.max_adx is not None


def _check_macd(macd_df: pd.DataFrame, criteria: ScanCriteria) -> bool:
    line = macd_df["macd"]
    signal = macd_df["signal"]
    hist = macd_df["hist"]
    last_hist = float(hist.iloc[-1])
    last_macd = float(line.iloc[-1])

    if criteria.min_macd_hist is not None and last_hist < criteria.min_macd_hist:
        return False
    if criteria.max_macd_hist is not None and last_hist > criteria.max_macd_hist:
        return False

    cross = (criteria.macd_crossover or "").lower()
    if cross == "bullish":
        return crossed_above(line, signal)
    if cross == "bearish":
        return crossed_below(line, signal)
    if cross == "above_zero":
        return last_macd > 0
    if cross == "below_zero":
        return last_macd < 0
    if cross in ("", "none"):
        return True
    raise ValueError(f"Unknown macd_crossover: {criteria.macd_crossover!r}")


def _check_ma(fast_ma: pd.Series, slow_ma: pd.Series, criteria: ScanCriteria) -> bool:
    cross = (criteria.ma_crossover or "").lower()
    if cross in ("", "none"):
        return True
    if cross == "golden":
        return crossed_above(fast_ma, slow_ma)
    if cross == "death":
        return crossed_below(fast_ma, slow_ma)
    if cross == "fast_above":
        return float(fast_ma.iloc[-1]) > float(slow_ma.iloc[-1])
    if cross == "fast_below":
        return float(fast_ma.iloc[-1]) < float(slow_ma.iloc[-1])
    raise ValueError(f"Unknown ma_crossover: {criteria.ma_crossover!r}")


def _check_gap(last_gap: float, criteria: ScanCriteria) -> bool:
    direction = (criteria.gap_direction or "").lower()
    if direction == "up" and last_gap <= 0:
        return False
    if direction == "down" and last_gap >= 0:
        return False
    if criteria.min_gap_pct is not None and last_gap < criteria.min_gap_pct:
        return False
    if criteria.max_gap_pct is not None and last_gap > criteria.max_gap_pct:
        return False
    return True


def _check_bb(bb_df: pd.DataFrame, last_close: float, criteria: ScanCriteria) -> bool:
    last_pct_b = float(bb_df["pct_b"].iloc[-1])
    last_bw = float(bb_df["bandwidth_pct"].iloc[-1])
    upper = float(bb_df["upper"].iloc[-1])
    lower = float(bb_df["lower"].iloc[-1])

    if criteria.min_bb_pct_b is not None and last_pct_b < criteria.min_bb_pct_b:
        return False
    if criteria.max_bb_pct_b is not None and last_pct_b > criteria.max_bb_pct_b:
        return False
    if criteria.max_bb_bandwidth_pct is not None and last_bw > criteria.max_bb_bandwidth_pct:
        return False

    touch = (criteria.bb_touch or "").lower()
    if touch == "upper" and last_close < upper * 0.995:
        return False
    if touch == "lower" and last_close > lower * 1.005:
        return False
    return True


def _check_high(last_pct: float, criteria: ScanCriteria) -> bool:
    if criteria.min_pct_from_high is not None and last_pct < criteria.min_pct_from_high:
        return False
    if criteria.max_pct_from_high is not None and last_pct > criteria.max_pct_from_high:
        return False
    return True


def _check_rvol(last_rvol: float, criteria: ScanCriteria) -> bool:
    if criteria.min_rvol is not None and last_rvol < criteria.min_rvol:
        return False
    if criteria.max_rvol is not None and last_rvol > criteria.max_rvol:
        return False
    return True


def _check_atr(last_multiple: float, criteria: ScanCriteria) -> bool:
    if criteria.min_atr_multiple is not None and last_multiple < criteria.min_atr_multiple:
        return False
    return True


def _check_stoch(stoch_df: pd.DataFrame, criteria: ScanCriteria) -> bool:
    k = stoch_df["stoch_k"]
    d = stoch_df["stoch_d"]
    last_k = float(k.iloc[-1])

    if criteria.min_stoch_k is not None and last_k < criteria.min_stoch_k:
        return False
    if criteria.max_stoch_k is not None and last_k > criteria.max_stoch_k:
        return False

    cross = (criteria.stoch_crossover or "").lower()
    if cross == "bullish":
        return crossed_above(k, d)
    if cross == "bearish":
        return crossed_below(k, d)
    if cross in ("", "none"):
        return True
    raise ValueError(f"Unknown stoch_crossover: {criteria.stoch_crossover!r}")


def _check_adx(last_adx: float, criteria: ScanCriteria) -> bool:
    if criteria.min_adx is not None and last_adx < criteria.min_adx:
        return False
    if criteria.max_adx is not None and last_adx > criteria.max_adx:
        return False
    return True


def evaluate_symbol(df: pd.DataFrame, criteria: ScanCriteria) -> dict | None:
    if len(df) < _min_bars(criteria):
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]
    volume = df["Volume"]

    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    last_open = float(open_.iloc[-1])
    last_volume = float(volume.iloc[-1])
    change_pct = ((last_close - prev_close) / prev_close) * 100 if prev_close else 0.0
    avg_volume_20d = float(volume.tail(20).mean())
    last_rsi = float(rsi(close, criteria.rsi_period).iloc[-1])

    gaps = gap_pct(open_, close.shift(1))
    last_gap = float(gaps.iloc[-1]) if pd.notna(gaps.iloc[-1]) else 0.0

    macd_df = macd(close, fast=criteria.macd_fast, slow=criteria.macd_slow, signal=criteria.macd_signal)
    fast_ma = moving_average(close, criteria.ma_fast, criteria.ma_type)
    slow_ma = moving_average(close, criteria.ma_slow, criteria.ma_type)
    bb_df = bollinger_bands(close, period=criteria.bb_period, std_dev=criteria.bb_std)
    rvol_series = relative_volume(volume, criteria.rvol_lookback)
    high_pct_series = pct_from_rolling_high(close, criteria.high_lookback)
    atr_series = atr(high, low, close, criteria.atr_period)
    stoch_df = stochastic(
        high, low, close, k_period=criteria.stoch_k_period, d_period=criteria.stoch_d_period
    )
    adx_series = adx(high, low, close, criteria.adx_period)

    last_rvol = float(rvol_series.iloc[-1]) if pd.notna(rvol_series.iloc[-1]) else 0.0
    last_high_pct = float(high_pct_series.iloc[-1]) if pd.notna(high_pct_series.iloc[-1]) else -100.0
    last_atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0.0
    atr_multiple = abs(last_close - prev_close) / last_atr if last_atr else 0.0
    last_adx = float(adx_series.iloc[-1]) if pd.notna(adx_series.iloc[-1]) else 0.0

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

    if _uses_macd(criteria) and not _check_macd(macd_df, criteria):
        return None
    if criteria.ma_crossover and not _check_ma(fast_ma, slow_ma, criteria):
        return None
    if _uses_gap(criteria) and not _check_gap(last_gap, criteria):
        return None
    if _uses_bb(criteria) and not _check_bb(bb_df, last_close, criteria):
        return None
    if _uses_high(criteria) and not _check_high(last_high_pct, criteria):
        return None
    if _uses_rvol(criteria) and not _check_rvol(last_rvol, criteria):
        return None
    if _uses_atr(criteria) and not _check_atr(atr_multiple, criteria):
        return None
    if _uses_stoch(criteria) and not _check_stoch(stoch_df, criteria):
        return None
    if _uses_adx(criteria) and not _check_adx(last_adx, criteria):
        return None

    row: dict = {
        "price": round(last_close, 2),
        "change_pct": round(change_pct, 2),
        "volume": int(last_volume),
        "avg_volume_20d": int(avg_volume_20d),
        "rsi": round(last_rsi, 1),
    }

    if _uses_gap(criteria):
        row["gap_pct"] = round(last_gap, 2)
    if _uses_macd(criteria):
        row["macd_hist"] = round(float(macd_df["hist"].iloc[-1]), 3)
    if criteria.ma_crossover:
        row[f"ma{criteria.ma_fast}"] = round(float(fast_ma.iloc[-1]), 2)
        row[f"ma{criteria.ma_slow}"] = round(float(slow_ma.iloc[-1]), 2)
    if _uses_bb(criteria):
        row["bb_pct_b"] = round(float(bb_df["pct_b"].iloc[-1]), 1)
        row["bb_bw_pct"] = round(float(bb_df["bandwidth_pct"].iloc[-1]), 2)
    if _uses_high(criteria):
        row["pct_from_high"] = round(last_high_pct, 2)
    if _uses_rvol(criteria):
        row["rvol"] = round(last_rvol, 2)
    if _uses_atr(criteria):
        row["atr"] = round(last_atr, 2)
        row["atr_mult"] = round(atr_multiple, 2)
    if _uses_stoch(criteria):
        row["stoch_k"] = round(float(stoch_df["stoch_k"].iloc[-1]), 1)
        row["stoch_d"] = round(float(stoch_df["stoch_d"].iloc[-1]), 1)
    if _uses_adx(criteria):
        row["adx"] = round(last_adx, 1)

    return row


def sort_column(criteria: ScanCriteria) -> str:
    if _uses_gap(criteria):
        return "gap_pct"
    if _uses_rvol(criteria):
        return "rvol"
    if _uses_atr(criteria):
        return "atr_mult"
    if _uses_high(criteria):
        return "pct_from_high"
    if _uses_macd(criteria):
        return "macd_hist"
    if _uses_bb(criteria):
        return "bb_pct_b"
    return "change_pct"