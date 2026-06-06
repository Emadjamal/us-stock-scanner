"""Core signal logic — gates, confluence, setup type, quality grade."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from us_stock_scanner.indicators import (
    adx,
    atr,
    bollinger_bands,
    bearish_macd_divergence,
    bearish_rsi_divergence,
    macd,
    moving_average,
    pct_from_rolling_high,
    relative_strength_vs,
    relative_volume,
    rsi,
)
from us_stock_scanner.config import (
    SignalSettings,
    default_signal_settings,
    strategy_settings_from_config,
)
from us_stock_scanner.market_regime import MarketRegime
from us_stock_scanner.timeframes import weekly_trend_bullish
from us_stock_scanner.trade_signal import TradeSignal, _strength, _trade_levels

# Back-compat exports (used by auto_pick, old code). New code should use SignalSettings.
# These reflect the relaxed defaults.
WATCH_MIN_SCORE = default_signal_settings().watch_min_score


@dataclass
class ConfluencePillar:
    name: str
    passed: bool
    detail: str


@dataclass
class SignalAnalysis:
    pillars: list[ConfluencePillar]
    warnings: list[str] = field(default_factory=list)
    setup_type: str = ""
    grade: str = "C"
    raw_score: float = 0.0
    final_score: float = 0.0
    confluence_count: int = 0


def _ma_slope(series: pd.Series, period: int = 20, lookback: int = 5) -> float:
    ma = moving_average(series, period, "sma")
    if len(ma.dropna()) < lookback + 1:
        return 0.0
    tail = ma.dropna().tail(lookback + 1)
    return float((tail.iloc[-1] - tail.iloc[0]) / tail.iloc[0] * 100)


def _higher_highs(high: pd.Series, lookback: int = 20) -> bool:
    segment = high.tail(lookback)
    if len(segment) < lookback:
        return False
    mid = lookback // 2
    first_half_max = float(segment.iloc[:mid].max())
    second_half_max = float(segment.iloc[mid:].max())
    return second_half_max >= first_half_max * 0.998


def _macd_hist_rising(hist: pd.Series, bars: int = 3) -> bool:
    tail = hist.dropna().tail(bars)
    if len(tail) < bars:
        return False
    return float(tail.iloc[-1]) > float(tail.iloc[0])


def _extended_above_ma(close: float, ma50: float) -> float:
    if ma50 <= 0:
        return 0.0
    return ((close - ma50) / ma50) * 100


def _pullback_entry(
    *,
    setup_type: str,
    last: float,
    ma20: float,
    extension_pct: float,
) -> tuple[float, float]:
    """
    Returns (suggested_limit_entry, market_close).
    Pullback limit sits between 20-MA and last price when extended or in pullback setup.
    """
    market = round(last, 2)
    if setup_type == "pullback" or extension_pct > 4:
        limit = max(ma20 * 1.003, (ma20 + last) / 2)
        if limit >= last:
            limit = last * 0.992
        return round(limit, 2), market
    return market, market


def _classify_setup(
    *,
    near_high: bool,
    change_pct: float,
    above_ma20: bool,
    pullback_to_ma: bool,
    macd_cross: bool,
) -> str:
    if near_high and change_pct >= 1.5 and macd_cross:
        return "breakout"
    if pullback_to_ma and above_ma20 and change_pct >= 0:
        return "pullback"
    if change_pct >= 2:
        return "momentum"
    return "continuation"


def _grade(confluence: int, final_score: float, warnings: list[str], settings: SignalSettings | None = None) -> str:
    settings = settings or default_signal_settings()
    if warnings and len(warnings) >= 2:
        return "C"
    if confluence >= settings.grade_a_min_confluence and final_score >= settings.grade_a_min_score:
        return "A"
    if confluence >= settings.grade_b_min_confluence and final_score >= settings.grade_b_min_score:
        return "B"
    if confluence >= settings.min_confluence and final_score >= settings.min_score_default:
        return "C"
    return "F"


def _align_spy_length(stock_df: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
    """Trim SPY to dates overlapping the stock series."""
    if spy_df is None or spy_df.empty:
        return spy_df
    if not isinstance(stock_df.index, pd.DatetimeIndex):
        stock_df = stock_df.copy()
        stock_df.index = pd.to_datetime(stock_df.index)
    spy = spy_df.copy()
    if not isinstance(spy.index, pd.DatetimeIndex):
        spy.index = pd.to_datetime(spy.index)
    return spy.loc[spy.index.intersection(stock_df.index)]


def analyze_symbol_v2(
    symbol: str,
    df: pd.DataFrame,
    market: MarketRegime | None = None,
    spy_df: pd.DataFrame | None = None,
    settings: SignalSettings | None = None,
) -> TradeSignal | None:
    if len(df) < 60:
        return None

    settings = settings or default_signal_settings()

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]
    volume = df["Volume"]

    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    last_open = float(open_.iloc[-1])
    if prev <= 0 or last < settings.min_price:
        return None

    change_pct = ((last - prev) / prev) * 100
    avg_vol = float(volume.tail(20).mean())
    if avg_vol < settings.min_avg_volume:
        return None

    rsi_series = rsi(close)
    last_rsi = float(rsi_series.iloc[-1])
    rvol_s = relative_volume(volume, 20)
    last_rvol = float(rvol_s.iloc[-1]) if pd.notna(rvol_s.iloc[-1]) else 0.0
    lookback = min(252, len(close) - 1)
    high_pct_s = pct_from_rolling_high(close, lookback)
    last_high_pct = float(high_pct_s.iloc[-1]) if pd.notna(high_pct_s.iloc[-1]) else -50.0

    macd_df = macd(close)
    hist = macd_df["hist"]
    last_macd_hist = float(hist.iloc[-1])
    macd_line = macd_df["macd"]
    signal_line = macd_df["signal"]
    macd_bull_cross = (
        float(macd_line.iloc[-2]) <= float(signal_line.iloc[-2])
        and float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])
    )
    hist_rising = _macd_hist_rising(hist, 3)

    atr_s = atr(high, low, close, 14)
    last_atr = float(atr_s.iloc[-1]) if pd.notna(atr_s.iloc[-1]) else 0.0
    if last_atr <= 0:
        return None

    adx_s = adx(high, low, close, 14)
    last_adx = float(adx_s.iloc[-1]) if pd.notna(adx_s.iloc[-1]) else 0.0

    ma20 = moving_average(close, 20, "sma")
    ma50 = moving_average(close, 50, "sma")
    last_ma20 = float(ma20.iloc[-1])
    last_ma50 = float(ma50.iloc[-1])
    above_ma20 = last > last_ma20
    above_ma50 = last > last_ma50
    ma20_slope = _ma_slope(close, 20, 5)
    extension_pct = _extended_above_ma(last, last_ma50)

    bb = bollinger_bands(close)
    last_bb_pct = float(bb["pct_b"].iloc[-1]) if pd.notna(bb["pct_b"].iloc[-1]) else 50.0

    gap = ((last_open - prev) / prev) * 100 if prev else 0.0
    near_high = last_high_pct >= settings.near_high_for_breakout
    pullback_to_ma = above_ma50 and abs(last - last_ma20) / last_ma20 < 0.025

    # --- Required: weekly trend ---
    weekly_ok, weekly_detail = weekly_trend_bullish(df)
    if not weekly_ok:
        return None

    # --- Required: relative strength vs SPY ---
    rs_vs_spy = 0.0
    if spy_df is not None and not spy_df.empty:
        aligned = _align_spy_length(df, spy_df)
        if len(aligned) >= 6:
            rs_vs_spy = relative_strength_vs(close, aligned["Close"], days=5)
    if rs_vs_spy < settings.min_rs_vs_spy:
        return None

    # --- Hard rejects (now from settings; relaxed defaults for change/RSI) ---
    if change_pct < settings.min_daily_change_pct:
        return None
    if last_rsi > settings.max_rsi:
        return None
    if change_pct > settings.max_single_day_change_pct:
        return None
    if extension_pct > settings.max_extension_pct:
        return None
    if change_pct > settings.blowoff_change_pct and last_rsi > settings.blowoff_rsi:
        return None
    if not hist_rising and last_macd_hist < 0 and not macd_bull_cross:
        return None
    if last < last_ma50 * settings.min_ma50_mult:
        return None
    if bearish_rsi_divergence(close, rsi_series):
        return None
    if bearish_macd_divergence(close, hist):
        return None

    warnings: list[str] = []
    if gap > 4 and change_pct < 1:
        warnings.append("Large gap up but weak close — possible fade")
    if extension_pct > 10:
        warnings.append(f"Extended {extension_pct:.0f}% above 50-MA — prefer limit entry")

    pillars: list[ConfluencePillar] = []

    trend_ok = above_ma20 and above_ma50 and ma20_slope > 0
    pillars.append(
        ConfluencePillar(
            "Trend",
            trend_ok,
            f"Above 20/50 MA, 20-MA slope {ma20_slope:+.1f}%"
            if trend_ok
            else "Trend weak or MAs flat/falling",
        )
    )

    momentum_ok = (last_macd_hist > 0 and hist_rising) or macd_bull_cross
    pillars.append(
        ConfluencePillar(
            "Momentum",
            momentum_ok,
            "MACD improving or fresh bullish cross"
            if momentum_ok
            else "MACD not supporting long",
        )
    )

    structure_ok = _higher_highs(high, 20)
    pillars.append(
        ConfluencePillar(
            "Structure",
            structure_ok,
            "Recent higher highs"
            if structure_ok
            else "No clear higher-high structure",
        )
    )

    volume_ok = last_rvol >= settings.min_rvol_for_volume
    pillars.append(
        ConfluencePillar(
            "Volume",
            volume_ok,
            f"RVOL {last_rvol:.1f}×"
            if volume_ok
            else f"Volume light ({last_rvol:.1f}×)",
        )
    )

    not_extended = (
        last_rsi <= settings.not_ext_max_rsi
        and extension_pct <= settings.not_ext_max_extension
        and last_bb_pct <= settings.not_ext_max_bb_pct
    )
    pillars.append(
        ConfluencePillar(
            "Not overextended",
            not_extended,
            f"RSI {last_rsi:.0f}, {extension_pct:.0f}% above 50-MA"
            if not_extended
            else "Stretched — late entry risk",
        )
    )

    breakout_ok = near_high or (change_pct >= settings.breakout_min_change and last_rvol >= settings.breakout_min_rvol)
    pillars.append(
        ConfluencePillar(
            "Breakout / demand",
            breakout_ok,
            f"{last_high_pct:+.1f}% from high, today {change_pct:+.1f}%"
            if breakout_ok
            else "Not near highs / weak demand",
        )
    )

    confluence = sum(1 for p in pillars if p.passed)
    if confluence < settings.min_confluence:
        return None

    setup_type = _classify_setup(
        near_high=near_high,
        change_pct=change_pct,
        above_ma20=above_ma20,
        pullback_to_ma=pullback_to_ma,
        macd_cross=macd_bull_cross,
    )
    entry_limit, entry_market = _pullback_entry(
        setup_type=setup_type,
        last=last,
        ma20=last_ma20,
        extension_pct=extension_pct,
    )

    raw = 0.0
    reasons: list[str] = []

    reasons.append(weekly_detail)
    reasons.append(f"Outperforming SPY by {rs_vs_spy:+.1f}% (5-day)")

    raw += min(settings.max_confluence_bonus, confluence * settings.bonus_confluence_per)
    reasons.append(f"Confluence: {confluence}/6 pillars aligned")

    if trend_ok:
        raw += settings.bonus_trend
        reasons.append(pillars[0].detail)
    if momentum_ok:
        raw += settings.bonus_momentum
        if macd_bull_cross:
            reasons.append("MACD bullish crossover today")
        else:
            reasons.append("MACD histogram rising — momentum building")
    if structure_ok:
        raw += settings.bonus_structure
        reasons.append("Higher-high structure on daily chart")
    if volume_ok:
        raw += settings.bonus_volume
        reasons.append(pillars[3].detail)
    if near_high:
        raw += settings.bonus_near_high
        reasons.append(f"Near 52-week high ({last_high_pct:+.1f}%) — leadership")
    elif last_high_pct >= -10:
        raw += settings.bonus_near_high_partial

    if 1 <= change_pct <= 6:
        raw += settings.bonus_controlled_momentum
        reasons.append(f"Controlled momentum (+{change_pct:.1f}% today)")
    elif 0 <= change_pct < 1:
        raw += settings.bonus_weak_momentum

    if last_adx >= settings.adx_min_for_bonus:
        raw += settings.bonus_adx
        reasons.append(f"ADX {last_adx:.0f} — trend strength")
    if settings.rsi_sweet_low <= last_rsi <= settings.rsi_sweet_high:
        raw += settings.bonus_rsi_sweet
        reasons.append(f"RSI {last_rsi:.0f} in ideal momentum zone")

    if rs_vs_spy >= 2.0:
        raw += settings.bonus_rs_strong
    elif rs_vs_spy >= 1.0:
        raw += settings.bonus_rs_moderate

    penalty = 0.0
    for _ in warnings:
        penalty += settings.penalty_per_warning
    if not market or not market.bullish:
        penalty += settings.penalty_weak_market
        warnings.append("Market regime weak — SPY not fully supportive")
    if last_rsi > settings.penalty_high_rsi_threshold:
        penalty += settings.penalty_high_rsi
    if extension_pct > settings.penalty_extension_threshold:
        penalty += settings.penalty_extension

    final_score = max(0, raw - penalty)
    grade = _grade(confluence, final_score, warnings, settings)

    min_required = settings.min_score_default
    if market and market.bullish:
        min_required = settings.min_score_strong_market
    elif market:
        min_required = settings.min_score_weak_market

    if grade == "F" or final_score < min_required:
        return None

    reasons.insert(0, f"Setup: {setup_type} · Grade {grade}")

    recent_low = float(low.tail(10).min())
    stop, t1, t2, risk_pct = _trade_levels(entry_limit, last_atr, recent_low, settings=settings)
    rr = (t1 - entry_limit) / (entry_limit - stop) if entry_limit > stop else 0
    if rr < settings.min_risk_reward:
        return None

    reward1_pct = ((t1 - entry_limit) / entry_limit) * 100
    reward2_pct = ((t2 - entry_limit) / entry_limit) * 100

    if entry_limit < entry_market:
        reasons.append(
            f"Entry: limit ${entry_limit:.2f} (pullback toward 20-MA) · last ${entry_market:.2f}"
        )
    else:
        reasons.append(f"Entry: ${entry_limit:.2f} (at/near last close)")

    reasons.append(
        f"Plan: risk {risk_pct:.1f}% · T1 +{reward1_pct:.1f}% ({rr:.1f}:1) · T2 +{reward2_pct:.1f}%"
    )
    if warnings:
        reasons.append("Caution: " + "; ".join(warnings))

    return TradeSignal(
        symbol=symbol,
        score=round(final_score, 1),
        strength=_strength(final_score),
        entry=entry_limit,
        entry_market=entry_market,
        stop_loss=stop,
        target1=t1,
        target2=t2,
        risk_pct=risk_pct,
        reward1_pct=round(reward1_pct, 2),
        reward2_pct=round(reward2_pct, 2),
        reasons=reasons,
        change_pct=round(change_pct, 2),
        rsi=round(last_rsi, 1),
        rvol=round(last_rvol, 2),
        adx=round(last_adx, 1),
        grade=grade,
        setup_type=setup_type,
        rs_vs_spy=round(rs_vs_spy, 2),
    )


def diagnose_rejection(
    symbol: str,
    df: pd.DataFrame,
    market: MarketRegime | None = None,
    spy_df: pd.DataFrame | None = None,
    settings: SignalSettings | None = None,
) -> str:
    """Why a symbol did not produce a long signal (for single-ticker / watchlist UI)."""
    if len(df) < 60:
        return "Not enough price history (need ~60 trading days)"

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]
    volume = df["Volume"]
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    settings = settings or default_signal_settings()

    if prev <= 0 or last < settings.min_price:
        return "Invalid or missing price data"

    change_pct = ((last - prev) / prev) * 100
    if float(volume.tail(20).mean()) < settings.min_avg_volume:
        return "Average volume too low (illiquid)"

    rsi_series = rsi(close)
    last_rsi = float(rsi_series.iloc[-1])
    hist = macd(close)["hist"]
    last_macd_hist = float(hist.iloc[-1])
    macd_line = macd(close)["macd"]
    signal_line = macd(close)["signal"]
    macd_bull_cross = (
        float(macd_line.iloc[-2]) <= float(signal_line.iloc[-2])
        and float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])
    )
    hist_rising = _macd_hist_rising(hist, 3)
    ma50 = float(moving_average(close, 50, "sma").iloc[-1])
    extension_pct = _extended_above_ma(last, ma50)

    weekly_ok, weekly_detail = weekly_trend_bullish(df)
    if not weekly_ok:
        return weekly_detail

    rs_vs_spy = 0.0
    if spy_df is not None and not spy_df.empty:
        aligned = _align_spy_length(df, spy_df)
        if len(aligned) >= 6:
            rs_vs_spy = relative_strength_vs(close, aligned["Close"], days=5)
    if rs_vs_spy < settings.min_rs_vs_spy:
        return f"Underperforming SPY ({rs_vs_spy:+.1f}% vs +{settings.min_rs_vs_spy}% required over 5 days)"

    if change_pct < settings.min_daily_change_pct:
        return f"Down {change_pct:.1f}% today — no long bias"
    if last_rsi > settings.max_rsi:
        return f"RSI {last_rsi:.0f} — overbought"
    if extension_pct > settings.max_extension_pct:
        return f"Extended {extension_pct:.0f}% above 50-day MA (max {settings.max_extension_pct:.0f}%)"
    if change_pct > settings.blowoff_change_pct and last_rsi > settings.blowoff_rsi:
        return "Blow-off move (big up day + high RSI)"
    if not hist_rising and last_macd_hist < 0 and not macd_bull_cross:
        return "MACD not bullish / not improving"
    if last < ma50 * settings.min_ma50_mult:
        return "Below 50-day moving average"
    if bearish_rsi_divergence(close, rsi_series):
        return "Bearish RSI divergence at highs"
    if bearish_macd_divergence(close, hist):
        return "Bearish MACD divergence at highs"

    sig = analyze_symbol_v2(symbol, df, market, spy_df, settings=settings)
    if sig:
        return "Passed — should appear as a signal (unexpected if you see this)"

    return "Confluence too weak (need 4 of 6 pillars) or score below minimum"


def find_all_signals_v2(
    history: dict[str, pd.DataFrame],
    market: MarketRegime | None = None,
    spy_df: pd.DataFrame | None = None,
    settings: SignalSettings | None = None,
) -> list[TradeSignal]:
    candidates: list[TradeSignal] = []
    for symbol, df in history.items():
        sig = analyze_symbol_v2(symbol, df, market, spy_df, settings=settings)
        if sig:
            candidates.append(sig)
    candidates.sort(key=lambda s: s.score, reverse=True)
    return candidates