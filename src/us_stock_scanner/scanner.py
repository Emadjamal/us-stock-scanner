"""Orchestrate universe load, data fetch, and screening."""

from __future__ import annotations

import pandas as pd

from us_stock_scanner.data import fetch_history
from us_stock_scanner.filters import ScanCriteria, evaluate_symbol, sort_column
from us_stock_scanner.universe import resolve_universe

BASE_COLUMNS = ["symbol", "price", "change_pct", "volume", "avg_volume_20d", "rsi"]


def run_scan(
    universe: str,
    criteria: ScanCriteria,
    *,
    period: str = "3mo",
    interval: str = "1d",
    limit: int | None = None,
    batch_size: int = 50,
) -> pd.DataFrame:
    tickers = resolve_universe(universe)
    if limit is not None:
        tickers = tickers[:limit]

    history = fetch_history(tickers, period=period, interval=interval, batch_size=batch_size)
    rows: list[dict] = []

    for symbol, df in history.items():
        metrics = evaluate_symbol(df, criteria)
        if metrics is None:
            continue
        rows.append({"symbol": symbol, **metrics})

    if not rows:
        return pd.DataFrame(columns=BASE_COLUMNS)

    result = pd.DataFrame(rows)
    by = sort_column(criteria)
    if by in result.columns:
        return result.sort_values(by, ascending=False).reset_index(drop=True)
    return result.sort_values("change_pct", ascending=False).reset_index(drop=True)