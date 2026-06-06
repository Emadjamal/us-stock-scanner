"""Centralized storage for the US Stock Scanner (local SQLite or Turso/libSQL).

- Local: single data/app.db file (replaces old CSV/TXT/YAML with auto-migration).
- Cloud: set TURSO_DATABASE_URL + TURSO_AUTH_TOKEN (or LIBSQL_*) env vars.
  Then it uses the `libsql` package (pip install libsql) for remote SQLite-compatible access.
  This solves the ephemeral FS problem on free PaaS while keeping the same API.

All public functions aim to keep backward compatibility with existing callers.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import SignalSettings


def _row_factory(cursor, row):
    """Return rows as dicts so code can use row['column'] consistently
    for both local sqlite3 and remote libsql/Turso connections.
    This fixes TypeError when accessing row['symbol'] etc. on remote.
    """
    if cursor.description is None:
        return row
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

# Columns expected by the rest of the app (kept for compatibility)
JOURNAL_COLUMNS = [
    "scan_date",
    "universe",
    "tier",
    "rank",
    "symbol",
    "grade",
    "score",
    "setup_type",
    "entry",
    "entry_market",
    "stop_loss",
    "target1",
    "target2",
    "risk_pct",
    "rs_vs_spy",
    "change_pct",
    "rsi",
    "rvol",
    "adx",
    "outcome_status",
    "outcome_date",
    "outcome_price",
    "pct_from_entry",
    "days_held",
]


def get_db_path() -> Path | str:
    """Return the path/URL to the backing store.
    For local: Path to data/app.db
    For Turso: the TURSO_DATABASE_URL (string)
    """
    if is_using_turso():
        return os.getenv("TURSO_DATABASE_URL") or os.getenv("LIBSQL_URL") or "turso:remote"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DB_PATH


def is_using_turso() -> bool:
    """True if we are configured to use a remote Turso / libSQL database."""
    return bool(os.getenv("TURSO_DATABASE_URL") or os.getenv("LIBSQL_URL"))


def _get_conn():
    """Get a connection. Uses libsql (Turso) if TURSO_DATABASE_URL + token are set,
    otherwise falls back to local SQLite file (with WAL).
    The returned connection tries to be API-compatible for our usage (execute, fetchall, Row-like).
    """
    turso_url = os.getenv("TURSO_DATABASE_URL") or os.getenv("LIBSQL_URL")
    if turso_url:
        try:
            import libsql
            auth_token = os.getenv("TURSO_AUTH_TOKEN") or os.getenv("LIBSQL_AUTH_TOKEN")
            conn = libsql.connect(database=turso_url, auth_token=auth_token)
            conn.row_factory = _row_factory
            # libsql remote connections are server-side; no local WAL/PRAGMA needed for most cases
            return conn
        except ImportError as e:
            # Fall back gracefully with a clear message (user can pip install libsql)
            print("[storage] WARNING: libsql not installed but Turso URL detected. "
                  "Falling back to local SQLite. Run: pip install libsql")
            # continue to local below

    # Local SQLite (original behavior)
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = _row_factory
    # Enable WAL mode for better concurrent reads/writes (local only)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn


def init_db() -> None:
    """Create tables if they don't exist and run one-time migration from old files."""
    conn = _get_conn()
    try:
        # Watchlist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY
            )
        """)

        # Signals / Journal log
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS signals_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {", ".join(f"{col} TEXT" for col in JOURNAL_COLUMNS)}
            )
        """)

        # Custom modes (store the whole settings dict as JSON)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_modes (
                name TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)

        # Active trades for approved signals (live monitoring)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                approved_ts TEXT,
                entry REAL,
                stop_loss REAL,
                target1 REAL,
                target2 REAL,
                grade TEXT,
                mode TEXT,
                reasons_json TEXT,
                status TEXT DEFAULT 'open',
                last_price REAL,
                last_checked_ts TEXT,
                notes TEXT,
                initial_risk_pct REAL,
                realized_r REAL DEFAULT 0.0
            )
        """)

        conn.commit()

        # One-time migration from legacy files (if DB tables are empty).
        # Skip for remote Turso (you can import manually if desired).
        if not is_using_turso():
            _migrate_from_legacy_files(conn)
    finally:
        conn.close()


def _migrate_from_legacy_files(conn: sqlite3.Connection) -> None:
    """Import data from old CSV/TXT/YAML files if the corresponding tables are empty."""
    # Watchlist
    count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    if count == 0:
        legacy_watch = PROJECT_ROOT / "data" / "watchlist.txt"
        if legacy_watch.exists():
            symbols = []
            for line in legacy_watch.read_text(encoding="utf-8").splitlines():
                sym = line.strip().upper().replace(".", "-")
                if sym and not sym.startswith("#"):
                    symbols.append(sym)
            if symbols:
                conn.executemany(
                    "INSERT OR IGNORE INTO watchlist (symbol) VALUES (?)",
                    [(s,) for s in symbols],
                )
                conn.commit()

    # Signals log
    count = conn.execute("SELECT COUNT(*) FROM signals_log").fetchone()[0]
    if count == 0:
        legacy_csv = PROJECT_ROOT / "data" / "signals_log.csv"
        if legacy_csv.exists():
            try:
                df = pd.read_csv(legacy_csv, dtype=str, keep_default_na=False)
                # Ensure all expected columns exist
                for col in JOURNAL_COLUMNS:
                    if col not in df.columns:
                        df[col] = ""
                df = df[JOURNAL_COLUMNS]
                df.to_sql("signals_log", conn, if_exists="append", index=False)
                conn.commit()
            except Exception:
                pass  # don't crash on bad legacy file

    # Custom modes
    count = conn.execute("SELECT COUNT(*) FROM custom_modes").fetchone()[0]
    if count == 0:
        for candidate in [
            PROJECT_ROOT / "data" / "custom_modes.yaml",
            PROJECT_ROOT / "custom_modes.yaml",
        ]:
            if candidate.exists():
                try:
                    import yaml
                    data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
                    for name, sdict in data.items():
                        if isinstance(name, str) and isinstance(sdict, dict):
                            conn.execute(
                                "INSERT OR REPLACE INTO custom_modes (name, data) VALUES (?, ?)",
                                (name, json.dumps(sdict)),
                            )
                    conn.commit()
                    break
                except Exception:
                    pass


# -----------------------------
# Watchlist
# -----------------------------

def load_watchlist() -> list[str]:
    """Return list of symbols (normalized)."""
    init_db()
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT symbol FROM watchlist ORDER BY symbol").fetchall()
        symbols = [row["symbol"] for row in rows]
        if not symbols:
            # Ensure a sensible default the first time
            default = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
            save_watchlist(default)
            return default
        return symbols
    finally:
        conn.close()


def save_watchlist(symbols: list[str]) -> None:
    """Replace the entire watchlist with the given symbols (normalized)."""
    init_db()
    normalized = []
    seen = set()
    for s in symbols:
        sym = s.strip().upper().replace(".", "-")
        if sym and sym not in seen:
            seen.add(sym)
            normalized.append(sym)

    conn = _get_conn()
    try:
        conn.execute("DELETE FROM watchlist")
        if normalized:
            conn.executemany(
                "INSERT INTO watchlist (symbol) VALUES (?)",
                [(s,) for s in normalized],
            )
        conn.commit()
    finally:
        conn.close()


def add_symbols(symbols: list[str]) -> list[str]:
    """Add symbols to watchlist (idempotent). Return current list."""
    current = set(load_watchlist())
    for s in symbols:
        sym = s.strip().upper().replace(".", "-")
        if sym:
            current.add(sym)
    save_watchlist(sorted(current))
    return sorted(current)


def remove_symbols(symbols: list[str]) -> list[str]:
    """Remove symbols from watchlist. Return current list."""
    drop = {s.strip().upper().replace(".", "-") for s in symbols}
    current = [s for s in load_watchlist() if s not in drop]
    save_watchlist(current)
    return current


def watchlist_path() -> Path | str:
    """Return the backing store path/URL (DB or Turso); kept for UI/CLI captions."""
    return get_db_path()


# -----------------------------
# Journal / Signals Log
# -----------------------------

def load_journal() -> pd.DataFrame:
    """Return journal as DataFrame (same shape as before).
    Works for both local sqlite3 and remote libsql/Turso (falls back to manual fetch if pandas can't use the conn directly).
    """
    init_db()
    conn = _get_conn()
    try:
        try:
            df = pd.read_sql_query("SELECT * FROM signals_log", conn)
        except Exception:
            # Fallback for libsql remote or other non-standard connections
            cur = conn.execute("SELECT * FROM signals_log")
            rows = cur.fetchall()
            if not rows:
                return pd.DataFrame(columns=JOURNAL_COLUMNS)
            # Try to get column names
            cols = [d[0] for d in cur.description] if cur.description else JOURNAL_COLUMNS
            df = pd.DataFrame([dict(zip(cols, r)) if not isinstance(r, dict) else r for r in rows])

        if df.empty:
            return pd.DataFrame(columns=JOURNAL_COLUMNS)

        # Ensure all columns exist and are in the right order
        for col in JOURNAL_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        df = df[JOURNAL_COLUMNS]

        # Coerce types like the old code did
        numeric_cols = [
            "rank", "score", "entry", "entry_market", "stop_loss",
            "target1", "target2", "risk_pct", "rs_vs_spy", "change_pct",
            "rsi", "rvol", "adx", "outcome_price", "pct_from_entry", "days_held",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        for col in ("scan_date", "universe", "tier", "symbol", "grade", "setup_type",
                    "outcome_status", "outcome_date"):
            if col in df.columns:
                df[col] = df[col].astype(str).replace("nan", "").replace("None", "")

        return df
    finally:
        try:
            conn.close()
        except Exception:
            pass


def append_scan(
    result: "ScanResult",
    universe: str = "sp500",
    *,
    include_watchlist: bool = False,
) -> None:
    """Append top picks (and optionally worth_watching) to the journal."""
    from us_stock_scanner.trade_signal import TradeSignal  # avoid circular import at top

    init_db()
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rows: list[dict] = []
    for rank, sig in enumerate(result.top_picks[:3], 1):
        rows.append(_make_signal_row(sig, scan_date=scan_date, universe=universe, tier="top_pick", rank=rank))

    if include_watchlist:
        for i, sig in enumerate(result.worth_watching, 1):
            rows.append(
                _make_signal_row(sig, scan_date=scan_date, universe=universe, tier="watch", rank=i)
            )

    if not rows:
        return

    conn = _get_conn()
    try:
        for row in rows:
            placeholders = ", ".join(["?"] * len(JOURNAL_COLUMNS))
            conn.execute(
                f"INSERT INTO signals_log ({', '.join(JOURNAL_COLUMNS)}) VALUES ({placeholders})",
                [row.get(col, "") for col in JOURNAL_COLUMNS],
            )
        conn.commit()
    finally:
        conn.close()


def _make_signal_row(
    sig: "TradeSignal",
    *,
    scan_date: str,
    universe: str,
    tier: str,
    rank: int,
) -> dict:
    market = sig.entry_market if sig.entry_market > 0 else sig.entry
    return {
        "scan_date": scan_date,
        "universe": universe,
        "tier": tier,
        "rank": rank,
        "symbol": sig.symbol,
        "grade": sig.grade,
        "score": sig.score,
        "setup_type": sig.setup_type,
        "entry": sig.entry,
        "entry_market": market,
        "stop_loss": sig.stop_loss,
        "target1": sig.target1,
        "target2": sig.target2,
        "risk_pct": sig.risk_pct,
        "rs_vs_spy": sig.rs_vs_spy,
        "change_pct": sig.change_pct,
        "rsi": sig.rsi,
        "rvol": sig.rvol,
        "adx": sig.adx,
        "outcome_status": "",
        "outcome_date": "",
        "outcome_price": "",
        "pct_from_entry": "",
        "days_held": "",
    }


def journal_path() -> Path | str:
    """Return the backing store path/URL (now the DB; export still offers CSV)."""
    return get_db_path()


def update_journal_rows(updates: list[dict]) -> None:
    """Update specific rows in the journal (used by outcomes.py).
    Each dict must contain at least 'symbol' and 'scan_date' as keys for identification,
    plus the fields to update.
    """
    if not updates:
        return
    init_db()
    conn = _get_conn()
    try:
        for row in updates:
            symbol = row.get("symbol")
            scan_date = row.get("scan_date")
            if not symbol or not scan_date:
                continue

            set_clauses = []
            values = []
            for col in JOURNAL_COLUMNS:
                if col in row and col not in ("symbol", "scan_date"):
                    set_clauses.append(f"{col} = ?")
                    values.append(row[col])

            if not set_clauses:
                continue

            values.extend([symbol, scan_date])
            sql = f"""
                UPDATE signals_log
                SET {", ".join(set_clauses)}
                WHERE symbol = ? AND scan_date = ?
            """
            conn.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


# -----------------------------
# Custom Modes
# -----------------------------

def load_custom_modes() -> dict[str, SignalSettings]:
    """Load custom modes from SQLite (JSON in 'data' column)."""
    init_db()
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT name, data FROM custom_modes").fetchall()
        modes: dict[str, SignalSettings] = {}
        for row in rows:
            name = row["name"]
            try:
                sdict = json.loads(row["data"])
                modes[name] = SignalSettings.from_dict(sdict)
            except Exception:
                continue
        return modes
    finally:
        conn.close()


def save_custom_modes(modes: dict[str, SignalSettings]) -> None:
    """Save (replace) all custom modes."""
    init_db()
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM custom_modes")
        for name, s in modes.items():
            serial = s.to_dict()
            conn.execute(
                "INSERT INTO custom_modes (name, data) VALUES (?, ?)",
                (name, json.dumps(serial)),
            )
        conn.commit()
    finally:
        conn.close()


def custom_modes_path() -> Path:
    """Return the backing store path (now the SQLite DB for custom modes)."""
    return get_db_path()


# =============================================================================
# Active Trades (approved signals for live monitoring & management)
# Professional trade management layer on top of the scanner.
# =============================================================================

def approve_trade(
    sig: "TradeSignal",
    *,
    mode: str = "default",
    notes: str = "",
) -> int:
    """Approve a top pick / signal and start monitoring it as an active trade.
    Returns the new trade id.
    """
    import json as _json

    init_db()
    conn = _get_conn()
    try:
        reasons = getattr(sig, "reasons", []) or []
        initial_risk = getattr(sig, "risk_pct", 0.0) or 0.0

        cur = conn.execute(
            """
            INSERT INTO active_trades
            (symbol, approved_ts, entry, stop_loss, target1, target2, grade, mode,
             reasons_json, status, last_price, last_checked_ts, notes, initial_risk_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
            """,
            (
                sig.symbol,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                sig.entry,
                sig.stop_loss,
                sig.target1,
                sig.target2,
                sig.grade,
                mode,
                _json.dumps(reasons),
                sig.entry_market or sig.entry,  # initial "current"
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                notes,
                initial_risk,
            ),
        )
        trade_id = cur.lastrowid
        conn.commit()
        return trade_id
    finally:
        conn.close()


def get_active_trades() -> list[dict]:
    """Return all currently active (not closed) trades."""
    init_db()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM active_trades WHERE status NOT IN ('closed', 'stopped', 't2_hit') ORDER BY approved_ts DESC"
        ).fetchall()
        trades = []
        for r in rows:
            d = dict(r)
            try:
                d["reasons"] = json.loads(d.get("reasons_json") or "[]")
            except Exception:
                d["reasons"] = []
            trades.append(d)
        return trades
    finally:
        conn.close()


def get_active_trade(trade_id: int) -> dict | None:
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM active_trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["reasons"] = json.loads(d.get("reasons_json") or "[]")
        except Exception:
            d["reasons"] = []
        return d
    finally:
        conn.close()


def close_trade(trade_id: int, *, reason: str = "", exit_price: float | None = None) -> None:
    """Manually or automatically close an active trade."""
    init_db()
    conn = _get_conn()
    try:
        trade = get_active_trade(trade_id)
        if not trade:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        exit_p = exit_price if exit_price is not None else trade.get("last_price") or trade.get("entry", 0)
        entry = trade.get("entry", 0)
        realized_r = 0.0
        if entry > 0 and trade.get("stop_loss"):
            risk = entry - trade["stop_loss"]
            if risk > 0:
                realized_r = (exit_p - entry) / risk

        notes = (trade.get("notes") or "") + f" | Closed {now}: {reason}"
        conn.execute(
            """
            UPDATE active_trades
            SET status = 'closed',
                last_price = ?,
                last_checked_ts = ?,
                notes = ?,
                realized_r = ?
            WHERE id = ?
            """,
            (exit_p, now, notes, round(realized_r, 2), trade_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_active_trade(trade_id: int, **fields) -> None:
    """Generic updater (status, last_price, notes, etc.)."""
    if not fields:
        return
    init_db()
    conn = _get_conn()
    try:
        set_clauses = ", ".join([f"{k} = ?" for k in fields])
        values = list(fields.values()) + [trade_id]
        conn.execute(f"UPDATE active_trades SET {set_clauses} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def _fetch_current_price(symbol: str) -> float:
    """Lightweight current/last close price fetch."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="5d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def monitor_active_trades(*, notify_callback=None) -> list[dict]:
    """Manually check all active trades against current prices and levels.
    This is an *on-demand* operation (not live/background).
    Call it from the UI button or /monitor in the bot.

    Updates statuses in the DB (t1_hit, t2_hit, stopped, etc.) and returns recommendations.
    The Active Trades table shows data from the last time this was run.

    Professional logic:
    - Price level triggers for T1/T2/Stop.
    - Basic invalidation if closes significantly below entry after approval.
    - Recommendations based on status + current extension/momentum.
    """
    trades = get_active_trades()
    if not trades:
        return []

    updates = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for t in trades:
        tid = t["id"]
        sym = t["symbol"]
        entry = t.get("entry") or 0
        stop = t.get("stop_loss") or 0
        t1 = t.get("target1") or 0
        t2 = t.get("target2") or 0
        status = t.get("status", "open")

        price = _fetch_current_price(sym)
        if price <= 0:
            continue

        new_status = status
        rec = ""
        event = ""

        # Core level checks (professional risk management)
        if price <= stop and status not in ("stopped", "closed"):
            new_status = "stopped"
            event = "STOP LOSS HIT"
            rec = "Trade stopped per plan. Review what invalidated the setup. Consider waiting for new confluence before re-entering."
        elif price >= t2 and status != "t2_hit":
            new_status = "t2_hit"
            event = "TARGET 2 HIT"
            rec = "Excellent! Full target reached. Consider closing remainder or trail aggressively with ATR. Book profits."
        elif price >= t1 and status not in ("t1_hit", "t2_hit", "stopped"):
            new_status = "t1_hit"
            event = "TARGET 1 HIT"
            rec = "Scale out 40-60% here. Move stop to breakeven (entry). Let the rest run to T2 or trail. Protect profits."
        elif status == "t1_hit" and price < entry * 0.98 and price > stop:
            # mild pullback after T1 but not stopped
            rec = "Pullback after partial profit. If structure still holds (higher lows, volume support), continue. Else tighten stops."
        elif price < entry and status == "open":
            # early invalidation warning
            rec = "Price back below entry. Monitor closely for breakdown. Consider tightening stop or closing small size if momentum weak."

        # Update if changed
        changed = False
        if new_status != status:
            update_active_trade(
                tid,
                status=new_status,
                last_price=price,
                last_checked_ts=now,
                notes=(t.get("notes") or "") + f" | {now}: {event}",
                realized_r=round((price - entry) / (entry - stop), 2) if (entry > stop and entry > 0) else 0.0,
            )
            changed = True
        else:
            update_active_trade(tid, last_price=price, last_checked_ts=now)

        if not rec:
            if status in ("t1_hit", "t2_hit"):
                rec = f"Target(s) reached. Current price ${price:.2f}. Consider trailing or closing remainder."
            elif status == "stopped":
                rec = "Trade stopped. Review the setup."
            elif status == "open":
                rec = f"No triggers crossed. Price ${price:.2f}. Watching levels."
            else:
                rec = f"Status {status}. Price ${price:.2f}."

        updates.append({
            "trade_id": tid,
            "symbol": sym,
            "event": event or "PRICE CHECK",
            "price": round(price, 2),
            "status": new_status,
            "recommendation": rec,
            "changed": changed,
        })

        if notify_callback and changed:
            try:
                notify_callback(updates[-1])
            except Exception:
                pass

    return updates


# Run init on import so tables exist
init_db()
