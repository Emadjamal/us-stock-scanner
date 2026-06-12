"""
US Stock Scanner — web UI (Streamlit).
Run: streamlit run app.py  or  start_ui.bat
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Bridge Streamlit secrets (Cloud dashboard or .streamlit/secrets.toml for local tests)
# into os.environ *before* any us_stock_scanner imports. This ensures storage.py's
# os.getenv("TURSO_*") / is_using_turso() see the values on Streamlit Cloud.
import os
try:
    if hasattr(st, "secrets"):
        # Accessing st.secrets can raise if no secrets.toml at all; guard heavily.
        try:
            secrets_dict = dict(st.secrets)
        except Exception:
            secrets_dict = {}
        for _k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "LIBSQL_URL", "LIBSQL_AUTH_TOKEN"):
            if _k not in os.environ and _k in secrets_dict:
                os.environ[_k] = str(secrets_dict[_k])
except Exception:
    pass

# Make the package importable whether running locally (pip install -e .)
# or on Streamlit Cloud / other hosts where only the repo is checked out.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from us_stock_scanner.auto_pick import run_auto_pick, run_single_symbol
from us_stock_scanner.config import (
    SCAN_MODE_CHOICES,
    SignalSettings,
    default_signal_settings,
    get_all_modes,
    get_mode_settings,
    load_config,
    load_custom_modes,
    save_custom_modes,
    strategy_settings_from_config,
)
from dataclasses import fields as dc_fields, replace as dc_replace
from us_stock_scanner.journal import append_scan, journal_path, load_journal
from us_stock_scanner.outcomes import update_outcomes
from us_stock_scanner.storage import get_active_trades, monitor_active_trades, close_trade, approve_trade, is_using_turso
from us_stock_scanner.presets import get_preset
from us_stock_scanner.watchlist import (
    add_symbols,
    load_watchlist,
    remove_symbols,
    save_watchlist,
    watchlist_path,
)

st.set_page_config(
    page_title="US Stock Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Init tunable strategy params in session (for sidebar widgets + preset buttons)
for _k, _v in [
    ("tune_min_chg", -2.5),
    ("tune_max_rsi", 78),
    ("tune_min_rs", 0.5),
    ("tune_max_ext", 15.0),
    ("tune_min_rvol", 1.15),
    ("tune_min_conf", 4),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

if "strategy_mode" not in st.session_state:
    st.session_state["strategy_mode"] = "default"

# Apply any pending strategy mode change requested from buttons or the Modes tab.
# This must run *before* any widget with key="strategy_mode" (or the tune_ sliders)
# is instantiated in this script run.
if "_set_strategy_mode" in st.session_state:
    st.session_state["strategy_mode"] = st.session_state.pop("_set_strategy_mode")

# Apply pending tune slider values (used by "load config" from inside the expander,
# after the sliders have already been created in the current run).
if "_pending_tune" in st.session_state:
    for k, v in st.session_state.pop("_pending_tune").items():
        st.session_state[k] = v

# Load customs early so the sidebar can reference them (e.g. to sync scan_period from a selected mode)
customs = load_custom_modes()

st.markdown(
    """
