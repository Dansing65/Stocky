# 📈 StockSentinel v2 — News + Technical Discord Bot

StockSentinel v2 combines **real-time news catalyst detection** with **technical analysis** to find the highest-conviction trade setups. When both a news catalyst and a technical signal fire on the same ticker at the same time, it posts a special ⚡ **High Conviction Combo Alert**.

---

## 🧠 How It Works

```
Every 10 minutes (pre-market → after-hours):
  📰 Fetch news from Finnhub + NewsAPI + SEC EDGAR
      ↓
  🤖 Claude AI reads each headline and scores it 1-10
      ↓
  📣 High-scoring catalysts (≥6/10) get posted to Discord

Every 15 minutes (market hours only):
  📊 Technical scan runs 4 strategies on your watchlist
      ↓
  If the same ticker has BOTH a news catalyst + tech signal:
      ↓
  ⚡ HIGH CONVICTION COMBO ALERT posted (highest priority)
```

---

## 🚀 Setup Guide

### Step 1 — Get Your API Keys (all free tiers available)

**Anthropic (Claude AI) — Required for news scoring**
1. Go to **console.anthropic.com**
2. Sign up → go to **API Keys** → click **Create Key**
3. Copy the key

**Finnhub — Real-time stock news**
1. Go to **finnhub.io**
2. Sign up for free → go to **Dashboard**
3. Copy your API key

**NewsAPI — Broad financial news**
1. Go to **newsapi.org**
2. Click **Get API Key** → sign up free
3. Copy your API key

---

### Step 2 — Discord Setup

1. Go to **discord.com/developers/applications**
2. Create a new application → go to **Bot**
3. Enable **Message Content Intent**
4. Copy your bot token
5. Go to **OAuth2 → URL Generator** → check `bot`
6. Under permissions check: Send Messages, Embed Links, Read Message History, View Channels
7. Open the generated URL → add bot to your server

**Optional: Create two channels in Discord**
- `#trade-alerts` — for technical signals
- `#news-catalyst` — for news alerts
Right-click each → Copy Channel ID

---

### Step 3 — Configure .env

```bash
cp .env.example .env
```

Open `.env` and fill in:
```
DISCORD_TOKEN=your_discord_bot_token
ALERTS_CHANNEL_ID=your_alerts_channel_id
NEWS_CHANNEL_ID=your_news_channel_id
ANTHROPIC_API_KEY=your_anthropic_key
FINNHUB_API_KEY=your_finnhub_key
NEWS_API_KEY=your_newsapi_key
```

---

### Step 4 — Install & Run

```bash
pip install -r requirements.txt
python bot.py
```

---

## 💬 Commands

| Command | Description |
|---|---|
| `!scan` | Immediate technical pattern scan |
| `!news` | Immediate news catalyst scan |
| `!news AAPL` | News scan filtered to one ticker |
| `!quote NVDA` | Live quote for any ticker |
| `!watchlist` | View all monitored tickers |
| `!addwatch TSLA` | Add ticker (mod permission required) |
| `!status` | Bot health & scan intervals |
| `!help` | All commands |

---

## 📡 Alert Types

### 🟢/🔴 Technical Signal
Fires when a chart pattern meets the confidence threshold:
- RSI Oversold Bounce
- MACD Crossover
- Volume Breakout
- EMA 9/21 Cross

### 📰 News Catalyst
Fires when Claude AI scores a headline ≥ 6/10:
- Earnings beats/misses
- FDA approvals/rejections
- Analyst upgrades/downgrades
- Insider buying clusters
- Major contract wins
- SEC 8-K filings

### ⚡ Combo Alert (Highest Conviction)
Fires when the **same ticker** has BOTH a news catalyst AND a technical setup at the same time. This is the signal to pay the most attention to.

---

## 🛠️ Customization

**Change minimum catalyst score** (in `.env`):
```
MIN_CATALYST_SCORE=7   # stricter — fewer but higher quality alerts
MIN_CATALYST_SCORE=5   # looser — more alerts
```

**Change scan frequency** (in `.env`):
```
NEWS_INTERVAL_MINUTES=5    # scan news every 5 min
SCAN_INTERVAL_MINUTES=30   # tech scan every 30 min
```

**Edit your watchlist**: modify `watchlist.txt` (one ticker per line) or use `!addwatch`

---

## ☁️ Running 24/7 on Railway

1. Push files to a **private GitHub repo**
2. Go to **railway.app** → New Project → Deploy from GitHub
3. Add all your `.env` variables in Railway's **Variables** tab
4. Set start command to `python bot.py`
5. Deploy — done!

---

## ⚠️ Disclaimer

> This bot is for educational and informational purposes only. It does not constitute financial advice. Always do your own research. Past signals do not guarantee future results. Never risk money you cannot afford to lose.
