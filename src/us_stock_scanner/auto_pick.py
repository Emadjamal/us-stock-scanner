"""Automatic scan: find the best trading setups."""

from __future__ import annotations

from dataclasses import dataclass, field

from us_stock_scanner.data import fetch_history
from us_stock_scanner.market_regime import MarketRegime, analyze_market_regime
from dataclasses import fields as dc_fields, replace as dc_replace

from us_stock_scanner.config import (
    SignalSettings,
    default_signal_settings,
    get_mode_settings,
)
from us_stock_scanner.signal_engine import (
    WATCH_MIN_SCORE,
    analyze_symbol_v2,
    diagnose_rejection,
    find_all_signals_v2,
)
from us_stock_scanner.trade_signal import TradeSignal
from us_stock_scanner.universe import resolve_universe
from us_stock_scanner.watchlist import load_watchlist

TOP_PICKS_COUNT = 3
WORTH_WATCHING_COUNT = 7


@dataclass
class ScanResult:
    top_picks: list[TradeSignal] = field(default_factory=list)
    worth_watching: list[TradeSignal] = field(default_factory=list)
    market: MarketRegime | None = None
    scan_mode: str = "universe"
    scan_label: str = "sp500"
    skipped: dict[str, str] = field(default_factory=dict)
    signals_found: int = 0  # number that passed analyze_symbol_v2 (all gates + confluence + min score + R:R) before top_picks/watch ranking


def _market_context() -> tuple[MarketRegime | None, object]:
    spy_frames = fetch_history(["SPY"], period="1y", batch_size=1)
    spy_df = spy_frames.get("SPY")
    market = analyze_market_regime(spy_df) if spy_df is not None else None
    return market, spy_df


def _rank_signals(
    all_signals: list[TradeSignal],
    *,
    top_picks: int,
    watch_count: int,
) -> tuple[list[TradeSignal], list[TradeSignal]]:
    ranked = sorted(
        all_signals,
        key=lambda s: ({"A": 3, "B": 2, "C": 1}.get(s.grade, 0), s.score),
        reverse=True,
    )
    picks = ranked[:top_picks]
    pick_symbols = {p.symbol for p in picks}
    watching = [
        s for s in ranked if s.symbol not in pick_symbols and s.score >= WATCH_MIN_SCORE
    ][:watch_count]
    return picks, watching


def run_scan(
    *,
    tickers: list[str] | None = None,
    universe: str = "sp500",
    period: str = "1y",
    interval: str = "1d",
    limit: int | None = 150,
    top_picks: int = TOP_PICKS_COUNT,
    watch_count: int = WORTH_WATCHING_COUNT,
    scan_mode: str = "universe",
    scan_label: str | None = None,
    settings: SignalSettings | None = None,
    mode: str | None = None,
) -> ScanResult:
    """Scan a universe, custom ticker list, or watchlist file.

    You can pass either:
      - settings=... (full control)
      - mode="aggressive" / "swing" etc. (high-level profile)
      - both (mode provides base, settings can further override specific fields)
    """
    if tickers is None:
        if universe == "watchlist":
            tickers = load_watchlist()
            scan_mode = "watchlist"
            scan_label = scan_label or "watchlist"
        else:
            tickers = resolve_universe(universe)
            if limit is not None:
                tickers = tickers[:limit]
            scan_label = scan_label or universe

    if not tickers:
        return ScanResult(scan_mode=scan_mode, scan_label=scan_label or "empty", signals_found=0)

    # Resolve settings: mode first, then explicit settings as overrides
    if mode:
        base = get_mode_settings(mode)
        if settings:
            overrides = {
                f.name: getattr(settings, f.name)
                for f in dc_fields(SignalSettings)
                if getattr(settings, f.name) != getattr(base, f.name)
            }
            settings = dc_replace(base, **overrides) if overrides else base
        else:
            settings = base
    else:
        settings = settings or default_signal_settings()

    market, spy_df = _market_context()
    history = fetch_history(tickers, period=period, interval=interval, batch_size=50)
    skipped: dict[str, str] = {}

    for symbol in tickers:
        if symbol not in history:
            skipped[symbol] = "No market data from Yahoo Finance"
        elif analyze_symbol_v2(symbol, history[symbol], market, spy_df, settings=settings, interval=interval) is None:
            skipped[symbol] = diagnose_rejection(symbol, history[symbol], market, spy_df, settings=settings, interval=interval)

    all_signals = find_all_signals_v2(history, market, spy_df, settings=settings, interval=interval)
    picks, watching = _rank_signals(all_signals, top_picks=top_picks, watch_count=watch_count)

    return ScanResult(
        top_picks=picks,
        worth_watching=watching,
        market=market,
        scan_mode=scan_mode,
        scan_label=scan_label or scan_mode,
        skipped=skipped,
        signals_found=len(all_signals),
    )


def run_auto_pick(
    universe: str = "sp500",
    *,
    period: str = "1y",  # lookback length (like scan_period)
    interval: str = "1d",  # bar timeframe (1d, 1wk, etc.) — now configurable like scan_period
    limit: int | None = 150,
    top_picks: int = TOP_PICKS_COUNT,
    watch_count: int = WORTH_WATCHING_COUNT,
    settings: SignalSettings | None = None,
    mode: str | None = None,
) -> ScanResult:
    """Scan S&P 500 or Nasdaq-100 (backward compatible)."""
    if universe == "watchlist":
        return run_scan(
            tickers=load_watchlist(),
            period=period,
            top_picks=top_picks,
            watch_count=watch_count,
            scan_mode="watchlist",
            settings=settings,
            mode=mode,
        )
    return run_scan(
        universe=universe,
        period=period,
        limit=limit,
        top_picks=top_picks,
        watch_count=watch_count,
        scan_mode="universe",
        scan_label=universe,
        settings=settings,
        mode=mode,
    )


def run_single_symbol(symbol: str, *, period: str = "1y", interval: str = "1d", settings: SignalSettings | None = None, mode: str | None = None) -> ScanResult:
    """Analyze one ticker."""
    sym = symbol.strip().upper().replace(".", "-")
    return run_scan(
        tickers=[sym],
        period=period,
        interval=interval,
        top_picks=1,
        watch_count=0,
        scan_mode="single",
        scan_label=sym,
        settings=settings,
        mode=mode,
    )