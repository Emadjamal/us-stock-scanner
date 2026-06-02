"""Load ticker universes for US equities."""

from __future__ import annotations

import io
from functools import lru_cache

import pandas as pd
import requests

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_NASDAQ100 = "https://en.wikipedia.org/wiki/Nasdaq-100"


def _read_wiki_tables(url: str) -> list[pd.DataFrame]:
    headers = {"User-Agent": "us-stock-scanner/0.1"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return pd.read_html(io.StringIO(response.text))


@lru_cache(maxsize=4)
def sp500_tickers() -> list[str]:
    """S&P 500 symbols from Wikipedia."""
    tables = _read_wiki_tables(WIKI_SP500)
    symbols = tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False)
    return sorted(symbols.tolist())


@lru_cache(maxsize=4)
def nasdaq100_tickers() -> list[str]:
    """Nasdaq-100 symbols from Wikipedia."""
    tables = _read_wiki_tables(WIKI_NASDAQ100)
    for table in tables:
        for col in ("Ticker", "Symbol"):
            if col in table.columns:
                symbols = table[col].astype(str).str.replace(".", "-", regex=False)
                return sorted(symbols.tolist())
    raise ValueError("Could not parse Nasdaq-100 ticker table")


def resolve_universe(name: str) -> list[str]:
    key = name.strip().lower().replace("_", "-")
    if key in ("sp500", "s-p-500", "s&p500"):
        return sp500_tickers()
    if key in ("nasdaq100", "ndx", "qqq"):
        return nasdaq100_tickers()
    raise ValueError(f"Unknown universe: {name!r}. Use sp500 or nasdaq100.")