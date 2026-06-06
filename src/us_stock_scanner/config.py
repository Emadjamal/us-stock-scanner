"""Load scan settings from YAML."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

import yaml

from us_stock_scanner.filters import ScanCriteria


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _filters_dict(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("filters") or data


def criteria_from_config(data: dict[str, Any]) -> ScanCriteria:
    f = _filters_dict(data)
    return ScanCriteria(
        min_price=f.get("min_price"),
        max_price=f.get("max_price"),
        min_volume=f.get("min_volume"),
        min_change_pct=f.get("min_change_pct"),
        max_change_pct=f.get("max_change_pct"),
        min_rsi=f.get("min_rsi"),
        max_rsi=f.get("max_rsi"),
        rsi_period=int(f.get("rsi_period", 14)),
        min_avg_volume_20d=f.get("min_avg_volume_20d"),
        macd_fast=int(f.get("macd_fast", 12)),
        macd_slow=int(f.get("macd_slow", 26)),
        macd_signal=int(f.get("macd_signal", 9)),
        macd_crossover=f.get("macd_crossover"),
        min_macd_hist=f.get("min_macd_hist"),
        max_macd_hist=f.get("max_macd_hist"),
        ma_fast=int(f.get("ma_fast", 20)),
        ma_slow=int(f.get("ma_slow", 50)),
        ma_type=str(f.get("ma_type", "sma")),
        ma_crossover=f.get("ma_crossover"),
        min_gap_pct=f.get("min_gap_pct"),
        max_gap_pct=f.get("max_gap_pct"),
        gap_direction=f.get("gap_direction"),
        bb_period=int(f.get("bb_period", 20)),
        bb_std=float(f.get("bb_std", 2.0)),
        min_bb_pct_b=f.get("min_bb_pct_b"),
        max_bb_pct_b=f.get("max_bb_pct_b"),
        max_bb_bandwidth_pct=f.get("max_bb_bandwidth_pct"),
        bb_touch=f.get("bb_touch"),
        high_lookback=int(f.get("high_lookback", 252)),
        min_pct_from_high=f.get("min_pct_from_high"),
        max_pct_from_high=f.get("max_pct_from_high"),
        rvol_lookback=int(f.get("rvol_lookback", 20)),
        min_rvol=f.get("min_rvol"),
        max_rvol=f.get("max_rvol"),
        atr_period=int(f.get("atr_period", 14)),
        min_atr_multiple=f.get("min_atr_multiple"),
        stoch_k_period=int(f.get("stoch_k_period", 14)),
        stoch_d_period=int(f.get("stoch_d_period", 3)),
        min_stoch_k=f.get("min_stoch_k"),
        max_stoch_k=f.get("max_stoch_k"),
        stoch_crossover=f.get("stoch_crossover"),
        adx_period=int(f.get("adx_period", 14)),
        min_adx=f.get("min_adx"),
        max_adx=f.get("max_adx"),
    )


@dataclass(frozen=True)
class SignalSettings:
    """Tunable parameters for the main long-signal strategy (v2 engine).
    Not hard-coded so users/presets/UI can relax or specialize (e.g. for breakouts).
    Defaults are a relaxed version of the original strict gates.
    """

    # Hard gates (liquidity / price always on)
    min_price: float = 5.0
    min_avg_volume: float = 750_000

    # Daily momentum gate - relaxed from original -0.5 (was killing valid pullbacks)
    min_daily_change_pct: float = -2.5

    # RSI cap - relaxed from 75 to allow strong momentum without instant kill on leaders
    max_rsi: float = 78.0

    # Other hard rejects
    max_single_day_change_pct: float = 12.0
    blowoff_change_pct: float = 8.0
    blowoff_rsi: float = 68.0
    min_ma50_mult: float = 0.97  # last >= ma50 * this

    # RS / extension (core required)
    min_rs_vs_spy: float = 0.5
    max_extension_pct: float = 15.0

    # Pillar thresholds (volume, not-ext, breakout/demand)
    min_rvol_for_volume: float = 1.15
    not_ext_max_rsi: float = 68.0
    not_ext_max_extension: float = 12.0
    not_ext_max_bb_pct: float = 92.0
    breakout_min_change: float = 1.0
    breakout_min_rvol: float = 1.2
    near_high_for_breakout: float = -3.0

    # Confluence & scores
    min_confluence: int = 4
    min_score_default: float = 52.0
    min_score_strong_market: float = 48.0
    min_score_weak_market: float = 58.0
    watch_min_score: float = 58.0

    # Grade thresholds
    grade_a_min_confluence: int = 5
    grade_a_min_score: float = 72.0
    grade_b_min_confluence: int = 4
    grade_b_min_score: float = 62.0

    # Scoring bonuses (confluence base + pillar / feature adds)
    bonus_confluence_per: int = 3
    max_confluence_bonus: int = 15
    bonus_trend: int = 14
    bonus_momentum: int = 14
    bonus_structure: int = 10
    bonus_volume: int = 12
    bonus_near_high: int = 12
    bonus_near_high_partial: int = 6
    bonus_controlled_momentum: int = 10
    bonus_weak_momentum: int = 4
    bonus_adx: int = 8
    bonus_rsi_sweet: int = 8
    bonus_rs_strong: int = 8
    bonus_rs_moderate: int = 4

    # Sweet spot for RSI bonus (used in scoring)
    rsi_sweet_low: float = 48.0
    rsi_sweet_high: float = 65.0
    adx_min_for_bonus: float = 22.0

    # Penalties
    penalty_per_warning: float = 6.0
    penalty_weak_market: float = 6.0
    penalty_high_rsi: float = 4.0
    penalty_extension: float = 4.0

    # Thresholds used in penalty logic (separate from max_rsi gate)
    penalty_high_rsi_threshold: float = 65.0
    penalty_extension_threshold: float = 8.0

    # Trade plan / risk (from _trade_levels)
    atr_stop_multiplier: float = 1.5
    target1_r_multiple: float = 1.5
    target2_r_multiple: float = 2.5
    min_risk_fraction: float = 0.005
    max_risk_fraction: float = 0.08
    min_risk_reward: float = 1.2

    def to_dict(self) -> dict[str, Any]:
        """Serialize all tunable parameters (for JSON storage / roundtrip)."""
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SignalSettings":
        """Rehydrate from a (possibly partial) dict. Fills defaults for missing keys."""
        return strategy_settings_from_config({"strategy": d or {}})


def default_signal_settings() -> SignalSettings:
    """Factory for the (relaxed) defaults used by main scans when nothing provided."""
    return SignalSettings()


def strategy_settings_from_config(data: dict[str, Any]) -> SignalSettings:
    """Load from YAML under 'strategy:' key (or top-level for convenience).
    Falls back to relaxed defaults for any missing keys.
    This unifies tuning with the expert filters path (which still uses 'filters:').
    """
    if not data:
        return default_signal_settings()
    s = data.get("strategy") or data
    if not isinstance(s, dict):
        return default_signal_settings()

    base = default_signal_settings()
    overrides: dict[str, Any] = {}
    for f in fields(SignalSettings):
        if f.name in s and s[f.name] is not None:
            overrides[f.name] = s[f.name]
    if overrides:
        return replace(base, **overrides)
    return base


# =============================================================================
# Scan Modes — high-level tuning profiles + user-managed custom modes
# =============================================================================

SCAN_MODE_CHOICES = ["default", "conservative", "swing", "aggressive", "breakout"]


def get_mode_settings(name: str | None = None) -> SignalSettings:
    """Return a full SignalSettings for the given mode name.

    Checks custom user modes first (from the database), then built-ins.
    This allows users to fully manage their own modes via the UI (like watchlist).
    """
    mode = (name or "default").lower().strip().replace("_", "-")
    base = default_signal_settings()

    # Custom user modes take precedence
    customs = load_custom_modes()
    if mode in customs:
        return customs[mode]

    if mode in ("default", "balanced", "normal"):
        return base

    if mode in ("conservative", "safe", "defensive", "quality"):
        return replace(
            base,
            min_daily_change_pct=-1.0,
            max_rsi=72.0,
            min_rs_vs_spy=0.8,
            max_extension_pct=10.0,
            min_rvol_for_volume=1.35,
            min_confluence=5,
            min_score_default=58.0,
            min_score_weak_market=62.0,
            atr_stop_multiplier=1.2,
            min_risk_reward=1.6,
            bonus_structure=12,
            penalty_weak_market=8,
        )

    if mode in ("swing", "position", "multi-day"):
        return replace(
            base,
            min_daily_change_pct=-3.5,
            max_rsi=80.0,
            min_rs_vs_spy=0.25,
            max_extension_pct=18.0,
            min_rvol_for_volume=1.05,
            min_confluence=4,
            min_score_default=50.0,
            near_high_for_breakout=-8.0,
            bonus_structure=14,
            bonus_near_high_partial=8,
            atr_stop_multiplier=1.8,
            target2_r_multiple=3.0,
        )

    if mode in ("aggressive", "hot", "momentum", "high-risk"):
        return replace(
            base,
            min_daily_change_pct=-4.5,
            max_rsi=86.0,
            min_rs_vs_spy=0.0,
            max_extension_pct=25.0,
            min_rvol_for_volume=1.0,
            min_confluence=3,
            min_score_default=44.0,
            min_score_strong_market=42.0,
            atr_stop_multiplier=2.2,
            max_risk_fraction=0.10,
            bonus_controlled_momentum=12,
            penalty_high_rsi=2.0,
        )

    if mode in ("breakout", "leader", "break"):
        return replace(
            base,
            min_daily_change_pct=-1.5,
            max_rsi=83.0,
            min_rs_vs_spy=0.6,
            max_extension_pct=20.0,
            min_rvol_for_volume=1.25,
            min_confluence=4,
            min_score_default=52.0,
            near_high_for_breakout=-2.5,
            breakout_min_change=0.8,
            breakout_min_rvol=1.4,
            bonus_near_high=15,
            bonus_volume=14,
            atr_stop_multiplier=1.6,
        )

    return base


# =============================================================================
# Custom user-managed modes (persisted like the watchlist)
# =============================================================================


def custom_modes_path() -> Path:
    """Return the backing store (SQLite DB)."""
    from . import storage
    return storage.get_db_path()


def load_custom_modes() -> dict[str, SignalSettings]:
    """Load user-defined custom modes (now from SQLite)."""
    from . import storage
    return storage.load_custom_modes()


def save_custom_modes(modes: dict[str, SignalSettings]) -> None:
    """Save custom modes (now to SQLite)."""
    from . import storage
    storage.save_custom_modes(modes)


def get_all_modes() -> dict[str, SignalSettings]:
    """Built-in modes + user custom modes (custom names override built-ins if conflict)."""
    modes = {m: get_mode_settings(m) for m in SCAN_MODE_CHOICES}
    modes.update(load_custom_modes())
    return modes


