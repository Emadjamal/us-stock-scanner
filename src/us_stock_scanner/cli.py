"""CLI — default: find the best trade signal automatically."""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields as dc_fields, replace as dc_replace
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from us_stock_scanner.auto_pick import run_auto_pick, run_single_symbol
from us_stock_scanner.config import (
    SignalSettings,
    criteria_from_config,
    get_all_modes,
    get_mode_settings,
    load_config,
    load_custom_modes,
    save_custom_modes,
    strategy_settings_from_config,
)
from us_stock_scanner.display import print_scan_result
from us_stock_scanner.journal import append_scan, journal_path
from us_stock_scanner.outcomes import print_outcome_report
from us_stock_scanner.presets import Preset, get_preset, list_presets
from us_stock_scanner.scanner import run_scan
from us_stock_scanner.watchlist import load_watchlist, watchlist_path

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find the best US stock trade setup (entry, targets, stop, reasons).",
    )
    parser.add_argument(
        "--symbol",
        "-s",
        metavar="TICKER",
        help="Scan one ticker only (e.g. AAPL, BRK-B)",
    )
    parser.add_argument(
        "--watchlist",
        "-w",
        action="store_true",
        help="Scan symbols from your watchlist (stored in the database)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Scan all index tickers (slower)",
    )
    parser.add_argument(
        "-u",
        "--universe",
        default="sp500",
        choices=["sp500", "nasdaq100", "watchlist"],
        help="Market index or watchlist (default: sp500)",
    )
    parser.add_argument("--watch", type=int, default=7, help="Worth-watching list size")
    parser.add_argument(
        "--expert",
        action="store_true",
        help="Expert raw screener mode (uses filters/presets for simple matches, no trade plans)",
    )
    parser.add_argument(
        "preset",
        nargs="?",
        help="Preset name to use for main long strategy (or with --expert for screener). See --list",
    )
    parser.add_argument("--list", action="store_true", help="List available presets (some carry strategy tunings for main engine)")
    parser.add_argument("-c", "--config", type=Path, help="YAML config with 'strategy:' (main) or 'filters:' (expert) sections")
    parser.add_argument("--quick", action="store_true", help="Expert: scan 50 tickers")
    parser.add_argument(
        "--mode",
        "-m",
        default=None,
        help="High-level tuning profile or custom mode name for the main long engine",
    )
    parser.add_argument("--list-modes", action="store_true", help="List all strategy modes (built-in + your custom modes)")
    parser.add_argument("--delete-mode", metavar="NAME", help="Delete a custom mode by name")
    parser.add_argument("--show-mode", metavar="NAME", help="Show the full settings for a mode (built-in or custom) as YAML")
    parser.add_argument("--outcomes", action="store_true", help="Show journal outcomes")
    parser.add_argument("--log-watch", action="store_true", help="Log runners-up to journal")
    parser.add_argument("--no-log", action="store_true", help="Skip journal")
    return parser


def _run_expert(args: argparse.Namespace) -> int:
    # Expert raw screener path (filters/criteria only). For main long engine + tunings use without --expert.
    if args.config:
        data = load_config(args.config)
        criteria = criteria_from_config(data)
        universe = data.get("universe", args.universe)
        period = data.get("period", "3mo")
        limit = 50 if args.quick else data.get("limit")
    elif args.preset:
        preset = get_preset(args.preset)
        criteria = preset.criteria
        universe = preset.universe
        period = preset.period
        limit = 50 if args.quick else preset.limit
        console.print(f"[dim]{preset.description}[/dim]")
    else:
        console.print("Expert: pass a preset (or --list for all presets) or use -c config.yaml")
        return 1

    console.print(f"[bold]Scanning[/bold] {universe}...")
    df = run_scan(universe, criteria, period=period, limit=limit)
    if df.empty:
        console.print("[yellow]No matches.[/yellow]")
    else:
        table = Table(title=f"Matches ({len(df)})")
        for col in df.columns:
            table.add_column(col)
        for _, row in df.iterrows():
            table.add_row(*(str(row[c]) for c in df.columns))
        console.print(table)
    return 0


