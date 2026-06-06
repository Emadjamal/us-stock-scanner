"""
Telegram Bot for US Stock Scanner.

Run locally:
  pip install "python-telegram-bot>=21.0"
  python bot.py

Deploy options: Railway (recommended for free/persistent), Fly.io, Render (paid for always-on), or your own VPS + systemd.

Environment:
  TELEGRAM_BOT_TOKEN=...          (required, from @BotFather)
  Optional Turso for persistence across deploys/sleeps:
    TURSO_DATABASE_URL=libsql://...
    TURSO_AUTH_TOKEN=...

Commands:
  /start
  /scan [sp500|nasdaq100|watchlist]   -- run a scan (rich output + approve buttons)
  /active                         -- list & manage approved live trades (buttons)
  /monitor                        -- manually check active trades for price updates + recommendations (on-demand, not live/auto)
  /watchlist
  /add SYMBOL [SYMBOL ...]
  /remove SYMBOL [SYMBOL ...]
  /modes
  /setmode NAME  (e.g. default, swing, aggressive or your custom)
  /journal [n=10]
  /help

After /scan, use the inline buttons to Approve picks (starts monitoring), get Why justification, or details.
Background monitoring runs automatically every ~10 minutes (for subscribed chats) and pushes notifications on T1/T2/stop/invalidation events.
Use /monitor for on-demand checks. /unsubscribe to stop background notifications.
"""

from __future__ import annotations

import asyncio
import html
import os
import sys
from datetime import datetime
from pathlib import Path

# Make package importable when running bot.py directly
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from us_stock_scanner.auto_pick import run_auto_pick
from us_stock_scanner.config import (
    SCAN_MODE_CHOICES,
    get_all_modes,
    get_mode_settings,
    load_custom_modes,
)
from us_stock_scanner.journal import load_journal
from us_stock_scanner.storage import (
    approve_trade,
    close_trade,
    get_active_trade,
    get_active_trades,
    monitor_active_trades,
)
from us_stock_scanner.watchlist import add_symbols, load_watchlist, remove_symbols

