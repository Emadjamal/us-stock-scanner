# US Stock Scanner

**One click** — scans the market and shows the **best long trades** with entry, stop loss, two targets, and reasons.

## Web UI (recommended)

**Double-click:** `start_ui.bat`

Or:

```powershell
cd C:\Users\Emad\Documents\Source\Repos\us-stock-scanner
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\start_ui.ps1
```

The UI will be available at:

- On the same machine: `http://localhost:8501`
- From other computers on your local network: `http://<machine-ip>:8501` (see below)

**To access from another computer on the same network:**
- The launchers now bind to `0.0.0.0` by default.
- On the machine running the app, find its IP with `ipconfig` (look for "IPv4 Address").
- From another PC on the LAN, open: `http://<ip-address>:8501`
  (example: `http://192.168.1.42:8501`)

**Security note:** This exposes the app to your local network with no authentication. Only do this on trusted networks.

## Deploying Publicly (Free / Cheap Hosting Options)

The project now supports multiple ways to make the scanner available on the internet. The **Telegram bot** is often the most practical "always useful" option for a stock scanner.

### Quick Comparison (2026)

| Option                  | UI?     | Always-on?          | Sleep / Cold Start      | Persistence (watchlist/journal/modes) | Best For                          | Difficulty | Cost          | Notes |
|-------------------------|---------|---------------------|-------------------------|---------------------------------------|-----------------------------------|------------|---------------|-------|
| **Streamlit Community Cloud** | Full Streamlit | No (sleeps) | ~12h inactivity        | Ephemeral (lost on sleep)            | Demos, sharing the nice UI       | Very easy  | Free         | Easiest for the existing `app.py`. Full scans can be slow due to CPU limits. |
| **Hugging Face Spaces** | Full   | Limited            | Sleeps                 | Ephemeral                            | AI-flavored demos                | Easy       | Free (limits)| Good Streamlit support, occasional ZeroGPU. |
| **Render / Railway / Fly.io** | Full or Bot | Hobby tiers limited | Render sleeps fast; Railway/Fly better on paid | Ephemeral unless you use external DB | More control than Streamlit Cloud | Medium     | Free tier + paid for 24/7 | Great for the Telegram bot (see below). |
| **Telegram Bot** (recommended for real use) | Chat only | Yes (with right platform) | None on good tiers     | **Excellent with Turso**             | Daily signals, watchlist management, low friction | Medium     | Free–$5/mo   | Users just chat with the bot. Supports all modes + full tuning. |
| **Local + Tunnel** (ngrok, Cloudflare Tunnel, Tailscale) | Full or Bot | Yes (your machine) | None                   | Full local SQLite                    | Personal use, maximum privacy & speed | Easy       | Free (or your electricity) | Run on a home PC / Raspberry Pi / always-on laptop. Expose via tunnel. |

**Critical for any cloud hosting**: The local `data/app.db` is great on your machine. On free PaaS the filesystem is ephemeral. **Use Turso** (see below) for true persistence.

### Deploying the Streamlit UI on Streamlit Community Cloud

This is the easiest way to get the full visual UI (with sidebar modes, watchlist management, active trades monitoring, journal, etc.) publicly accessible.

#### Prerequisites
- A free Turso database (strongly recommended — see "Turso" section below). Without it, all data (watchlist, custom modes, active trades, journal) will be lost every time the app sleeps.
- Your code pushed to a public GitHub repository.

#### Step-by-step Deployment
1. **Push your code to GitHub**
   - Make sure `data/app.db*`, `.venv/`, and any local secrets are in `.gitignore` (they should be).
   - Commit and push.

2. **Deploy on Streamlit Community Cloud**
   - Go to https://share.streamlit.io
   - Sign in with your GitHub account.
   - Click **New app**.
   - Select your repository.
   - Set **Main file path** to `app.py`.
   - (Optional) Give it a nice URL slug.
   - Click **Deploy**.

3. **Configure Secrets (for Turso persistence)**
   - After the first deploy, go to the app's menu (three dots) → **Settings** → **Secrets**.
   - Paste something like this (replace with your real Turso values):

     ```toml
     TURSO_DATABASE_URL = "libsql://your-db-name.turso.io"
     TURSO_AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
     ```

   - Click **Save**. The app will restart and switch to using the remote Turso database.

