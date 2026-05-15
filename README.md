# 📈 StockSentinel — Discord Trading Bot

StockSentinel scans the stock market every 15 minutes during market hours and posts high-confidence trade setups directly to your Discord server, complete with **entry price**, **price target**, and **stop loss**.

---

## 🚀 Quick Start (5 steps)

### Step 1 — Create a Discord Bot

1. Go to <https://discord.com/developers/applications>
2. Click **New Application** → give it a name (e.g. "StockSentinel")
3. Open the **Bot** tab → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable:
   - ✅ Message Content Intent
5. Click **Reset Token** → copy the token (keep it secret!)

### Step 2 — Add the Bot to Your Server

1. In the Developer Portal, go to **OAuth2 → URL Generator**
2. Check `bot` under Scopes
3. Under Bot Permissions, check:
   - `Send Messages`
   - `Embed Links`
   - `Read Message History`
   - `View Channels`
4. Copy the generated URL, open it in your browser, and add the bot to your server

### Step 3 — Get Your Alerts Channel ID

1. In Discord, open **User Settings → Advanced** → enable **Developer Mode**
2. Right-click the channel where you want trade alerts → **Copy Channel ID**

### Step 4 — Configure the Bot

```bash
# Copy the example env file
cp .env.example .env

# Edit .env and fill in your values
DISCORD_TOKEN=your_bot_token_here
ALERTS_CHANNEL_ID=your_channel_id_here
SCAN_INTERVAL_MINUTES=15   # how often to scan (default: every 15 min)
```

### Step 5 — Install & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Start the bot
python bot.py
```

You should see:
```
[INFO] Logged in as StockSentinel#1234
[INFO] Scan loop started — every 15 minutes.
```

---

## 💬 Commands

| Command | Description |
|---|---|
| `!scan` | Run an immediate market scan |
| `!quote AAPL` | Get a live quote for any ticker |
| `!watchlist` | See all tickers being monitored |
| `!addwatch TSLA` | Add a ticker (mod permission required) |
| `!status` | Show bot status & next scheduled scan |
| `!help` | List all commands |

---

## 📡 How Scanning Works

The bot runs **4 technical strategies** on every ticker in your watchlist:

| Strategy | Signal | Logic |
|---|---|---|
| **RSI Oversold Bounce** | BUY | RSI(14) < 30, reverting upward |
| **MACD Crossover** | BUY / SELL | MACD line crosses signal line |
| **Volume Breakout** | BUY | Price breaks 20-day high on 1.8× avg volume |
| **EMA 9/21 Cross** | BUY / SELL | Short-term EMA crosses medium-term EMA |

Each setup is scored for **confidence (0–100%)**. Only setups scoring ≥ 60% are posted.

### Entry / Target / Stop Calculation

All levels use **ATR (Average True Range)** to size properly to each ticker's volatility:

```
Entry  = current close price
Target = Entry + (ATR × 2.0)   for BUY
Stop   = Entry − (ATR × 1.0)   for BUY
```
This always produces at least a **2:1 risk-to-reward ratio**.

---

## 🛠️ Customization

### Change the watchlist
Edit `watchlist.txt` — one ticker per line. Or use `!addwatch` in Discord.

### Change scan frequency
Set `SCAN_INTERVAL_MINUTES` in `.env`. Minimum recommended: 5 minutes.

### Adjust confidence threshold
In `scanner.py`, change `MIN_CONFIDENCE = 60` (higher = fewer, higher-quality alerts).

### Adjust risk/reward sizing
In `scanner.py`:
```python
ATR_MULT_TARGET = 2.0   # higher = wider target
ATR_MULT_STOP   = 1.0   # higher = wider stop
```

---

## ☁️ Running 24/7

To keep the bot running continuously, host it on a server:

**Railway (easiest — free tier available)**
```bash
railway init
railway up
```

**Fly.io**
```bash
fly launch
fly deploy
```

**VPS / Linux server**
```bash
# Using screen
screen -S stocksentinel
python bot.py
# Ctrl+A then D to detach

# Or use systemd / pm2 for production
```

---

## ⚠️ Disclaimer

> **This bot is for educational and informational purposes only. It does not constitute financial advice. Always do your own research before making any investment decisions. Past technical signals do not guarantee future results.**

---

## 📦 Dependencies

- `discord.py` — Discord API wrapper
- `yfinance` — Free market data (Yahoo Finance)
- `pandas` / `numpy` — Data manipulation & indicator math
- `python-dotenv` — Environment variable management
- `pytz` — Timezone handling for market hours
