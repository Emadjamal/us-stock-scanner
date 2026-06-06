"""User watchlist — load, save, normalize tickers.

Now backed by SQLite (via storage.py). The public API is kept compatible.
Legacy file support is handled inside the storage layer on first run.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import storage


def normalize_symbol(raw: str) -> str | None:
    s = raw.strip().upper().replace(".", "-")
    if not s or s.startswith("#"):
        return None
    if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", s):
        return None
    return s


def load_watchlist(path: Path | None = None) -> list[str]:
    # We ignore the path parameter for the new backend (kept for API compatibility).
    # Legacy migration happens automatically in storage.init_db()
    return storage.load_watchlist()


def save_watchlist(symbols: list[str], path: Path | None = None) -> Path:
    storage.save_watchlist(symbols)
    # Return a plausible path for callers that print it
    return storage.watchlist_path()


def add_symbols(symbols: list[str], path: Path | None = None) -> list[str]:
    return storage.add_symbols(symbols)


def remove_symbols(symbols: list[str], path: Path | None = None) -> list[str]:
    return storage.remove_symbols(symbols)


def watchlist_path() -> Path:
    return storage.watchlist_path()