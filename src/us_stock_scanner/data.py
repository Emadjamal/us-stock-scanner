"""Download and normalize market data."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
import yfinance as yf


def fetch_history(
    tickers: Iterable[str],
    *,
    period: str = "3mo",
    batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    """Download OHLCV history in batches. Returns ticker -> DataFrame."""
    symbols = list(dict.fromkeys(tickers))
    frames: dict[str, pd.DataFrame] = {}

    for start in range(0, len(symbols), batch_size):
        chunk = symbols[start : start + batch_size]
        raw = yf.download(
            chunk,
            period=period,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            continue

        if len(chunk) == 1:
            symbol = chunk[0]
            frames[symbol] = _normalize_frame(raw.copy())
            continue

        for symbol in chunk:
            if symbol not in raw.columns.get_level_values(0):
                continue
            df = raw[symbol].dropna(how="all")
            if not df.empty:
                frames[symbol] = _normalize_frame(df)

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