4. **Done**
   - Your app will be at something like `https://your-slug.streamlit.app`
   - Share the link. Anyone can open it.

#### Important Limitations (Free Community Cloud)
- The app sleeps after ~12 hours of no traffic (cold start can take 10-60 seconds).
- Resource limits (~1-2 GB RAM, limited CPU). Heavy S&P 500 scans may be slow or hit limits.
- No persistent local filesystem — **Turso is required** for watchlist, modes, active trades, and journal to survive sleeps/restarts.
- Public apps only (free tier). One private app is sometimes allowed.

#### What Works Well After Deploy
- All UI features: Strategy Mode (including custom modes), Watchlist CRUD, Approve trades from scan results, Active Trades monitoring (manual "Run monitor" button), Journal with outcomes.
- Data is shared if you also deploy the Telegram bot against the same Turso database.

#### Tips
- After deploying, test by approving a trade in the Scan tab, then going to the Journal tab and running the monitor button. The data should persist even after the app sleeps.
- You can update the app anytime by pushing to GitHub — Streamlit will auto-redeploy.
- For better performance on heavy scans, consider upgrading to a paid Streamlit plan later or using the Telegram bot as the primary interface.

If you run into issues (e.g. missing `libsql` package or import errors), check that your `requirements.txt` has `libsql` at the top level (it does in the current project).

### 2. Recommended for Daily Use: Telegram Bot

Much lighter than the full UI and perfect for getting actionable signals in chat.

**Features implemented**:
- `/scan sp500|nasdaq100|watchlist`
- `/watchlist`, `/add`, `/remove`
- `/modes`, `/setmode aggressive|swing|...|yourcustom`
- `/journal`
- Uses the exact same engine, modes, and storage as the UI/CLI.

**Run locally (fast test)**:
```powershell
pip install "python-telegram-bot>=21.0"
set TELEGRAM_BOT_TOKEN=123456:ABCDEF...   # from @BotFather
python bot.py
```

**For persistent public bot (free/cheap)**:
- **Railway** (very easy, good free tier for bots): `railway up` after linking repo + set env var `TELEGRAM_BOT_TOKEN`.
- **Fly.io**: Good always-on hobby machines.
- **Render**: Use paid "Always On" or it will sleep (bad for polling bots).
- Self-host on a $3–5/mo VPS or even a home machine + `systemd` + ngrok/Cloudflare Tunnel.

**Persistence**:
Set these two environment variables on your hosting platform:
```
TURSO_DATABASE_URL=libsql://your-db-name.turso.io
TURSO_AUTH_TOKEN=eyJ...
```
Then the bot (and future UI deploys) will share the exact same watchlist, custom modes, and journal.

See "Turso (libSQL) – The Best Persistence Companion" below.

### 3. Local Machine + Public Tunnel (Zero Hosting Cost)

```powershell
# Terminal 1
python -m streamlit run app.py --server.address 0.0.0.0

# Or the bot
python bot.py

# Terminal 2 (install ngrok or cloudflared)
ngrok http 8501
# or for the bot (if you add webhook support later)
```

Share the https ngrok URL. Your machine must stay on.

### Turso (libSQL) – The Best Persistence Companion (for any cloud option)

Because we refactored everything to clean SQLite in this project, switching to Turso is almost zero-code:

1. Sign up free at https://turso.tech (very generous free tier: several GB storage, hundreds of millions of reads).
2. Create a database.
3. Copy the `libsql://...` URL and auth token.
4. Set the two env vars above on **any** platform (Streamlit secrets, Railway, Fly, your VPS, etc.).
5. `libsql` is already in `requirements.txt`.

The same schema, all your custom modes, full journal history, watchlist, and active trades — everything just works remotely. No schema changes needed.

Local development continues to use the plain `data/app.db` file when the Turso variables are not set.

### Adding Turso support (already done)

The storage layer auto-detects `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` (or the `LIBSQL_*` aliases) and switches to the remote engine when present. Migration from old local files only happens for local SQLite.

### Other Tips for Publishing

