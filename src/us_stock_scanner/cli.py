"""Command-line interface for the stock scanner."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from us_stock_scanner.config import criteria_from_config, load_config
from us_stock_scanner.filters import ScanCriteria
from us_stock_scanner.scanner import run_scan

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Screen US stocks by price, volume, momentum, and RSI.",
    )
    parser.add_argument(
        "-u",
        "--universe",
        default="sp500",
        choices=["sp500", "nasdaq100"],
        help="Ticker universe (default: sp500)",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="YAML config file (see config.example.yaml)",
    )
    parser.add_argument("--min-price", type=float, help="Minimum last close price")
    parser.add_argument("--max-price", type=float, help="Maximum last close price")
    parser.add_argument("--min-volume", type=float, help="Minimum last-day volume")
    parser.add_argument(
        "--min-avg-volume-20d",
        type=float,
        help="Minimum 20-day average volume",
    )
    parser.add_argument("--min-change-pct", type=float, help="Minimum daily %% change")
    parser.add_argument("--max-change-pct", type=float, help="Maximum daily %% change")
    parser.add_argument("--min-rsi", type=float, help="Minimum RSI(14)")
    parser.add_argument("--max-rsi", type=float, help="Maximum RSI(14)")
    parser.add_argument(
        "--period",
        default="3mo",
        help="yfinance history period (default: 3mo)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max tickers to scan (useful for quick tests)",
    )
    return parser


def _criteria_from_args(
    args: argparse.Namespace,
) -> tuple[ScanCriteria, str, str, int | None]:
    if args.config:
        data = load_config(args.config)
        criteria = criteria_from_config(data)
        universe = data.get("universe", args.universe)
        period = data.get("period", args.period)
        limit = data.get("limit", args.limit)
        return criteria, universe, period, limit

    criteria = ScanCriteria(
        min_price=args.min_price,
        max_price=args.max_price,
        min_volume=args.min_volume,
        min_change_pct=args.min_change_pct,
        max_change_pct=args.max_change_pct,
        min_rsi=args.min_rsi,
        max_rsi=args.max_rsi,
        min_avg_volume_20d=args.min_avg_volume_20d,
    )
    return criteria, args.universe, args.period, args.limit


def _print_results(df) -> None:
    if df.empty:
        console.print("[yellow]No symbols matched your filters.[/yellow]")
        return

    table = Table(title=f"Matches ({len(df)})")
    for col in df.columns:
        table.add_column(col, justify="right" if col != "symbol" else "left")
    for _, row in df.iterrows():
        table.add_row(*(str(row[c]) for c in df.columns))
    console.print(table)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    criteria, universe, period, limit = _criteria_from_args(args)

    console.print(f"[bold]Scanning[/bold] {universe} (limit={limit or 'all'})...")
    results = run_scan(
        universe,
        criteria,
        period=period,
        limit=limit,
    )
    _print_results(results)
    return 0