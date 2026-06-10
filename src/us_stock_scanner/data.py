"""Download and normalize market data."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
import yfinance as yf

# Simple in-memory cache for ticker data (keyed by (ticker, period, interval)).
# This dramatically speeds up repeated scans (e.g. trying different modes on the same
# universe/period) and full-index scans in the UI, since yfinance downloads are the
# main bottleneck. Cache lives for the process lifetime (good for Streamlit sessions
# and CLI runs).
_HISTORY_CACHE: dict[tuple[str, str, str], pd.DataFrame] = {}


def fetch_history(
    tickers: Iterable[str],
    *,
    period: str = "3mo",
    interval: str = "1d",
    batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    """Download OHLCV history in batches. Returns ticker -> DataFrame.
    interval: bar size, e.g. "1d", "1wk", "1mo" (like scan_period lookback).

    Uses an in-memory cache (per ticker+period+interval) to avoid re-downloading
    the same data when the user changes modes, re-runs scans, or looks at charts.
    This is the main performance win for full-index scans and interactive use.
    """
    symbols = list(dict.fromkeys(tickers))
    frames: dict[str, pd.DataFrame] = {}
    to_fetch: list[str] = []

    for sym in symbols:
        key = (sym.upper(), period, interval)
        if key in _HISTORY_CACHE:
            frames[sym] = _HISTORY_CACHE[key].copy()
        else:
            to_fetch.append(sym)

    if not to_fetch:
        return frames

    # Only download what we don't have cached
    symbols = to_fetch
    for start in range(0, len(symbols), batch_size):
        chunk = symbols[start : start + batch_size]
        raw = yf.download(
            chunk,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            continue

        if len(chunk) == 1:
            symbol = chunk[0]
            df = _normalize_frame(raw.copy())
            frames[symbol] = df
            _HISTORY_CACHE[(symbol.upper(), period, interval)] = df.copy()
            continue

        for symbol in chunk:
            if symbol not in raw.columns.get_level_values(0):
                continue
            df = raw[symbol].dropna(how="all")
            if not df.empty:
                df = _normalize_frame(df)
                frames[symbol] = df
                _HISTORY_CACHE[(symbol.upper(), period, interval)] = df.copy()

    return frames


_OHLCV = {"Open", "High", "Low", "Close", "Volume"}


def _flatten_columns(columns) -> list[str]:
    """yfinance uses (Price, Ticker) or (Ticker, Price) MultiIndex layouts."""
    flat: list[str] = []
    for col in columns:
        if isinstance(col, str):
            flat.append(col)
            continue
        if isinstance(col, tuple):
            for part in col:
                if part in _OHLCV:
                    flat.append(part)
                    break
            else:
                flat.append(str(col[-1]))
            continue
        flat.append(str(col))
    return flat


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.title() for c in _flatten_columns(df.columns)]
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns {missing}")
    return df.dropna(subset=["Close", "Volume"])