<style>
    .block-container { padding-top: 1.5rem; max-width: 1200px; }
    .pick-card {
        background: linear-gradient(145deg, #1a2332 0%, #121820 100%);
        border: 1px solid #2d3a4f;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        color: #e2e8f0;
    }
    .grade-a { color: #3dd68c; font-weight: 700; }
    .grade-b { color: #5eb3ff; font-weight: 700; }
    .grade-c { color: #aab4c3; font-weight: 700; }
    .ticker {
        font-size: 1.4rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .pick-secondary {
        color: #cbd5e1;
    }
    .market-ok {
        background: #123d24;
        color: #d1fae5;
        border: 1px solid #166534;
        border-radius: 8px;
        padding: 0.85rem 1rem;
        line-height: 1.35;
    }
    .market-warn {
        background: #4a3510;
        color: #fef3c7;
        border: 1px solid #854d0e;
        border-radius: 8px;
        padding: 0.85rem 1rem;
        line-height: 1.35;
    }
    .market-ok b, .market-warn b {
        color: #ffffff;
        font-size: 0.95rem;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""",
    unsafe_allow_html=True,
)


def _grade_class(grade: str) -> str:
    return {"A": "grade-a", "B": "grade-b"}.get(grade, "grade-c")


def _get_reason_hint(reason: str) -> str:
    """Very brief one-sentence explanation for common reasons so users understand the jargon."""
    r = reason.lower()
    if "rvol" in r and "×" in reason:
        return "Relative Volume: today's volume vs 20-day average. 1.0× = normal. ≥1.4× = unusually strong participation / interest."
    if "volume light" in r:
        return "Today's volume is below average — the move has less conviction from buyers."
    if "outperforming spy" in r:
        return "The stock is beating the S&P 500 over the last 5 days (positive relative strength)."
    if "confluence" in r:
        return "Number of the 6 key pillars (Trend, Momentum, Structure, Volume, Not-overextended, Breakout/Demand) that are all firing together."
    if "macd" in r:
        return "MACD is a momentum oscillator. Bullish cross or rising histogram = upward momentum is building or confirming."
    if "higher-high structure" in r or "structure" in r:
        return "The stock keeps making new highs on the daily chart — buyers remain in control."
    if "52-week high" in r or "near high" in r:
        return "Price is close to its highest point in the past year. These leadership names often keep outperforming."
    if "controlled momentum" in r:
        return "A moderate green day (not parabolic). Sustainable strength rather than an exhaustion move."
    if "adx" in r:
        return "ADX measures the strength of the trend (not its direction). Higher = clearer, stronger trend in place."
    if "rsi" in r and "ideal" in r:
        return "RSI in the 48-65 zone is often the 'sweet spot' for healthy momentum stocks — not yet overbought."
    if "setup:" in r or "grade" in r:
        return "Pattern type + overall quality grade (A/B/C) based on confluence + final score."
    if "entry:" in r:
        return "Suggested buy price. A limit slightly below current price often gets you a better entry on a tiny pullback."
    if "plan:" in r or "risk" in r or "t1" in r or "t2" in r:
        return "Risk = % distance to your stop. Targets are set at 1.5× and 2.5× that risk (R-multiples). We only show ideas with decent reward-to-risk."
    if "caution" in r or "warning" in r:
        return "The setup isn't perfect (e.g. already extended, weak overall market, big gap). Size smaller or use a tighter stop."
    if "weekly" in r:
        return "Higher-timeframe (weekly) trend is bullish. We only look for long trades when the bigger picture is up."
    return ""


def _render_pick(sig, rank: int) -> None:
    gc = _grade_class(sig.grade)
    setup = f" · {sig.setup_type}" if sig.setup_type else ""
    st.markdown(
        f'<div class="pick-card">'
        f'<span class="ticker">#{rank} {sig.symbol}</span> '
        f'<span class="{gc}">Grade {sig.grade}</span>'
        f'<span class="pick-secondary">{setup} · Score {sig.score}/100</span>'
        f"</div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    if sig.entry < sig.entry_market and sig.entry_market > 0:
        c1.metric("Entry (limit)", f"${sig.entry:.2f}")
        c2.metric("Last price", f"${sig.entry_market:.2f}")
    else:
        c1.metric("Entry", f"${sig.entry:.2f}")
        c2.metric("Today", f"{sig.change_pct:+.1f}%")
    c3.metric("Stop loss", f"${sig.stop_loss:.2f}", delta=f"-{sig.risk_pct:.1f}% risk", delta_color="inverse")
    c4.metric("Target 1", f"${sig.target1:.2f}", delta=f"+{sig.reward1_pct:.1f}%")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Target 2", f"${sig.target2:.2f}", delta=f"+{sig.reward2_pct:.1f}%")
    t2.metric("R:R → T1", f"{sig.risk_reward_t1:.1f}:1")
    t3.metric("RS vs SPY", f"{sig.rs_vs_spy:+.1f}%")
    t4.metric("RSI / Vol", f"{sig.rsi:.0f} · {sig.rvol:.1f}×")

    with st.expander("Why this pick", expanded=rank == 1):
        for reason in sig.reasons:
            st.markdown(f"- {reason}")
            hint = _get_reason_hint(reason)
            if hint:
                st.caption(f"💡 {hint}")

    # Candlestick chart with EMAs/SMAs, golden cross visibility, volume, and trade levels (visual reasons for the pick)
    with st.expander("📈 Candlestick + Key Patterns & Levels", expanded=False):
        try:
            import plotly.graph_objects as go  # type: ignore[import-not-found]
            from plotly.subplots import make_subplots  # type: ignore[import-not-found]

            # Use the shared (cached) fetch_history so the 6mo chart benefits from the
            # same cache as scans. This improves perceived perf when viewing multiple picks
            # and keeps data consistent with what the engine saw.
            from us_stock_scanner.data import fetch_history
            h = fetch_history([sig.symbol], period="6mo", interval="1d")
            hist = h.get(sig.symbol, pd.DataFrame())
            if hist.empty or len(hist) < 30:
                st.caption("Not enough price history for a meaningful chart.")
            else:
                # Compute indicators used by the engine (SMA20/50) + EMAs as user requested
                hist['SMA20'] = hist['Close'].rolling(window=20).mean()
                hist['SMA50'] = hist['Close'].rolling(window=50).mean()
                hist['EMA20'] = hist['Close'].ewm(span=20, adjust=False).mean()
                hist['EMA50'] = hist['Close'].ewm(span=50, adjust=False).mean()

                # Create subplots: candles on top, volume on bottom
                fig = make_subplots(
                    rows=2, cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.03,
                    row_heights=[0.75, 0.25],
                    subplot_titles=(f"{sig.symbol} - Candles + EMAs/SMAs (Trend & Structure)", "Volume")
                )

                # Candlestick - make them clearly visible with fill
                fig.add_trace(
                    go.Candlestick(
                        x=hist.index,
                        open=hist['Open'],
                        high=hist['High'],
                        low=hist['Low'],
                        close=hist['Close'],
                        name='Candles',
                        increasing_line_color='#00C853',
                        decreasing_line_color='#FF1744',
                        increasing_fillcolor='#00C853',
                        decreasing_fillcolor='#FF1744',
                        increasing_line_width=1.2,
                        decreasing_line_width=1.2
                    ),
                    row=1, col=1
                )

                # EMAs (as user requested) + SMAs (as used by the engine)
                fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA20'], line=dict(color='#2196f3', width=1.5), name='EMA20'), row=1, col=1)
                fig.add_trace(go.Scatter(x=hist.index, y=hist['EMA50'], line=dict(color='#ff9800', width=1.5), name='EMA50'), row=1, col=1)
                fig.add_trace(go.Scatter(x=hist.index, y=hist['SMA20'], line=dict(color='#3f51b5', width=1, dash='dot'), name='SMA20 (engine)'), row=1, col=1)
                fig.add_trace(go.Scatter(x=hist.index, y=hist['SMA50'], line=dict(color='#f44336', width=1, dash='dot'), name='SMA50 (engine)'), row=1, col=1)

                # Trade levels as horizontal lines (directly from the pick logic)
                levels = [
                    (sig.entry, 'Entry', '#4caf50'),
                    (sig.stop_loss, 'Stop Loss', '#f44336'),
                    (sig.target1, 'Target 1', '#2196f3'),
                    (sig.target2, 'Target 2', '#9c27b0'),
                ]
                for price, name, color in levels:
                    fig.add_hline(
                        y=price,
                        line_dash="dash",
                        line_color=color,
                        line_width=1.5,
                        row=1, col=1,
                        annotation_text=name,
                        annotation_position="top right",
                        annotation_font_size=10
                    )

                # Volume bars
                colors = ['#26a69a' if close >= open else '#ef5350' for close, open in zip(hist['Close'], hist['Open'])]
                fig.add_trace(
                    go.Bar(
                        x=hist.index,
                        y=hist['Volume'],
                        marker_color=colors,
                        name='Volume',
                        showlegend=False
                    ),
                    row=2, col=1
                )

                # Simple golden cross annotation (EMA20 crossing above EMA50 recently)
                try:
                    ema20 = hist['EMA20'].dropna()
                    ema50 = hist['EMA50'].dropna()
                    if len(ema20) > 5 and len(ema50) > 5:
                        last_cross = (ema20.iloc[-1] > ema50.iloc[-1]) and (ema20.iloc[-5] <= ema50.iloc[-5])
                        if last_cross:
                            fig.add_annotation(
                                x=ema20.index[-1],
                                y=ema20.iloc[-1],
                                text="Golden Cross (EMA20 > EMA50)",
                                showarrow=True,
                                arrowhead=2,
                                ax=0,
                                ay=-40,
                                font=dict(color="#2196f3", size=11),
                                row=1, col=1
                            )
                except Exception:
                    pass

                # Additional pattern visuals in the candlestick expander (from roadmap).
                # These highlight the exact reasons the engine picked the ticker:
                # higher-high structure, the swing low used for stop placement, and setup classification.
                try:
                    # Recent higher highs (supports the "Structure" pillar + "higher-high structure" reason)
                    highs = hist['High']
                    hh = []
                    for i in range(3, len(highs) - 3):
                        if (highs.iloc[i] > highs.iloc[i-1] > highs.iloc[i-2] and
                            highs.iloc[i] > highs.iloc[i+1] > highs.iloc[i+2]):
                            hh.append((highs.index[i], highs.iloc[i]))
                    for d, price in hh[-4:]:
                        fig.add_trace(
                            go.Scatter(
                                x=[d], y=[price * 1.015],
                                mode="markers+text",
                                marker=dict(symbol="triangle-up", size=7, color="#22c55e"),
                                text=["HH"], textposition="top center",
                                textfont=dict(size=8, color="#22c55e"),
                                showlegend=False,
                            ),
                            row=1, col=1
                        )

                    # Approximate recent swing low (engine uses a similar recent low.tail(10).min() for the stop)
                    recent_low_idx = hist['Low'].tail(15).idxmin()
                    recent_low_price = hist.loc[recent_low_idx, 'Low']
                    fig.add_trace(
                        go.Scatter(
                            x=[recent_low_idx], y=[recent_low_price * 0.985],
                            mode="markers+text",
                            marker=dict(symbol="triangle-down", size=8, color="#ef4444"),
                            text=["Swing Low"], textposition="bottom center",
                            textfont=dict(size=8, color="#ef4444"),
                            showlegend=False,
                        ),
                        row=1, col=1
                    )

                    # Setup type context (what the engine saw: pullback / breakout / momentum / continuation)
                    setup = getattr(sig, "setup_type", "continuation") or "continuation"
                    setup_text = {
                        "pullback": "Pullback setup",
                        "breakout": "Breakout / near highs",
                        "momentum": "Momentum day",
                        "continuation": "Trend continuation",
                    }.get(setup, setup.title())
                    fig.add_annotation(
                        x=hist.index[-1],
                        y=hist['Close'].iloc[-1] * 1.025,
                        text=setup_text,
                        showarrow=False,
                        font=dict(size=9, color="#64748b"),
                        row=1, col=1
                    )
                except Exception:
                    pass

                # Layout - make candles prominent
                fig.update_layout(
                    height=580,
                    xaxis_rangeslider_visible=False,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
                    margin=dict(l=30, r=10, t=30, b=10),
                    hovermode="x unified",
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)'
                )
                fig.update_xaxes(showgrid=True, gridwidth=0.5, gridcolor='rgba(128,128,128,0.2)')
                fig.update_yaxes(title_text="Price", row=1, col=1, showgrid=True, gridwidth=0.5, gridcolor='rgba(128,128,128,0.2)')
                fig.update_yaxes(title_text="Volume", row=2, col=1, showgrid=True, gridwidth=0.5, gridcolor='rgba(128,128,128,0.2)')

                st.plotly_chart(fig, use_container_width=True)

                # Visual context for the pick reasons
                st.caption(
                    f"**Visual reasons for this pick:** "
                    f"Candles show real price action & structure (higher highs etc.). "
                    f"EMA20 (blue) / EMA50 (orange) + SMA20/SMA50 (dotted) show trend, momentum & golden cross. "
                    f"Colored volume bars support the RVOL reason. "
                    f"Dashed lines = exact Entry / Stop / T1 / T2. "
                    f"Green HH markers = higher-high structure. Red triangle = recent swing low (stop basis). "
                    f"Small text = engine's setup classification (pullback/breakout/etc)."
                )
        except Exception as e:
            st.caption(f"Advanced chart unavailable (install plotly if missing: pip install plotly). Simple view: {e}")


def _do_scan(
    mode: str,
    universe: str,
    single_symbol: str,
    full: bool,
    watch_count: int,
    log_watch: bool,
    save_journal: bool,
    settings: SignalSettings | None = None,
    period: str = "1y",
    interval: str = "1d",
    top_picks: int = 3,
) -> None:
    label = universe
    with st.spinner("Scanning… please wait."):
        if mode == "Single ticker":
            sym = single_symbol.strip().upper()
            result = run_single_symbol(sym, settings=settings, period=period, interval=interval)
            label = sym
        elif mode == "My watchlist":
            result = run_auto_pick("watchlist", top_picks=top_picks, watch_count=watch_count, settings=settings, period=period, interval=interval)
            label = "watchlist"
        else:
            limit = None if full else 150
            result = run_auto_pick(universe, limit=limit, top_picks=top_picks, watch_count=watch_count, settings=settings, period=period, interval=interval)
            label = universe
    st.session_state["scan_result"] = result
    st.session_state["scan_label"] = label

    # Record the params/settings actually used for this scan (for the result header + parity debugging)
    st.session_state["last_scan_params"] = st.session_state.get("last_scan_params") or {"mode": "?", "period": period, "interval": interval, "top_picks": top_picks}
    if settings is not None:
        st.session_state["last_scan_settings"] = st.session_state.get("last_scan_settings") or {
            "min_chg": round(settings.min_daily_change_pct, 2),
            "max_rsi": settings.max_rsi,
            "min_rvol": settings.min_rvol_for_volume,
            "min_conf": settings.min_confluence,
            "min_score": settings.min_score_default,
            "max_ext": settings.max_extension_pct,
            "min_rs": settings.min_rs_vs_spy,
        }

    if save_journal and result.top_picks:
        path = append_scan(result, universe=label, include_watchlist=log_watch)
        st.session_state["last_journal"] = str(path)


def _journal_stats(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No journal entries yet. Run a scan first.")
        return
    status = df["outcome_status"].fillna("").astype(str)
    evaluated = df[status.ne("")]
    if evaluated.empty:
        st.warning("Click **Refresh outcomes** to update results.")
        return
    total = len(evaluated)
    wins = (evaluated["outcome_status"].isin(["hit_t1", "hit_t2"])).sum()
    stops = (evaluated["outcome_status"] == "stopped").sum()
    not_filled = (evaluated["outcome_status"] == "not_filled").sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Signals logged", len(df))
    c2.metric("Win rate (T1+T2)", f"{100 * wins / total:.0f}%" if total else "—")
    c3.metric("Stopped", int(stops))
    c4.metric("Limit not filled", int(not_filled))


# --- Sidebar ---
with st.sidebar:
    st.title("US Stock Scanner")
    st.divider()
    scan_mode = st.radio(
        "Scan",
        ["Market index", "My watchlist", "Single ticker"],
        index=0,
    )
    universe = "sp500"
    single_sym = "AAPL"
    if scan_mode == "Market index":
        universe = st.selectbox("Index", ["sp500", "nasdaq100"], format_func=lambda x: x.upper())
        full_scan = st.checkbox("Full index scan (slower)", value=False)
    elif scan_mode == "Single ticker":
        single_sym = st.text_input("Ticker symbol", value="AAPL").strip().upper()
        full_scan = False
    else:
        wl = load_watchlist()
        st.caption(f"Watchlist: **{len(wl)}** symbols")
        full_scan = False

    top_picks = st.slider("Top picks (max)", 1, 10, 3, key="top_picks_slider")
    watch_count = st.slider("Worth watching (max)", 0, 15, 7, key="watch_count_slider")
    log_watch = st.checkbox("Log runners-up to journal", value=False)
    save_journal = st.checkbox("Save top picks to journal", value=False)
    st.divider()

    # --- High-level Scan Mode (tunes the engine presets) ---
    # Dynamically include user custom modes (loaded from the database)
    dynamic_modes = list(get_all_modes().keys())
    display_options = [m for m in dynamic_modes if m in SCAN_MODE_CHOICES] + \
                      [m for m in dynamic_modes if m not in SCAN_MODE_CHOICES] + ["custom"]

    # Robust current value
    current_mode_val = st.session_state.get("strategy_mode", "default")
    if current_mode_val not in display_options:
        current_mode_val = "default"

    strategy_mode = st.selectbox(
        "Strategy Mode",
        options=display_options,
        index=display_options.index(current_mode_val),
        format_func=lambda x: {
            "default": "Default (balanced)",
            "conservative": "Conservative (strict quality)",
            "swing": "Swing (pullback friendly)",
            "aggressive": "Aggressive (more signals)",
            "breakout": "Breakout (leaders & volume)",
            "custom": "Custom (manual tweaks)",
        }.get(x, f"Custom: {x}"),
        key="strategy_mode",   # use this as the canonical key
        help="High-level tuning profile (built-in or your saved custom modes). Changes the core gates etc. automatically.",
    )

    # Always sync the 6 visible sidebar sliders to the selected *named* mode's values
    # (so they reflect the mode). If the user later tweaks any slider, the on_change
    # will switch to "custom" and the engine will use the live slider values.
    # Note: we set session_state *before* creating the keyed widgets below.
    # The widgets use only `key=` (no `value=`) so Streamlit reads exclusively from session_state
    # and avoids the "created with a default value but also had its value set via the Session State API" warning.
    if strategy_mode != "custom":
        mode_s = get_mode_settings(strategy_mode)
        st.session_state["tune_min_chg"] = mode_s.min_daily_change_pct
        st.session_state["tune_max_rsi"] = int(mode_s.max_rsi)
        st.session_state["tune_min_rs"] = mode_s.min_rs_vs_spy
        st.session_state["tune_max_ext"] = int(mode_s.max_extension_pct)
        st.session_state["tune_min_rvol"] = mode_s.min_rvol_for_volume
        st.session_state["tune_min_conf"] = mode_s.min_confluence

    # Sync scan period and timeframe from the selected named mode (if saved with the mode)
    if 'customs' in dir() and strategy_mode != "custom" and strategy_mode in customs:
        cdata = customs[strategy_mode]
        if isinstance(cdata, dict):
            mode_p = cdata.get("scan_period", "1y")
            st.session_state["scan_period"] = mode_p
            mode_tf = cdata.get("timeframe", "1d")
            st.session_state["timeframe"] = mode_tf

    # Scan period - now configurable in sidebar (and savable per mode in Modes tab)
    available_periods = ["3mo", "6mo", "1y", "2y", "5y"]
    current_p = st.session_state.get("scan_period", "1y")
    if current_p not in available_periods:
        current_p = "1y"
    scan_period = st.selectbox(
        "Scan Period (daily data lookback)",
        options=available_periods,
        index=available_periods.index(current_p),
        key="scan_period",
        help="How much historical daily data the scanner analyzes for patterns, indicators, and structure. Longer = more context for trends/weekly filter but slower scans. When you select a custom mode that has a saved period, it auto-applies here."
    )

    # Timeframe (bar size) — configurable just like scan_period
    timeframe_options = ["1d", "1wk", "1mo"]
    current_tf = st.session_state.get("timeframe", "1d")
    if current_tf not in timeframe_options:
        current_tf = "1d"
    timeframe = st.selectbox(
        "Timeframe (bar size)",
        options=timeframe_options,
        index=timeframe_options.index(current_tf),
        key="timeframe",
        help="Bar interval for the scan: daily (1d, default & recommended), weekly (1wk), or monthly (1mo). Affects indicators and the weekly trend filter. Non-daily is experimental. Saved per custom mode just like Scan Period."
    )
    if timeframe != "1d":
        st.caption("⚠️ Non-daily timeframe: the weekly trend gate is skipped (see Help). Use 1d for normal scans.")

    # --- Tuning for main strategy (unified, not hard-coded) ---
    with st.expander("⚙️ Fine-tune current mode (advanced)", expanded=False):
        st.caption("Relaxed defaults vs original strict. Changes apply on next Run scan.")
        c1, c2 = st.columns(2)
        with c1:
            def _to_custom():
                st.session_state["_set_strategy_mode"] = "custom"

            min_chg = st.number_input(
                "Min daily chg % (lower = more pullbacks)",
                min_value=-10.0,
                max_value=2.0,
                step=0.5,
                key="tune_min_chg",
                help="Original was -0.5 (very strict). -2.5 allows normal red days.",
                on_change=_to_custom,
            )
            max_rsi = st.slider(
                "Max RSI (higher tolerates momentum)",
                min_value=60,
                max_value=90,
                key="tune_max_rsi",
                help="Original 75 hard cap often killed breakouts.",
                on_change=_to_custom,
            )
            min_rs = st.number_input(
                "Min 5d RS vs SPY %",
                min_value=0.0,
                max_value=5.0,
                step=0.1,
                key="tune_min_rs",
                on_change=_to_custom,
            )
        with c2:
            max_ext = st.slider(
                "Max ext % above 50MA",
                min_value=5,
                max_value=25,
                key="tune_max_ext",
                on_change=_to_custom,
            )
            min_rvol = st.slider(
                "Min RVOL (volume pillar)",
                min_value=1.0,
                max_value=2.5,
                step=0.05,
                key="tune_min_rvol",
                on_change=_to_custom,
            )
            min_conf = st.slider(
                "Min confluence (of 6 pillars)",
                min_value=3,
                max_value=6,
                key="tune_min_conf",
                on_change=_to_custom,
            )

        colb1, colb2, colb3 = st.columns(3)
        with colb1:
            if st.button("Apply Default", width="stretch"):
                st.session_state["_set_strategy_mode"] = "default"
                st.rerun()
        with colb2:
            if st.button("Apply Breakout", width="stretch"):
                st.session_state["_set_strategy_mode"] = "breakout"
                st.rerun()
        with colb3:
            if st.button("Apply Aggressive", width="stretch"):
                st.session_state["_set_strategy_mode"] = "aggressive"
                st.rerun()

        if st.button("Try load config.yaml strategy", width="stretch"):
            try:
                cfg = load_config(Path("config.yaml"))
                s = strategy_settings_from_config(cfg)
                # Use pending mechanism for both mode and the tune sliders,
                # because this code runs after the sidebar widgets have been created.
                st.session_state["_set_strategy_mode"] = "custom"
                st.session_state["_pending_tune"] = {
                    "tune_min_chg": s.min_daily_change_pct,
                    "tune_max_rsi": int(s.max_rsi),
                    "tune_min_rs": s.min_rs_vs_spy,
                    "tune_max_ext": int(s.max_extension_pct),
                    "tune_min_rvol": s.min_rvol_for_volume,
                    "tune_min_conf": s.min_confluence,
                }
                # Support top-level "period" / "timeframe" (or "interval") in config.yaml
                if "period" in cfg:
                    st.session_state["scan_period"] = cfg["period"]
                if "timeframe" in cfg or "interval" in cfg:
                    st.session_state["timeframe"] = cfg.get("timeframe") or cfg.get("interval")
                st.success("Loaded from config.yaml (set to Custom)")
                st.rerun()
            except Exception as ex:
                st.warning(f"Could not load: {ex}")

        st.divider()
        new_mode_name = st.text_input("Save current tweaks as custom mode", value="my-new-mode", key="save_mode_name")
        if st.button("Save as custom mode", width="stretch") and new_mode_name.strip():
            customs = load_custom_modes()
            # Build full settings from current tune sliders + other defaults
            current_tune = SignalSettings(
                min_daily_change_pct=float(st.session_state["tune_min_chg"]),
                max_rsi=float(st.session_state["tune_max_rsi"]),
                min_rs_vs_spy=float(st.session_state["tune_min_rs"]),
                max_extension_pct=float(st.session_state["tune_max_ext"]),
                min_rvol_for_volume=float(st.session_state["tune_min_rvol"]),
                min_confluence=int(st.session_state["tune_min_conf"]),
            )
            period = st.session_state.get("scan_period", "1y")
            tf = st.session_state.get("timeframe", "1d")
            customs[new_mode_name.strip()] = {"settings": current_tune, "scan_period": period, "timeframe": tf}
            save_custom_modes(customs)
            st.session_state["_set_strategy_mode"] = new_mode_name.strip()
            st.success(f"Saved as '{new_mode_name.strip()}' and activated.")
            st.rerun()

    # Build effective settings:
    # - If a named mode is active → use the full tuned SignalSettings for that mode (richer than just the 6 sliders)
    # - If "custom" → build from the fine-tune sliders (user overrides)
    current_mode = st.session_state.get("strategy_mode", "default")
    if current_mode != "custom":
        tune_settings = get_mode_settings(current_mode)
    else:
        tune_settings = SignalSettings(
            min_daily_change_pct=float(st.session_state["tune_min_chg"]),
            max_rsi=float(st.session_state["tune_max_rsi"]),
            min_rs_vs_spy=float(st.session_state["tune_min_rs"]),
            max_extension_pct=float(st.session_state["tune_max_ext"]),
            min_rvol_for_volume=float(st.session_state["tune_min_rvol"]),
            min_confluence=int(st.session_state["tune_min_conf"]),
            # all other fields (trade plan, scoring bonuses, penalties, etc.) come from defaults
        )
    st.session_state["_last_tune_settings"] = tune_settings

    if st.button("Run scan", type="primary", width="stretch"):
        period = st.session_state.get("scan_period", "1y")
        tf = st.session_state.get("timeframe", "1d")
        tp = st.session_state.get("top_picks_slider", 3)
        current_mode = st.session_state.get("strategy_mode", "default")
        st.session_state["last_scan_params"] = {"mode": current_mode, "period": period, "interval": tf, "top_picks": tp}
        st.session_state["last_scan_settings"] = {
            "min_chg": round(tune_settings.min_daily_change_pct, 2),
            "max_rsi": tune_settings.max_rsi,
            "min_rvol": tune_settings.min_rvol_for_volume,
            "min_conf": tune_settings.min_confluence,
            "min_score": tune_settings.min_score_default,
            "max_ext": tune_settings.max_extension_pct,
            "min_rs": tune_settings.min_rs_vs_spy,
        }
        _do_scan(scan_mode, universe, single_sym, full_scan, watch_count, log_watch, save_journal, settings=tune_settings, period=period, interval=tf, top_picks=tp)
        st.rerun()
    if st.button("Update outcomes", width="stretch"):
        with st.spinner("Updating…"):
            update_outcomes(only_pending=True)
        st.rerun()
    st.caption("This re-evaluates pending + currently open journal entries (updates outcome_date and days_held for open trades). Closed trades keep their historical outcome timestamp.")

# --- Main tabs ---
st.header("Find your best trade setup")

tab_scan, tab_watchlist, tab_modes, tab_journal, tab_help = st.tabs(
    ["Scan", "Watchlist", "Modes", "Journal", "Help"]
)

with tab_scan:
    result = st.session_state.get("scan_result")
    if result is None:
        st.info("Choose scan type in the sidebar, then click **Run scan**.")
    else:
        st.caption(f"Scan: **{result.scan_label}** ({result.scan_mode})")
        lp = st.session_state.get("last_scan_params") or {}
        db_label = "Turso (remote)" if is_using_turso() else "local SQLite"
        p = lp.get("period", "1y")
        tf = lp.get("interval", "1d")
        md = lp.get("mode", st.session_state.get("strategy_mode", "default"))
        st.caption(f"Effective: mode=`{md}` · period=`{p}` · timeframe=`{tf}` · db=`{db_label}`")

        # Show the actual gate values used for this scan (critical for local vs cloud parity)
        gs = st.session_state.get("last_scan_settings") or {}
        if gs:
            st.caption(
                f"Gates used: daily_chg ≥ {gs.get('min_chg', '—')}% · RSI ≤ {gs.get('max_rsi', '—')} "
                f"· RVOL ≥ {gs.get('min_rvol', '—')} · conf ≥ {gs.get('min_conf', '—')} "
                f"· min_score {gs.get('min_score', '—')} · ext ≤ {gs.get('max_ext', '—')}% · RS ≥ {gs.get('min_rs', '—')}%"
            )

        # Signals found (how many cleared the full engine before picking top N)
        sigs = getattr(result, "signals_found", 0)
        attempted = getattr(result, "attempted", 0)
        fetched = getattr(result, "fetched", 0)
        mkt = getattr(result, "market_summary", "")

        if sigs or result.top_picks or result.worth_watching or attempted:
            st.caption(
                f"Signals found (passed all gates + confluence + score + R:R): **{sigs}**  |  "
                f"Top picks: {len(result.top_picks)}  |  Worth watching: {len(result.worth_watching)}"
            )
            if attempted:
                st.caption(f"Tickers: attempted={attempted} · fetched with data={fetched} · market={mkt or '—'}")
        if result.market:
            m = result.market
            css = "market-ok" if m.bullish else "market-warn"
            st.markdown(
                f'<div class="{css}"><b>Market regime</b><br>{m.summary}<br>'
                f'SPY today {m.spy_change_pct:+.1f}%</div>',
                unsafe_allow_html=True,
            )
            st.write("")

        if result.scan_mode == "single" and not result.top_picks:
            sym = result.scan_label
            reason = result.skipped.get(sym, "Does not meet long setup criteria.")
            st.error(f"**{sym}** — no long signal")
            st.markdown(reason)
        elif not result.top_picks:
            st.warning("No setups passed filters.")
        else:
            n = st.session_state.get("top_picks_slider", 3)
            title = "Top pick" if result.scan_mode == "single" else f"Top {min(n, len(result.top_picks))} picks"
            st.subheader(title)
            for rank, sig in enumerate(result.top_picks[:n], 1):
                _render_pick(sig, rank)
                # Approve button for active trade monitoring (new feature)
                btn_key = f"approve_pick_{rank}_{sig.symbol}_{result.scan_label}"
                if st.button(f"✅ Approve #{rank} {sig.symbol} (start monitoring)", key=btn_key, width="stretch"):
                    try:
                        mode = st.session_state.get("strategy_mode", "default")
                        tid = approve_trade(
                            sig,
                            mode=mode,
                            notes=f"Approved from UI scan: {result.scan_label} ({result.scan_mode}, mode={mode})"
                        )
                        st.success(
                            f"✅ Approved {sig.symbol} as active trade #{tid}. "
                            "Go to **Journal** tab → expand 'Close Active Trade(s)' to manually close it, "
                            "or use the monitor button for updates/recommendations."
                        )
                        # Optional: rerun to refresh any state, but keep user on scan tab
                    except Exception as e:
                        st.error(f"Approve failed: {e}")
        if result.worth_watching:
            st.subheader("Worth watching")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Symbol": s.symbol,
                            "Grade": s.grade,
                            "Score": s.score,
                            "Entry": s.entry,
                            "Stop": s.stop_loss,
                            "T1": s.target1,
                            "Today %": s.change_pct,
                        }
                        for s in result.worth_watching
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

        if result.skipped:
            # Quick categorized breakdown of why things were rejected (helps compare local vs cloud)
            reasons = list(result.skipped.values())
            no_data = sum(1 for r in reasons if "No market data" in r or "not enough" in r.lower())
            weekly = sum(1 for r in reasons if "weekly" in r.lower() or "Higher-TF" in r or "Higher timeframe" in r)
            rs_gate = sum(1 for r in reasons if "SPY" in r or "Underperforming" in r or "relative strength" in r.lower())
            hard = sum(1 for r in reasons if any(x in r.lower() for x in ["down ", "overbought", "extended", "below 50", "macd not", "blow-off", "gap"]))
            confluence = sum(1 for r in reasons if "confluence" in r.lower() or "too weak" in r.lower())
            score = sum(1 for r in reasons if "score" in r.lower() or "grade" in r.lower() or "minimum" in r.lower())
            other = len(reasons) - (no_data + weekly + rs_gate + hard + confluence + score)
            st.caption(
                f"Rejection breakdown (of {len(result.skipped)}): "
                f"no-data/insufficient={no_data} · weekly/H-TF={weekly} · RS vs SPY={rs_gate} · "
                f"hard gates (chg/rsi/ext/macd)={hard} · confluence={confluence} · score/RR={score} · other={max(0, other)}"
            )
            with st.expander(f"Did not pass ({len(result.skipped)} symbols)", expanded=(result.scan_mode == "watchlist" or len(result.top_picks) == 0)):
                st.dataframe(
                    pd.DataFrame(
                        [{"Symbol": k, "Reason": v} for k, v in sorted(result.skipped.items())]
                    ),
                    width="stretch",
                    hide_index=True,
                )

        # === Rich copy-paste friendly diagnostics (P0 parity debugging) ===
        # Always shown after a scan so user can easily report exact conditions
        with st.expander("📋 Scan Diagnostics (copy this when reporting local vs cloud differences)", expanded=False):
            lp = st.session_state.get("last_scan_params") or {}
            gs = st.session_state.get("last_scan_settings") or {}
            db_label = "Turso (remote)" if is_using_turso() else "local SQLite"

            attempted = getattr(result, 'attempted', 0)
            fetched = getattr(result, 'fetched', 0)
            sigs = getattr(result, 'signals_found', 0)
            mkt = getattr(result, 'market_summary', '')

            # Fallback for results saved before we added attempted/fetched/market_summary fields
            if attempted == 0 and (len(result.skipped) or sigs):
                attempted = len(result.skipped) + sigs
            if fetched == 0 and attempted > 0:
                fetched = attempted   # best guess when old result

            if not mkt or mkt == "— (market info not captured in this result)":
                # Provide a friendlier message; the root cause (missing SPY for RS/market)
                # is now mitigated by fetching SPY together with the main tickers.
                mkt = getattr(result, "market_summary", "") or "— (SPY context not available for this result)"

            diag_lines = []
            diag_lines.append(f"Mode: {lp.get('mode', 'unknown')}")
            diag_lines.append(f"Period: {lp.get('period', '1y')} | Timeframe: {lp.get('interval', '1d')} | TopPicks: {lp.get('top_picks', 3)}")
            diag_lines.append(f"DB: {db_label}")
            diag_lines.append(f"Attempted: {attempted} | Fetched: {fetched}")
            diag_lines.append(f"Signals found: {sigs} | Top picks: {len(result.top_picks)} | Worth watching: {len(result.worth_watching)}")
            diag_lines.append(f"Market: {mkt}")
            if gs:
                diag_lines.append(f"Gates: min_chg={gs.get('min_chg')} | max_rsi={gs.get('max_rsi')} | min_rvol={gs.get('min_rvol')} | min_conf={gs.get('min_conf')} | min_score={gs.get('min_score')}")
            diag_lines.append(f"Skipped: {len(result.skipped)}")

            diag_text = "\n".join(diag_lines)
            st.code(diag_text, language="text")

            if result.skipped:
                # Show top rejection reasons for quick comparison
                from collections import Counter
                top_reasons = Counter(result.skipped.values()).most_common(5)
                st.markdown("**Top rejection reasons:**")
                for reason, count in top_reasons:
                    st.caption(f"- ({count}x) {reason[:90]}{'...' if len(reason) > 90 else ''}")

        if st.session_state.get("last_journal"):
            st.success(f"Journal saved: `{st.session_state['last_journal']}`")

with tab_watchlist:
    st.subheader("Manage watchlist")
    st.caption(f"Stored in: `{watchlist_path()}` (SQLite backed)")

    symbols = load_watchlist()
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.write("**Current symbols**")
        if symbols:
            selected = st.multiselect("Select to remove", symbols, label_visibility="collapsed")
        else:
            st.info("Watchlist is empty.")
            selected = []
    with col_r:
        st.write("**Add symbols**")
        add_input = st.text_input("e.g. AAPL, MSFT, NVDA", label_visibility="collapsed")
        if st.button("Add", width="stretch") and add_input:
            parts = [p.strip() for p in add_input.replace(",", " ").split()]
            add_symbols(parts)
            st.rerun()
        if st.button("Remove selected", width="stretch") and selected:
            remove_symbols(selected)
            st.rerun()

    if symbols:
        st.dataframe(pd.DataFrame({"Symbol": symbols}), width="stretch", hide_index=True)

    st.divider()
    st.write("**Bulk edit** (one symbol per line)")
    bulk = st.text_area("Symbols", value="\n".join(symbols), height=200, label_visibility="collapsed")
    if st.button("Save watchlist", type="primary"):
        lines = [ln.strip() for ln in bulk.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        save_watchlist(lines)
        st.success("Watchlist saved.")
        st.rerun()

    if st.button("Scan my watchlist now", width="stretch"):
        wc = st.session_state.get("watch_count_slider", 7)
        # Use the same effective settings as the main Run scan button would
        current_mode = st.session_state.get("strategy_mode", "default")
        if current_mode != "custom":
            ts = get_mode_settings(current_mode)
        else:
            ts = st.session_state.get("_last_tune_settings") or default_signal_settings()
        with st.spinner("Scanning watchlist…"):
            period = st.session_state.get("scan_period", "1y")
            tf = st.session_state.get("timeframe", "1d")
            tp = st.session_state.get("top_picks_slider", 3)
            st.session_state["last_scan_params"] = {"mode": current_mode, "period": period, "interval": tf, "top_picks": tp}
            st.session_state["last_scan_settings"] = {
                "min_chg": round(ts.min_daily_change_pct, 2),
                "max_rsi": ts.max_rsi,
                "min_rvol": ts.min_rvol_for_volume,
                "min_conf": ts.min_confluence,
                "min_score": ts.min_score_default,
                "max_ext": ts.max_extension_pct,
                "min_rs": ts.min_rs_vs_spy,
            }
            result = run_auto_pick("watchlist", top_picks=tp, watch_count=wc, settings=ts, period=period, interval=tf)
        st.session_state["scan_result"] = result
        st.session_state["scan_label"] = "watchlist"
        st.rerun()


with tab_modes:
    st.subheader("Manage Custom Strategy Modes")
    st.caption(
        "Create, edit, and delete your own tuning profiles (or override built-ins). "
        "They will appear in the **Strategy Mode** selector in the sidebar (like the Watchlist). "
        "All 55+ parameters from the engine are editable here."
    )

    customs = load_custom_modes()
    all_modes = get_all_modes()

    # --- List existing (built-in + custom) ---
    st.markdown("**Available modes** (built-ins are read-only; customs can be edited/deleted)")
    if all_modes:
        mode_list = sorted(all_modes.keys())
        st.dataframe(
            pd.DataFrame({
                "Mode": mode_list,
                "Type": ["custom" if m in customs else "built-in" for m in mode_list]
            }),
            width="stretch", hide_index=True
        )

    # Delete only customs
    if customs:
        to_delete = st.multiselect("Select custom mode(s) to delete", list(customs.keys()), key="modes_delete_select")
        if st.button("Delete selected custom mode(s)", width="stretch") and to_delete:
            for name in to_delete:
                customs.pop(name, None)
            save_custom_modes(customs)
            if st.session_state.get("strategy_mode") in to_delete:
                st.session_state["_set_strategy_mode"] = "default"
            st.success("Deleted.")
            st.rerun()

    st.divider()

    # --- Create / Edit form (now supports editing built-ins by saving override) ---
    st.markdown("**Edit mode parameters or create new**")

    # Allow selecting any mode (built-in or custom) to base the editor on
    built_in_names = list(SCAN_MODE_CHOICES)
    custom_names = [n for n in customs if n not in built_in_names]
    edit_options = ["(create new)"] + built_in_names + custom_names

    edit_choice = st.selectbox(
        "Mode to base editor on (changing this reloads all parameter values below)",
        options=edit_options,
        key="modes_edit_choice",
    )

    # When the mode selector changes, clean any stale editor widget state from the *previous* mode.
    # Keys for normal modes contain the mode name; for "(create new)" they contain "new_from_XXX".
    prev = st.session_state.get("_last_modes_edit_choice")
    if prev != edit_choice:
        for k in list(st.session_state.keys()):
            if not isinstance(k, str) or not k.startswith("modes_full_"):
                continue
            if edit_choice == "(create new)":
                # switching into create-new: keep only current new_from_ keys (cleaned per-base below)
                if not k.startswith("modes_full_new_from_"):
                    del st.session_state[k]
            else:
                if edit_choice not in k:
                    del st.session_state[k]
        st.session_state["_last_modes_edit_choice"] = edit_choice

    if edit_choice == "(create new)":
        mode_name = st.text_input("New custom mode name", value="my-new-mode", key="new_mode_name")
        base_for_new = st.selectbox("Start from (copy parameters from)", options=built_in_names, index=0, key="modes_base")
        current_s = get_mode_settings(base_for_new)

        # When the "Start from" base changes, clean stale editor widgets for previous bases.
        # New key_prefix will be "modes_full_new_from_{base_for_new}", so widgets get fresh keys + correct value=.
        prev_base = st.session_state.get("_last_modes_base_for_new")
        if prev_base != base_for_new:
            for k in list(st.session_state.keys()):
                if isinstance(k, str) and k.startswith("modes_full_new_from_") and base_for_new not in k:
                    del st.session_state[k]
            st.session_state["_last_modes_base_for_new"] = base_for_new
    else:
        mode_name = edit_choice
        if edit_choice in customs:
            current_s = customs[edit_choice]
        else:
            current_s = get_mode_settings(edit_choice)
        base_for_new = None  # not used for non-new

    base_label = f"new from {base_for_new}" if edit_choice == "(create new)" else edit_choice
    st.write(f"**Editing parameters for base: {base_label}**")

    # Scan period - exposed here so each custom mode can have its own preferred data lookback
    available_periods = ["3mo", "6mo", "1y", "2y", "5y"]
    default_period = st.session_state.get("scan_period", "1y")
    if edit_choice != "(create new)" and edit_choice in customs:
        cdata = customs[edit_choice]
        default_period = cdata.get("scan_period", "1y") if isinstance(cdata, dict) else "1y"
    mode_scan_period = st.selectbox(
        "Preferred Scan Period for this mode",
        options=available_periods,
        index=available_periods.index(default_period) if default_period in available_periods else 2,
        key=f"modes_scan_period_{edit_choice or 'new'}",
        help="The daily data lookback this mode prefers (used when you select the mode in sidebar)."
    )

    # Timeframe for this mode (just like scan period)
    tf_options = ["1d", "1wk", "1mo"]
    default_tf = st.session_state.get("timeframe", "1d")
    if edit_choice != "(create new)" and edit_choice in customs:
        cdata = customs[edit_choice]
        default_tf = cdata.get("timeframe", "1d") if isinstance(cdata, dict) else "1d"
    mode_timeframe = st.selectbox(
        "Preferred Timeframe (bar size) for this mode",
        options=tf_options,
        index=tf_options.index(default_tf) if default_tf in tf_options else 0,
        key=f"modes_timeframe_{edit_choice or 'new'}",
        help="Bar interval this mode prefers (1d daily, 1wk weekly, 1mo monthly)."
    )

    if edit_choice in SCAN_MODE_CHOICES:
        st.info(f"You are editing the built-in '{edit_choice}'. Saving will store a custom override under the same name (it will take precedence over the original built-in everywhere).")

    # === FULL PARAMETER EDITOR - all fields from SignalSettings ===
    # Grouped for usability. All 55+ parameters are now exposed.
    edited_params = {}

    # Helper to create consistent widget (avoid Streamlit mixed numeric type errors)
    def _field_input(fname, val, key_base):
        is_int = isinstance(val, (int, bool)) or fname in (
            "min_confluence", "watch_min_score", "min_score_default", "min_score_strong_market",
            "min_score_weak_market", "grade_a_min_confluence", "grade_a_min_score",
            "grade_b_min_confluence", "grade_b_min_score", "bonus_confluence_per",
            "max_confluence_bonus", "bonus_trend", "bonus_momentum", "bonus_structure",
            "bonus_volume", "bonus_near_high", "bonus_near_high_partial", "bonus_controlled_momentum",
            "bonus_weak_momentum", "bonus_adx", "bonus_rsi_sweet", "bonus_rs_strong",
            "bonus_rs_moderate", "adx_min_for_bonus"
        ) or ("penalty_" in fname and "threshold" not in fname and "fraction" not in fname)

        if is_int:
            v = int(val)
            stp = 1
            fmt = "%d"
            mn = None
        else:
            v = float(val)
            stp = 0.5 if any(x in fname for x in ["pct", "change", "extension", "rs_"]) else 0.1
            fmt = "%.2f"
            mn = None  # avoid type mix; user can still type negative if needed

        return st.number_input(
            fname.replace("_", " ").title(),
            value=v,
            step=stp,
            format=fmt,
            key=f"{key_base}_{fname}",
            min_value=mn
        )

    key_prefix = f"modes_full_{edit_choice}" if edit_choice != "(create new)" else f"modes_full_new_from_{base_for_new}"

    with st.expander("Core Gates & Liquidity", expanded=True):
        c = st.columns(4)
        for i, f in enumerate(['min_price', 'min_avg_volume', 'min_daily_change_pct', 'max_rsi', 'max_single_day_change_pct', 'blowoff_change_pct', 'blowoff_rsi', 'min_ma50_mult']):
            with c[i % 4]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    with st.expander("RS / Extension / Breakout Structure", expanded=True):
        c = st.columns(4)
        for i, f in enumerate(['min_rs_vs_spy', 'max_extension_pct', 'near_high_for_breakout', 'breakout_min_change', 'breakout_min_rvol']):
            with c[i % 4]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    with st.expander("Pillar Thresholds", expanded=True):
        c = st.columns(4)
        for i, f in enumerate(['min_rvol_for_volume', 'not_ext_max_rsi', 'not_ext_max_extension', 'not_ext_max_bb_pct']):
            with c[i % 4]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    with st.expander("Confluence, Scores & Grades", expanded=True):
        c = st.columns(4)
        fields_group = ['min_confluence', 'min_score_default', 'min_score_strong_market', 'min_score_weak_market',
                        'watch_min_score', 'grade_a_min_confluence', 'grade_a_min_score', 'grade_b_min_confluence',
                        'grade_b_min_score']
        for i, f in enumerate(fields_group):
            with c[i % 4]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    with st.expander("Scoring Bonuses", expanded=False):
        c = st.columns(4)
        bonus_fields = [f for f in [ff.name for ff in dc_fields(SignalSettings)] if f.startswith('bonus_')]
        for i, f in enumerate(bonus_fields):
            with c[i % 4]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    with st.expander("Penalties & Thresholds", expanded=False):
        c = st.columns(4)
        pen_fields = [f for f in [ff.name for ff in dc_fields(SignalSettings)] if f.startswith('penalty_')]
        for i, f in enumerate(pen_fields):
            with c[i % 4]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    with st.expander("Trade Plan & Risk Management (very important)", expanded=True):
        c = st.columns(3)
        trade_fields = ['atr_stop_multiplier', 'target1_r_multiple', 'target2_r_multiple',
                        'min_risk_fraction', 'max_risk_fraction', 'min_risk_reward']
        for i, f in enumerate(trade_fields):
            with c[i % 3]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    with st.expander("RSI / ADX Sweet Spots & Misc", expanded=False):
        c = st.columns(4)
        misc = ['rsi_sweet_low', 'rsi_sweet_high', 'adx_min_for_bonus']
        for i, f in enumerate(misc):
            with c[i % 4]:
                edited_params[f] = _field_input(f, getattr(current_s, f), key_prefix)

    # Save logic
    if st.button("Save / Update this mode (saves as custom override)", type="primary", width="stretch"):
        clean_name = mode_name.strip() if mode_name else ""
        if not clean_name or clean_name == "(create new)":
            st.error("Enter a valid name for the (custom) mode.")
        else:
            new_s = current_s
            for k, v in edited_params.items():
                if hasattr(new_s, k):
                    try:
                        new_s = dc_replace(new_s, **{k: type(getattr(new_s, k))(v)})
                    except Exception:
                        pass
            customs[clean_name] = {"settings": new_s, "scan_period": mode_scan_period, "timeframe": mode_timeframe}
            save_custom_modes(customs)

            st.success(f"Saved/updated mode '{clean_name}' (now available in sidebar).")
            # Use pending mechanism so the assignment happens *before* the sidebar
            # Strategy Mode widget is instantiated on the next run.
            st.session_state["_set_strategy_mode"] = clean_name
            st.rerun()

    # Only allow delete/reset for actual customs (or overrides of built-ins)
    if edit_choice != "(create new)" and edit_choice in customs:
        if st.button(f"Delete this custom mode ('{edit_choice}')", width="stretch"):
            customs.pop(edit_choice, None)
            save_custom_modes(customs)
            if st.session_state.get("strategy_mode") == edit_choice:
                st.session_state["_set_strategy_mode"] = "default"
            st.success(f"Deleted custom override '{edit_choice}'.")
            st.rerun()

        if edit_choice in SCAN_MODE_CHOICES:
            if st.button(f"Reset '{edit_choice}' to pure built-in (remove override)", width="stretch"):
                customs.pop(edit_choice, None)
                save_custom_modes(customs)
                if st.session_state.get("strategy_mode") == edit_choice:
                    st.session_state["_set_strategy_mode"] = edit_choice
                st.success(f"Reverted '{edit_choice}' to the original built-in definition.")
                st.rerun()

    st.caption("Note: Saving under a built-in name creates/updates a **custom override** (takes precedence). Use the Reset button above to remove an override for a built-in. Both Scan Period and Timeframe are saved with the mode and auto-apply in the sidebar.")


with tab_journal:
    if st.button("Refresh outcomes", type="primary"):
        with st.spinner("Fetching prices…"):
            update_outcomes(only_pending=True)
        st.rerun()
    st.caption("Re-evaluates pending and open (unrealized) entries. outcome_date and days_held will update for open trades. Closed historical trades keep the date from when they were first evaluated.")
    df = load_journal()
    _journal_stats(df)
    if not df.empty:
        st.dataframe(df.sort_values("scan_date", ascending=False), width="stretch", hide_index=True)
        # Export current journal from the database
        csv_data = df.to_csv(index=False, float_format="%.4f")
        st.download_button(
            "Download CSV",
            data=csv_data,
            file_name="signals_log.csv",
            mime="text/csv",
        )

    # Active trades (approved from picks). Monitoring is on-demand (click the button below to fetch fresh prices and recommendations).
    # The table always reflects the last time you (or the bot) ran monitor.
    st.subheader("Active Trades (approved & monitored on demand)")
    try:
        active = get_active_trades()
        if active:
            # Button only shown when there are actives. Clicking runs a fresh price check + updates DB + shows recommendations.
            if st.button("Run monitor & show recommendations", key="run_monitor_btn"):
                ups = monitor_active_trades()
                st.session_state["last_monitor_updates"] = ups
                active = get_active_trades()  # refresh after DB updates from monitor

            active_df = pd.DataFrame([
                {
                    "ID": t["id"],
                    "Sym": t["symbol"],
                    "Status": t["status"],
                    "Entry": t["entry"],
                    "Stop": t["stop_loss"],
                    "T1/T2": f"{t['target1']}/{t['target2']}",
                    "Last": t.get("last_price"),
                    "Mode": t.get("mode", ""),
                } for t in active
            ])
            st.dataframe(active_df, width="stretch", hide_index=True)

            # Close trades section
            with st.expander("Close Active Trade(s)", expanded=False):
                trade_map = {f"#{t['id']} {t['symbol']} ({t['status']})": t['id'] for t in active}
                selected = st.multiselect(
                    "Select trade(s) to close (stops monitoring)",
                    list(trade_map.keys()),
                    key="close_trades"
                )
                close_reason = st.text_input("Close reason (optional)", key="close_reason_input")
                exit_price = st.number_input(
                    "Exit price (optional - used for realized R/P&L)",
                    min_value=0.0, value=0.0, step=0.01, key="close_exit_price"
                )
                if st.button("Close Selected Trade(s)", key="close_selected_btn") and selected:
                    for label in selected:
                        tid = trade_map[label]
                        try:
                            ep = exit_price if exit_price > 0 else None
                            close_trade(tid, reason=close_reason or "Closed manually from Journal tab", exit_price=ep)
                            st.success(f"Closed {label}")
                        except Exception as ex:
                            st.error(f"Failed to close {label}: {ex}")
                    st.rerun()
                st.caption("Closed trades are removed from this active list (kept in journal history).")

            # Persist last monitor recommendations across reruns (shown after table)
            if st.session_state.get("last_monitor_updates"):
                st.markdown("**Last monitor results / recommendations:**")
                for u in st.session_state["last_monitor_updates"]:
                    st.info(f"**{u['symbol']}** — {u['event']}: {u['recommendation']}")
                if st.button("Clear last monitor results", key="clear_monitor"):
                    st.session_state.pop("last_monitor_updates", None)
                    st.rerun()
        else:
            st.caption("No active trades yet. Approve from top picks in a scan (or via Telegram bot).")
    except Exception as e:
        st.caption(f"Active trades view unavailable: {e}")

with tab_help:
    st.markdown(
        """
### How the Scanner Finds Picks (Core Logic)

The scanner looks for **healthy, momentum-driven uptrends** that still have fresh buying interest and are not too stretched.

**1. Hard Gates (must pass or the stock is rejected early)**
- Minimum price and average volume (liquidity filter)
- Positive 5-day relative strength vs SPY (the stock must be outperforming the market)
- Not a big red day (min daily change, currently relaxed)
- RSI not extremely overbought
- Not massively extended above its 50-day moving average
- **Weekly** chart must be in a clear uptrend (higher highs/lows or price above key MA) — this is a higher-timeframe filter
- No major bearish divergences on RSI or MACD

**Timeframe used by the scanner**: Daily bars (1D), default last 1 year of data. All pillars, MACD, RSI, RVOL, structure, etc. are calculated on daily data. A weekly trend filter is also required.

**2. 6 Confluence Pillars** (need at least 4 out of 6)
- **Trend** — Price above both 20 & 50 MA + 20-MA sloping upward
- **Momentum** — MACD histogram positive and improving, or a fresh bullish crossover
- **Structure** — Making higher highs on the daily chart
- **Volume (RVOL)** — Today's volume significantly above the 20-day average (shows real participation)
- **Not overextended** — RSI not too high, price not too far above the 50-MA, not at the top of the Bollinger Band
- **Breakout / Demand** — Either trading near its 52-week high (leadership) **or** a strong green day with volume

**3. Scoring + Bonuses / Penalties**
- Each passed pillar gives points.
- Extra bonuses for: being near all-time highs, "controlled" green days, strong ADX (trend strength), RSI in the momentum sweet spot (~48-65), and strong outperformance vs SPY.
- Penalties for warnings (large gaps, weak overall market, already very extended, etc.).
- Final score + confluence level → letter Grade (A/B/C) and whether it clears the minimum score threshold (thresholds are softer in strong markets, stricter in weak ones).

**4. Trade Plan**
- Stop placed below a recent swing low or using ATR (average true range).
- Targets set at 1.5× and 2.5× the risk (R-multiples).
- Only shows ideas that meet a minimum reward-to-risk ratio (currently 1.2:1).

**RVOL explained (common question)**
RVOL = Relative Volume = today's volume ÷ 20-day average volume.  
1.0× = perfectly average. 1.4×+ = unusually high interest (one of the strongest confirming signals).

Different **Strategy Modes** (Default / Conservative / Swing / Aggressive / Breakout) simply relax or tighten the gates and bonus weights above. You can edit every single number in the **Modes** tab.

The system is a **confluence + momentum + relative-strength** scanner, not a pure breakout hunter or mean-reversion tool.

### Scan modes (sidebar)
| Mode | Use for |
|------|---------|
| **Market index** | S&P 500 or Nasdaq-100 |
| **My watchlist** | Only your saved symbols |
| **Single ticker** | One stock e.g. `NVDA` |

### Strategy Modes (new)
Use the **Strategy Mode** dropdown in the sidebar (includes your saved custom modes).

**Manage custom modes** in the dedicated **Modes** tab (exactly like the Watchlist tab):
- Create / edit / delete your own profiles
- They appear automatically in the sidebar selector

After choosing a mode you can still fine-tune in the expander (it will switch to "Custom").

You can also load `mode: my-name` + `strategy:` overrides from `config.yaml`.

### Watchlist tab
Add/remove symbols or paste a list and **Save**. Stored in SQLite `data/app.db` (legacy `data/watchlist.txt` is migrated automatically on first run).

### Command line (now supports modes + tuning)
```powershell
python -m us_stock_scanner --symbol NVDA --mode aggressive
python -m us_stock_scanner --watchlist --mode swing
python -m us_stock_scanner -u sp500 --mode breakout
python -m us_stock_scanner -c config.yaml          # can contain "mode: aggressive" + strategy overrides
python -m us_stock_scanner --preset relaxed-long
```

Use `python -m us_stock_scanner --list` to see presets (some carry strategy).
`python -m us_stock_scanner --help` shows the --mode choices.
        """
    )