# Try to import the bot library (optional dependency)
try:
    from telegram import (
        Update,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        ReplyKeyboardMarkup,
        KeyboardButton,
    )
    from telegram.ext import (
        ApplicationBuilder,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    from telegram.constants import ParseMode
except ImportError:
    print("python-telegram-bot is not installed.")
    print("Install with: pip install 'python-telegram-bot>=21.0'")
    sys.exit(1)


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Current effective mode for this bot process (in-memory; persisted via custom modes in DB)
CURRENT_MODE = os.getenv("DEFAULT_MODE", "default")


def _get_effective_settings():
    return get_mode_settings(CURRENT_MODE)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Auto-subscribe this chat for scheduled monitoring notifications (background job)
    chats = context.bot_data.setdefault("monitor_chats", set())
    chats.add(update.effective_chat.id)

    text = (
        "📈 US Stock Scanner Bot\n\n"
        "Commands (or use the keyboard below):\n"
        "/scan [sp500|nasdaq100|watchlist] — rich scan with approve buttons\n"
        "/active — your live approved trades (with action buttons)\n"
        "/monitor — manually check active trades for price updates + recommendations (on-demand)\n"
        "/setmode &lt;name&gt;\n"
        "/journal\n\n"
        f"Current mode: <b>{CURRENT_MODE}</b>\n"
        "Approve from /scan results to start monitoring + get notified on changes.\n\n"
        "🔔 Background monitoring is active (checks every ~10 minutes and notifies you on changes).\n"
        "Use /unsubscribe to stop automatic notifications."
    )
    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("/scan sp500"), KeyboardButton("/active"), KeyboardButton("/monitor")],
            [KeyboardButton("/modes"), KeyboardButton("/setmode swing"), KeyboardButton("/journal")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def modes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customs = load_custom_modes()
    all_modes = get_all_modes()
    lines = ["<b>Available modes</b> (customs override built-ins):"]
    for name in sorted(all_modes):
        typ = "custom" if name in customs else "built-in"
        s = all_modes[name]
        ex = f"chg={s.min_daily_change_pct}, rsi&lt;={s.max_rsi}, conf&gt;={s.min_confluence}"
        lines.append(f"• {name} ({typ}) — {ex}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def setmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CURRENT_MODE
    if not context.args:
        await update.message.reply_text(
            "Usage: /setmode NAME\nAvailable: " + ", ".join(SCAN_MODE_CHOICES + list(load_custom_modes().keys()))
        )
        return
    name = context.args[0].lower().strip()
    allm = get_all_modes()
    if name not in allm:
        await update.message.reply_text(f"Unknown mode '{name}'. Use /modes to list.")
        return
    CURRENT_MODE = name
    s = get_mode_settings(name)
    await update.message.reply_text(
        f"✅ Mode set to '{name}'.\n"
        f"Gates: min_chg={s.min_daily_change_pct} | max_rsi={s.max_rsi} | min_conf={s.min_confluence}\n"
        "New scans will use this profile."
    )


def _format_pick_html(sig, rank: int, mode: str) -> str:
    """Rich HTML justification + levels, matching the spirit of the Streamlit UI."""
    # Use \n for line breaks — Telegram HTML does NOT support <br>
    reasons_html = "\n".join([f"• {html.escape(r)}" for r in (sig.reasons or [])[:6]]) or "Strong confluence across pillars."
    entry_line = (
        f"Entry (limit): <b>${sig.entry:.2f}</b>" if sig.entry < (sig.entry_market or sig.entry) else
        f"Entry: <b>${sig.entry:.2f}</b> (today {sig.change_pct:+.1f}%)"
    )
    return (
        f"<b>#{rank} {sig.symbol}</b>  <b>Grade {sig.grade}</b>  (mode: {mode})\n"
        f"{entry_line}\n"
        f"Stop: <b>${sig.stop_loss:.2f}</b>  (risk {sig.risk_pct:.1f}%)\n"
        f"T1: <b>${sig.target1:.2f}</b> (+{sig.reward1_pct:.1f}%)  |  T2: <b>${sig.target2:.2f}</b> (+{sig.reward2_pct:.1f}%)\n"
        f"R:R T1 <b>{sig.risk_reward_t1:.1f}:1</b>  •  RS vs SPY <b>{sig.rs_vs_spy:+.1f}%</b>  •  RSI/Vol <b>{sig.rsi:.0f} / {sig.rvol:.1f}x</b>\n\n"
        f"<b>Why this setup:</b>\n{reasons_html}"
    )


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    universe = "sp500"
    if context.args:
        arg = context.args[0].lower()
        if arg in ("sp500", "snp500", "spy"):
            universe = "sp500"
        elif arg in ("nasdaq100", "ndx", "nasdaq"):
            universe = "nasdaq100"
        elif arg in ("watch", "watchlist", "wl"):
            universe = "watchlist"

    await update.message.reply_text(
        f"🔍 Scanning {universe} with mode <b>{CURRENT_MODE}</b> … (30-90s)",
        parse_mode=ParseMode.HTML
    )

    try:
        settings = _get_effective_settings()
        result = run_auto_pick(universe, limit=80, watch_count=5, settings=settings, mode=CURRENT_MODE)

        if not result.top_picks:
            await update.message.reply_text("No strong signals found in this run.")
            return

        # Store picks in user context for button callbacks (approve by index)
        context.user_data["last_picks"] = result.top_picks[:5]
        context.user_data["last_universe"] = universe

        # Send rich HTML for each top pick + action buttons
        for rank, sig in enumerate(result.top_picks[:5], 1):
            text = _format_pick_html(sig, rank, CURRENT_MODE)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve:{rank-1}"),
                    InlineKeyboardButton("❓ Why?", callback_data=f"why:{rank-1}"),
                ],
                [InlineKeyboardButton("📊 Full details", callback_data=f"details:{rank-1}")]
            ])
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

        if result.worth_watching:
            ww = ", ".join([f"{s.symbol}({s.grade})" for s in result.worth_watching[:4]])
            await update.message.reply_text(f"<i>Worth watching: {ww}</i>", parse_mode=ParseMode.HTML)

        await update.message.reply_text(
            "Use buttons above to approve or inspect. /active to see monitored trades. /setmode to change profile.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Scan failed: {e}")


# ---------------- Callback handlers (buttons) ----------------