def _print_skipped(skipped: dict[str, str], *, single: bool = False) -> None:
    if not skipped:
        return
    if single and len(skipped) == 1:
        sym, reason = next(iter(skipped.items()))
        console.print(Panel(f"[bold]{sym}[/bold]\n{reason}", title="No signal", border_style="red"))
        return
    table = Table(title="Did not pass filters")
    table.add_column("Symbol", style="cyan")
    table.add_column("Reason")
    for sym, reason in sorted(skipped.items()):
        table.add_row(sym, reason[:80])
    console.print(table)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        table = Table(title="Presets (usable with main long engine or --expert screener)")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        for p in list_presets():
            tag = " [strategy]" if getattr(p, "strategy", None) else ""
            table.add_row(p.key, (p.description or "") + tag)
        console.print(table)

        # Also show available high-level modes
        console.print("\n[bold]Available Strategy Modes[/bold] (use with --mode / -m or in config.yaml):")
        mode_table = Table()
        mode_table.add_column("Mode", style="green")
        mode_table.add_column("Description")
        mode_table.add_row("default", "Balanced relaxed (good daily all-rounder)")
        mode_table.add_row("conservative", "Strict quality, fewer but higher-conviction signals")
        mode_table.add_row("swing", "Pullback / multi-day friendly, tolerates deeper retraces")
        mode_table.add_row("aggressive", "Looser gates for more signals and early entries")
        mode_table.add_row("breakout", "Optimized for volume surges and stocks near highs")
        console.print(mode_table)
        return 0

    if args.list_modes:
        customs = load_custom_modes()
        allm = get_all_modes()
        t = Table(title="Strategy Modes (built-in + custom)")
        t.add_column("Name", style="cyan")
        t.add_column("Type")
        t.add_column("Example (chg / max_rsi / min_conf / atr_mult)")
        for n in sorted(allm.keys()):
            s = allm[n]
            typ = "custom" if n in customs else "built-in"
            ex = f"{s.min_daily_change_pct} / {s.max_rsi} / {s.min_confluence} / {s.atr_stop_multiplier}"
            t.add_row(n, typ, ex)
        console.print(t)
        console.print("\n[dim]Use --show-mode NAME to dump full settings, --delete-mode NAME to remove a custom, or manage everything (including editing all 50+ params) in the UI Modes tab.[/dim]")
        return 0

    if args.show_mode:
        name = args.show_mode
        try:
            s = get_mode_settings(name)
            import yaml as _yaml
            print(_yaml.safe_dump({name: {f.name: getattr(s, f.name) for f in __import__("dataclasses").fields(s)}}, sort_keys=False))
        except Exception as e:
            console.print(f"[red]Could not show mode '{name}': {e}[/red]")
        return 0

    if args.delete_mode:
        customs = load_custom_modes()
        if args.delete_mode in customs:
            del customs[args.delete_mode]
            save_custom_modes(customs)
            console.print(f"[green]Deleted custom mode '{args.delete_mode}'[/green]")
        else:
            console.print(f"[yellow]No custom mode named '{args.delete_mode}' (only customs can be deleted via CLI).[/yellow]")
        return 0

    if args.expert:
        return _run_expert(args)

    if args.outcomes:
        print_outcome_report()
        return 0

    # Main long-strategy path (default). Support mode / preset / config for tuning.
    settings: SignalSettings | None = None
    effective_mode = args.mode

    if args.config:
        data = load_config(args.config)
        # config can contain a top-level "mode:" + optional "strategy:" overrides
        if "mode" in data and not effective_mode:
            effective_mode = data["mode"]
        settings = strategy_settings_from_config(data)
        if effective_mode:
            base = get_mode_settings(effective_mode)
            # merge config strategy on top of mode
            overrides = {
                f.name: getattr(settings, f.name)
                for f in dc_fields(SignalSettings)
                if getattr(settings, f.name) != getattr(base, f.name)
            }
            settings = dc_replace(base, **overrides) if overrides else base
        console.print(f"[dim]Loaded settings (mode={effective_mode or 'default'}) from config[/dim]")
    elif args.preset:
        try:
            p: Preset = get_preset(args.preset)
            if getattr(p, "strategy", None):
                settings = p.strategy
                console.print(f"[dim]Preset '{p.key}' strategy: {p.description}[/dim]")
            else:
                console.print(f"[dim]Preset '{p.key}' (screener-oriented, no strategy override) — using default long settings[/dim]")
        except Exception as e:
            console.print(f"[yellow]Unknown preset {args.preset!r}: {e}. Using defaults.[/yellow]")

    # If a mode was explicitly requested (or came from config) and we don't have settings yet, use it
    if effective_mode and not settings:
        settings = get_mode_settings(effective_mode)
        console.print(f"[dim]Using scan mode: {effective_mode}[/dim]")
    elif effective_mode and settings:
        # mode + preset/config: mode as base, then overlay
        base = get_mode_settings(effective_mode)
        overrides = {
            f.name: getattr(settings, f.name)
            for f in dc_fields(SignalSettings)
            if getattr(settings, f.name) != getattr(base, f.name)
        }
        settings = dc_replace(base, **overrides) if overrides else base
        console.print(f"[dim]Using scan mode: {effective_mode} (with overrides)[/dim]")

    use_watchlist = args.watchlist or args.universe == "watchlist"
    label = args.universe

    try:
        if args.symbol:
            sym = args.symbol.strip().upper()
            console.print(f"[bold]Analyzing {sym}[/bold]…\n")
            result = run_single_symbol(sym, settings=settings)
            label = sym
        elif use_watchlist:
            tickers = load_watchlist()
            console.print(f"[bold]Scanning watchlist[/bold] ({len(tickers)} symbols)…\n")
            result = run_auto_pick("watchlist", watch_count=args.watch, settings=settings)
            label = "watchlist"
        else:
            limit = None if args.full else 150
            console.print(
                f"[bold]Scanning {args.universe.upper()}[/bold]"
                + (" (full)" if args.full else " (top 150)")
                + "…\n"
            )
            result = run_auto_pick(args.universe, limit=limit, watch_count=args.watch, settings=settings)
    except Exception as e:
        console.print(f"[red]Scan failed: {e}[/red]")
        return 1

    if args.symbol and not result.top_picks:
        _print_skipped(result.skipped, single=True)
        return 0

    print_scan_result(result)
    _print_skipped(result.skipped)

    if not args.no_log and result.top_picks:
        append_scan(result, universe=label, include_watchlist=args.log_watch)
        console.print("\n[dim]Journal updated in database[/dim]")

    if use_watchlist:
        console.print(f"[dim]Watchlist stored in database (see Modes tab to manage)[/dim]")

    return 0


if __name__ == "__main__":
    sys.exit(main())