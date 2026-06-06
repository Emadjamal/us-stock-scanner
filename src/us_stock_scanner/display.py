"""Pretty output for trade signals."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from us_stock_scanner.auto_pick import ScanResult
from us_stock_scanner.trade_signal import TradeSignal

console = Console()


def _print_market_context(market) -> None:
    if market is None:
        return
    style = "green" if market.bullish else "yellow"
    console.print(
        Panel(
            f"{market.summary}\n[dim]SPY today {market.spy_change_pct:+.1f}%[/dim]",
            title="[bold]Market regime[/bold]",
            border_style=style,
        )
    )
    console.print()


def _signal_panel(sig: TradeSignal, rank: int) -> Panel:
    border = "green" if sig.grade == "A" else "blue" if sig.grade == "B" else "cyan"
    setup = f" · {sig.setup_type}" if sig.setup_type else ""
    title = f"#{rank}  {sig.symbol}  ·  Grade {sig.grade}{setup}  ·  {sig.score}/100"

    if sig.entry < sig.entry_market and sig.entry_market > 0:
        entry_lines = [
            f"[bold]Entry (limit)[/bold]  ${sig.entry:.2f}  [dim]buy pullback[/dim]",
            f"[bold]Last price[/bold]    ${sig.entry_market:.2f}  [dim]market now[/dim]",
        ]
    else:
        entry_lines = [f"[bold]Entry[/bold]       ${sig.entry:.2f}"]

    lines = [
        *entry_lines,
        f"[bold red]Stop loss[/bold red]   ${sig.stop_loss:.2f}  [dim](-{sig.risk_pct:.1f}% risk)[/dim]",
        f"[bold green]Target 1[/bold green]    ${sig.target1:.2f}  [dim](+{sig.reward1_pct:.1f}% · {sig.risk_reward_t1:.1f}:1)[/dim]",
        f"[bold green]Target 2[/bold green]    ${sig.target2:.2f}  [dim](+{sig.reward2_pct:.1f}%)[/dim]",
        "",
        "[bold]Why[/bold]",
    ]
    for i, reason in enumerate(sig.reasons[:-1], 1):
        lines.append(f"  {i}. {reason}")
    lines.append(f"[dim]{sig.reasons[-1]}[/dim]" if sig.reasons else "")
    rs = f" · RS vs SPY {sig.rs_vs_spy:+.1f}%" if sig.rs_vs_spy else ""
    lines.append(
        f"\n[dim]+{sig.change_pct:.1f}% today · RSI {sig.rsi} · Vol {sig.rvol}× · ADX {sig.adx}{rs}[/dim]"
    )
    return Panel("\n".join(lines), title=title, border_style=border, padding=(0, 1))


def print_scan_result(result: ScanResult) -> None:
    if not result.top_picks:
        console.print(
            Panel(
                "[yellow]No strong setups found.[/yellow]\n"
                "Try again later or run with [bold]--full[/bold] to scan more stocks.",
                title="Result",
                border_style="yellow",
            )
        )
        return

    _print_market_context(result.market)

    console.print(
        Panel(
            "[bold]Top 3[/bold] — must pass 4/6 confluence pillars, min risk/reward, and quality gates.",
            title="[bold white]TOP 3 PICKS (LONG)[/bold white]",
            border_style="white",
            padding=(0, 1),
        )
    )
    console.print()

    for rank, sig in enumerate(result.top_picks[:3], 1):
        console.print(_signal_panel(sig, rank))
        console.print()

    if result.worth_watching:
        table = Table(
            title="Worth watching — runners-up (shorter list, review before trading)",
            show_header=True,
            header_style="bold",
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Symbol", style="cyan")
        table.add_column("Grade", justify="center")
        table.add_column("Score", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("Stop", justify="right")
        table.add_column("T1", justify="right")
        table.add_column("T2", justify="right")
        table.add_column("Today", justify="right")
        table.add_column("Why (summary)", max_width=40)

        for i, s in enumerate(result.worth_watching, 1):
            summary = s.reasons[0] if s.reasons else ""
            table.add_row(
                str(i),
                s.symbol,
                s.grade,
                f"{s.score:.0f}",
                f"${s.entry:.2f}",
                f"${s.stop_loss:.2f}",
                f"${s.target1:.2f}",
                f"${s.target2:.2f}",
                f"{s.change_pct:+.1f}%",
                summary[:40] + ("…" if len(summary) > 40 else ""),
            )
        console.print(table)

    console.print(
        "\n[dim]Not financial advice. Confirm charts and risk before trading.[/dim]"
    )


# Backward-compatible alias
def print_best_signal(signals: list[TradeSignal]) -> None:
    print_scan_result(
        ScanResult(top_picks=signals[:3], worth_watching=signals[3:])
    )