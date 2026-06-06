"""Append scan results to the journal (now backed by SQLite).

Public API kept compatible with the rest of the app (returns DataFrames, etc.).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import storage


def journal_path() -> Path:
    return storage.journal_path()


def append_scan(
    result: "ScanResult",
    universe: str = "sp500",
    *,
    include_watchlist: bool = False,
) -> Path:
    """Log top 3 picks (and optionally worth watching)."""
    storage.append_scan(result, universe=universe, include_watchlist=include_watchlist)
    return storage.journal_path()


def load_journal() -> pd.DataFrame:
    return storage.load_journal()


def pending_outcomes(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rows not yet evaluated or marked open."""
    data = df if df is not None else load_journal()
    if data.empty:
        return data
    status = data["outcome_status"].fillna("").astype(str).str.strip()
    return data[status.eq("") | status.eq("open")].copy()