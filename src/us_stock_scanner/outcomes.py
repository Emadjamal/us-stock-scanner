"""Evaluate past journal entries against price history."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import storage
from us_stock_scanner.journal import load_journal

console = Console()


def _parse_scan_date(value: str) -> pd.Timestamp:
    return pd.to_datetime(value, utc=True).tz_convert(None)


def _evaluate_trade(
    df: pd.DataFrame,
    *,
    entry: float,
    stop: float,
    t1: float,
    t2: float,
) -> tuple[str, float, float, int]:
    """
    Walk bars in order; return status, last price, pct from entry, days held.
    Uses limit entry — assumes fill if price traded at or below entry on a bar.
    """
    if df.empty or entry <= 0:
        return "no_data", 0.0, 0.0, 0

    filled = False
    status = "open"
    days = len(df)

    for _, bar in df.iterrows():
        low = float(bar["Low"])
        high = float(bar["High"])
        if not filled:
            if low <= entry:
                filled = True
            else:
                continue
        if low <= stop:
            return "stopped", float(bar["Close"]), ((stop - entry) / entry) * 100, days
        if high >= t2:
            close = float(bar["Close"])
            return "hit_t2", close, ((t2 - entry) / entry) * 100, days
        if high >= t1:
            close = float(bar["Close"])
            return "hit_t1", close, ((t1 - entry) / entry) * 100, days

    last_close = float(df["Close"].iloc[-1])
    if not filled:
        pct_ref = ((last_close - entry) / entry) * 100
        return "not_filled", last_close, pct_ref, days

    pct = ((last_close - entry) / entry) * 100
    if last_close <= stop:
        return "stopped", last_close, pct, days
    if last_close >= t2:
        return "hit_t2", last_close, pct, days
    if last_close >= t1:
        return "hit_t1", last_close, pct, days
    if pct >= 0:
        return "open_profit", last_close, pct, days
    return "open_loss", last_close, pct, days


def _fetch_since(symbol: str, start: pd.Timestamp) -> pd.DataFrame:
    from us_stock_scanner.data import _normalize_frame

    raw = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=True,
    )
    if raw.empty:
        return raw
    return _normalize_frame(raw.copy())


def update_outcomes(*, only_pending: bool = True) -> pd.DataFrame:
    """Refresh outcome columns in the journal CSV."""
    journal = load_journal()
    if journal.empty:
        return journal

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cache: dict[tuple[str, str], pd.DataFrame] = {}
    updated_indices: list = []

    for idx, row in journal.iterrows():
        status_prev = str(row.get("outcome_status", "")).strip()
        if only_pending and status_prev not in ("", "open", "error"):
            continue

        symbol = str(row["symbol"])
        scan_dt = _parse_scan_date(str(row["scan_date"]))
        key = (symbol, scan_dt.strftime("%Y-%m-%d"))
        try:
            if key not in cache:
                cache[key] = _fetch_since(symbol, scan_dt)

            bars = cache[key]
            entry = float(row["entry"])
            stop = float(row["stop_loss"])
            t1 = float(row["target1"])
            t2 = float(row["target2"])

            status, price, pct, days = _evaluate_trade(
                bars, entry=entry, stop=stop, t1=t1, t2=t2
            )

            journal.at[idx, "outcome_status"] = status
            journal.at[idx, "outcome_date"] = now
            journal.at[idx, "outcome_price"] = round(price, 2) if price else ""
            journal.at[idx, "pct_from_entry"] = round(pct, 2)
            journal.at[idx, "days_held"] = int(days) if days else 0
            updated_indices.append(idx)
        except Exception:
            journal.at[idx, "outcome_status"] = "error"
            journal.at[idx, "outcome_date"] = now
            updated_indices.append(idx)

    # Persist updates via the new storage layer (only the rows we evaluated in this pass)
    updates = []
    for idx in updated_indices:
        row = journal.loc[idx]
        updates.append({
            "symbol": row["symbol"],
            "scan_date": row["scan_date"],
            "outcome_status": row["outcome_status"],
            "outcome_date": row["outcome_date"],
            "outcome_price": row["outcome_price"],
            "pct_from_entry": row["pct_from_entry"],
            "days_held": row["days_held"],
        })
    storage.update_journal_rows(updates)
    return journal


def _status_style(status: str) -> str:
    if status in ("hit_t1", "hit_t2"):
        return "green"
    if status == "stopped":
        return "red"
    if status in ("open_profit", "open"):
        return "cyan"
    if status in ("open_loss", "not_filled", "pending"):
        return "yellow"
    return "white"


def print_outcome_report(*, last_n: int = 30) -> None:
    journal = load_journal()
    if journal.empty:
        console.print(
            Panel(
                "[yellow]No journal yet.[/yellow] Run [bold].\\scan.ps1[/bold] first to log signals.",
                title="Signal journal",
            )
        )
        return

    journal = update_outcomes(only_pending=True)
    recent = journal.tail(last_n).copy()

    console.print(
        Panel(
            f"[bold]{len(journal)}[/bold] signals logged · SQLite:\n[dim]{storage.get_db_path()}[/dim]",
            title="Signal journal",
            border_style="blue",
        )
    )

    # Summary on completed-ish statuses
    status_col = journal["outcome_status"].fillna("").astype(str)
    evaluated = journal[status_col.ne("")]
    if not evaluated.empty:
        counts = evaluated["outcome_status"].value_counts()
        total = len(evaluated)
        wins = counts.get("hit_t1", 0) + counts.get("hit_t2", 0)
        stops = counts.get("stopped", 0)
        console.print(
            f"\n[bold]All-time stats[/bold] ({total} evaluated): "
            f"[green]{wins} hits[/green] · "
            f"[red]{stops} stopped[/red] · "
            f"{counts.get('open_profit', 0)} open+ · "
            f"{counts.get('open_loss', 0)} open- · "
            f"{counts.get('not_filled', 0)} limit not filled · "
        f"{counts.get('error', 0)} errors"
        )
        if total:
            console.print(f"[dim]Win rate (T1+T2): {100 * wins / total:.1f}%[/dim]\n")

    table = Table(title=f"Recent signals (last {len(recent)})", show_header=True)
    table.add_column("Scan", max_width=16)
    table.add_column("Sym", style="cyan")
    table.add_column("Gr")
    table.add_column("Entry", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("P/L %", justify="right")
    table.add_column("Days", justify="right")

    for _, row in recent.iterrows():
        raw_status = row.get("outcome_status", "")
        status = str(raw_status).strip() if pd.notna(raw_status) else ""
        if not status:
            status = "pending"
        pct = row.get("pct_from_entry", "")
        pct_str = f"{float(pct):+.1f}%" if pct != "" and pd.notna(pct) else "—"
        price = row.get("outcome_price", "")
        price_str = f"${float(price):.2f}" if price != "" and pd.notna(price) else "—"
        scan_short = str(row["scan_date"])[:16]
        table.add_row(
            scan_short,
            str(row["symbol"]),
            str(row.get("grade", "")),
            f"${float(row['entry']):.2f}",
            f"[{_status_style(status)}]{status}[/]",
            price_str,
            pct_str,
            str(row.get("days_held", "")),
        )
    console.print(table)