"""Orchestrate universe load, data fetch, and screening."""

from __future__ import annotations

import pandas as pd

from us_stock_scanner.data import fetch_history
from us_stock_scanner.filters import ScanCriteria, evaluate_symbol
from us_stock_scanner.universe import resolve_universe


def run_scan(
    universe: str,
    criteria: ScanCriteria,
    *,
    period: str = "3mo",
    limit: int | None = None,
    batch_size: int = 50,
) -> pd.DataFrame:
    tickers = resolve_universe(universe)
    if limit is not None:
        tickers = tickers[:limit]

    history = fetch_history(tickers, period=period, batch_size=batch_size)
    rows: list[dict] = []

    for symbol, df in history.items():
        metrics = evaluate_symbol(df, criteria)
        if metrics is None:
            continue
        rows.append({"symbol": symbol, **metrics})

    if not rows:
        return pd.DataFrame(columns=["symbol", "price", "change_pct", "volume", "avg_volume_20d", "rsi"])

    result = pd.DataFrame(rows)
    return result.sort_values("change_pct", ascending=False).reset_index(drop=True)