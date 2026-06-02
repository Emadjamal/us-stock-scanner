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
            df = raw.copy()
            df.columns = [c if isinstance(c, str) else c[0] for c in df.columns]
            frames[symbol] = _normalize_frame(df)
            continue

        for symbol in chunk:
            if symbol not in raw.columns.get_level_values(0):
                continue
            df = raw[symbol].dropna(how="all")
            if not df.empty:
                frames[symbol] = _normalize_frame(df)

    return frames


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).title() for c in df.columns]
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns {missing}")
    return df.dropna(subset=["Close", "Volume"])