- Add `libsql` and/or `python-telegram-bot` via `pip install -e .[cloud,telegram]` or the individual packages.
- Never commit `data/app.db*`, your real `TELEGRAM_BOT_TOKEN`, or Turso token.
- For Streamlit Cloud secrets: put Turso + any other keys in the Streamlit dashboard Secrets UI (or `.streamlit/secrets.toml` locally for testing).

### Quick Deploy – Telegram Bot on Railway (Recommended right now)

This is currently the best way to get your scanner "online" with working background monitoring of active trades.

1. **Push to GitHub**
   - Create a new (public or private) repo.
   - Push your code (make sure `data/app.db*` is ignored – it already is in `.gitignore`).

2. **Create a Turso database** (for persistence)
   - Go to https://turso.tech → Sign up (free).
   - Create a new database.
   - Copy:
     - `TURSO_DATABASE_URL` (looks like `libsql://your-db.turso.io`)
     - `TURSO_AUTH_TOKEN`

3. **Deploy on Railway**
   - Go to https://railway.app
   - New Project → Deploy from GitHub repo.
   - Railway will detect the `Procfile` (I added one: `web: python bot.py`).
   - Go to **Variables** tab and add these three:
     ```
     TELEGRAM_BOT_TOKEN=123456:AAF...          # from @BotFather
     TURSO_DATABASE_URL=libsql://...
     TURSO_AUTH_TOKEN=eyJ...
     ```
   - Deploy.

4. **Test**
   - Your bot should be reachable via the username you set on BotFather.
   - Try `/start`, `/scan sp500`, approve a trade.
   - Background monitoring (every 10 min) should now be active and will message you when targets/stops are hit.

**Note**: The background job only works while the Railway service is running. On free tiers it can sleep after inactivity — you may need to hit the bot occasionally or upgrade.

### Deploying the Streamlit UI (optional, as a second app)

- Go to https://share.streamlit.io
- Deploy from the same GitHub repo, main file = `app.py`
- In the app settings → **Secrets**, paste:
  ```toml
  TURSO_DATABASE_URL = "libsql://..."
  TURSO_AUTH_TOKEN = "eyJ..."
  ```
- The UI will now read/write the same data as the bot (watchlist, modes, active trades, journal).

You can run the bot and the UI as two separate services sharing one Turso database.

---

Ready when you are. Tell me:
- Do you want me to create a `railway.toml` with specific settings?
- Do you want step-by-step screenshots-style instructions for Turso + Railway?
- Or do you prefer deploying the Streamlit UI first?

Just say the word and we'll get it live.

| In the app | What to do |
|------------|------------|
| Sidebar → **Market / Watchlist / Single ticker** | Choose what to scan |
| **Strategy Mode** dropdown | Choose Default / Conservative / Swing / Aggressive / Breakout (or Custom) |
| **Watchlist** tab | Add/remove your symbols |
| **Journal** tab | Past signals & win rate |

## Setup (once)

```powershell
pip install -e .
```

## Scan one ticker or your watchlist

**UI:** Sidebar → **Single ticker** or **My watchlist** (manage symbols under **Watchlist** tab)

**Command line:**

```powershell
.\scan.ps1 -Symbol NVDA
.\scan.ps1 -Watchlist
.\scan.ps1 -Universe nasdaq100
# With a tuning mode
python -m us_stock_scanner --mode aggressive -u sp500
python -m us_stock_scanner --mode swing --symbol AAPL
```

```powershell
python -m us_stock_scanner --symbol AAPL
python -m us_stock_scanner --watchlist
python -m us_stock_scanner -u watchlist
```

Watchlist / modes / journal are stored in SQLite: `data/app.db` (auto-migrates old `data/watchlist.txt`, `signals_log.csv`, `custom_modes.yaml` on first use; fully editable via UI tabs + CLI).

## Signal journal

Every scan can save top 3 picks + watchlist runners to the journal (SQLite `signals_log` table; exportable as CSV from UI).

| Outcome | Meaning |
|---------|---------|
| `hit_t1` / `hit_t2` | Target reached |
| `stopped` | Hit stop loss |
| `not_filled` | Limit entry never touched |

**Disclaimer:** For education only. Not financial advice.