async def _send_why(update_or_query, sig, rank: int):
    reasons = "\n".join([f"• {html.escape(r)}" for r in (sig.reasons or [])]) or "No detailed reasons recorded."
    text = (
        f"<b>#{rank} {sig.symbol} — Full Justification</b>\n\n"
        f"{reasons}\n\n"
        f"Entry ${sig.entry:.2f} | Stop ${sig.stop_loss:.2f} | T1 ${sig.target1:.2f} | T2 ${sig.target2:.2f}\n"
        f"Score {sig.score} | Grade {sig.grade} | RS {sig.rs_vs_spy:+.1f}%"
    )
    if hasattr(update_or_query, "message"):
        await update_or_query.message.reply_text(text, parse_mode=ParseMode.HTML)
    else:
        await update_or_query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    picks = context.user_data.get("last_picks", [])

    if data.startswith("approve:"):
        idx = int(data.split(":", 1)[1])
        if idx >= len(picks):
            await query.edit_message_text("Pick no longer available. Run /scan again.")
            return
        sig = picks[idx]
        try:
            trade_id = approve_trade(sig, mode=CURRENT_MODE, notes=f"Approved via Telegram bot from {context.user_data.get('last_universe', 'scan')}")
            await query.edit_message_text(
                f"✅ <b>APPROVED</b> {sig.symbol} (trade #{trade_id})\n"
                f"Now monitoring. Use /active to manage.",
                parse_mode=ParseMode.HTML
            )
            # Immediately check once
            updates = monitor_active_trades()
            for u in updates:
                if u["trade_id"] == trade_id:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"📈 Initial monitor for {sig.symbol}: {u['event']}\n{u['recommendation']}",
                        parse_mode=ParseMode.HTML
                    )
        except Exception as e:
            await query.edit_message_text(f"Approve failed: {e}")

    elif data.startswith("why:"):
        idx = int(data.split(":", 1)[1])
        if idx < len(picks):
            await _send_why(query, picks[idx], idx + 1)
        else:
            await query.edit_message_text("Details expired. /scan again.")

    elif data.startswith("details:"):
        idx = int(data.split(":", 1)[1])
        if idx < len(picks):
            sig = picks[idx]
            text = _format_pick_html(sig, idx+1, CURRENT_MODE)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text("Expired. Run /scan.")

    elif data.startswith("active:"):
        # e.g. active:close:5 or active:recommend:3
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        try:
            tid = int(parts[2])
        except (IndexError, ValueError):
            await query.edit_message_text("Invalid trade id.")
            return

        trade = get_active_trade(tid)
        if not trade:
            await query.edit_message_text("Trade not found (already closed?).")
            return

        if action == "close":
            close_trade(tid, reason="Closed via Telegram bot")
            await query.edit_message_text(f"🔒 Trade #{tid} {trade['symbol']} closed.")
        elif action == "recommend":
            updates = monitor_active_trades()
            rec = "No new recommendation."
            for u in updates:
                if u["trade_id"] == tid:
                    rec = u["recommendation"]
                    break
            await query.edit_message_text(
                f"<b>Recommendation for {trade['symbol']} (#{tid})</b>\n\n{rec}",
                parse_mode=ParseMode.HTML
            )
        else:
            # default: show current status
            await query.edit_message_text(
                f"<b>Active #{tid} {trade['symbol']}</b>\n"
                f"Status: {trade['status']} | Entry ${trade['entry']:.2f} | Last ${trade.get('last_price', '?')}\n"
                f"Notes: {trade.get('notes', '')[:200]}",
                parse_mode=ParseMode.HTML
            )


async def active_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List active approved trades with management buttons."""
    trades = get_active_trades()
    if not trades:
        await update.message.reply_text("No active trades. Approve some from /scan results.")
        return

    for t in trades[:8]:
        tid = t["id"]
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Recommend", callback_data=f"active:recommend:{tid}"),
                InlineKeyboardButton("❌ Close", callback_data=f"active:close:{tid}"),
            ],
            [InlineKeyboardButton("📋 Status", callback_data=f"active:status:{tid}")]
        ])
        text = (
            f"<b>#{tid} {t['symbol']}</b> — {t['status'].upper()}\n"
            f"Entry ${t['entry']:.2f} → SL ${t['stop_loss']:.2f} | T1 ${t['target1']:.2f} / T2 ${t['target2']:.2f}\n"
            f"Approved: {t.get('approved_ts', '')[:16]} | Mode: {t.get('mode', '')}"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually check all active trades for price updates, status changes (T1/T2/stop), and get recommendations.
    Monitoring is on-demand — run this whenever you want fresh data. No automatic background checks."""
    await update.message.reply_text("⏳ Running manual monitor on active trades...")

    def _notify(u: dict):
        asyncio.create_task(
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🔔 <b>{u['event']}</b> — {u['symbol']} @ ${u['price']}\n{u['recommendation']}",
                parse_mode=ParseMode.HTML
            )
        )

    updates = monitor_active_trades(notify_callback=_notify)
    if not updates:
        await update.message.reply_text("No changes on active trades.")
        return

    for u in updates:
        if not u.get("changed"):
            continue
        # already notified via callback for changes; still summarize
        pass
    await update.message.reply_text(f"Monitor complete. {len(updates)} updates processed.")


