"""Load scan settings from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from us_stock_scanner.filters import ScanCriteria


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def criteria_from_config(data: dict[str, Any]) -> ScanCriteria:
    filters = data.get("filters") or {}
    return ScanCriteria(
        min_price=filters.get("min_price"),
        max_price=filters.get("max_price"),
        min_volume=filters.get("min_volume"),
        min_change_pct=filters.get("min_change_pct"),
        max_change_pct=filters.get("max_change_pct"),
        min_rsi=filters.get("min_rsi"),
        max_rsi=filters.get("max_rsi"),
        rsi_period=int(filters.get("rsi_period", 14)),
        min_avg_volume_20d=filters.get("min_avg_volume_20d"),
    )