async def scheduled_monitor(context: ContextTypes.DEFAULT_TYPE):
    """Background job: runs monitor_active_trades periodically and notifies subscribed chats on changes.
    This makes monitoring 'live' for the bot (runs every 10 minutes by default).
    """
    bot = context.bot
    chats = context.bot_data.get("monitor_chats", set())
    if not chats:
        return

    # Use a notify that sends to all subscribed chats
    notified_chats = set()

    def notify(u: dict):
        for chat_id in list(chats):
            if chat_id in notified_chats:
                continue
            try:
                # Only notify on real changes (not every PRICE CHECK)
                if u.get("changed") or u.get("event") not in ("PRICE CHECK", "PRICE UPDATE"):
                    asyncio.create_task(
                        bot.send_message(
                            chat_id=chat_id,
                            text=f"🔔 <b>{u['event']}</b> — {u['symbol']} @ ${u['price']}\n{u['recommendation']}",
                            parse_mode=ParseMode.HTML
                        )
                    )
                    notified_chats.add(chat_id)
            except Exception as e:
                print(f"[scheduled_monitor] Failed to notify {chat_id}: {e}")

    updates = monitor_active_trades(notify_callback=notify)

    # Optional: log to console for the bot owner
    if updates:
        print(f"[scheduled_monitor] {len(updates)} updates at {datetime.now().strftime('%H:%M')}")


async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chats = context.bot_data.setdefault("monitor_chats", set())
    if update.effective_chat.id in chats:
        chats.remove(update.effective_chat.id)
        await update.message.reply_text("🔕 Unsubscribed from automatic monitoring notifications.")
    else:
        await update.message.reply_text("You were not subscribed.")


async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wl = load_watchlist()
    await update.message.reply_text(
        "📋 Watchlist (" + str(len(wl)) + "):\n" + ", ".join(wl[:30]) +
        ("\n..." if len(wl) > 30 else "")
    )


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add AAPL MSFT NVDA")
        return
    added = add_symbols(context.args)
    await update.message.reply_text(f"✅ Added. Watchlist now has {len(added)} symbols.")


async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /remove AAPL")
        return
    remaining = remove_symbols(context.args)
    await update.message.reply_text(f"✅ Removed. Watchlist now has {len(remaining)} symbols.")


async def journal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = 8
    if context.args:
        try:
            n = max(1, min(30, int(context.args[0])))
        except ValueError:
            pass

    df = load_journal()
    if df.empty:
        await update.message.reply_text("No journal entries yet. Run a /scan first.")
        return

    recent = df.tail(n)
    lines = [f"<b>Recent journal (last {len(recent)})</b>"]
    for _, row in recent.iterrows():
        sym = row.get("symbol", "?")
        grade = row.get("grade", "")
        status = row.get("outcome_status", "") or "pending"
        entry = row.get("entry", "")
        pl = row.get("pct_from_entry", "")
        pl_str = f"{pl:+.1f}%" if pl not in ("", None) else ""
        lines.append(f"{sym} {grade} | entry ${entry} | {status} {pl_str}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Try /help")


def main():
    if not BOT_TOKEN:
        print("ERROR: Set TELEGRAM_BOT_TOKEN environment variable (get one from @BotFather on Telegram).")
        print("Example: set TELEGRAM_BOT_TOKEN=123456:ABC-DEF in your shell or hosting dashboard.")
        sys.exit(1)

    print("Starting US Stock Scanner Telegram bot...")
    print(f"Using mode: {CURRENT_MODE}")
    print(f"Turso remote? { 'yes' if os.getenv('TURSO_DATABASE_URL') else 'no (local SQLite)' }")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("modes", modes_cmd))
    app.add_handler(CommandHandler("setmode", setmode_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("journal", journal_cmd))
    app.add_handler(CommandHandler("active", active_cmd))
    app.add_handler(CommandHandler("monitor", monitor_cmd))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))

    # Button callbacks (approve, why, active management, etc.)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Fallback
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Error handler to prevent crashes and log issues (e.g. bad HTML)
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        print(f"Exception while handling an update: {context.error}")
        # You can add more logging or notify admin here
        # For production, consider sending a friendly message to user if possible

    app.add_error_handler(error_handler)

    # Schedule background monitoring job (every 10 minutes)
    # This makes monitoring "live" for subscribed chats (Option A)
    if app.job_queue:
        app.job_queue.run_repeating(
            scheduled_monitor,
            interval=600,   # 10 minutes
            first=60,       # start after 1 minute
            name="active_trades_monitor"
        )
        print("Background monitoring job scheduled (every 10 min for subscribed chats).")
    else:
        print("Warning: JobQueue not available. Background monitoring disabled. "
              "Install with: pip install 'python-telegram-bot[job-queue]' if needed.")

    print("Bot is running (polling). Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
