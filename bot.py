"""
StockSentinel v2 — Discord Trading Bot
Combines real-time news catalyst detection with technical confirmation.
"""

import discord
from discord.ext import commands, tasks
import asyncio
import os
import logging
from dotenv import load_dotenv
from scanner import StockScanner
from news_scanner import NewsScanner
from datetime import datetime, time
import yfinance as yf
import pytz

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN             = os.getenv("DISCORD_TOKEN")
ALERTS_CHANNEL    = int(os.getenv("ALERTS_CHANNEL_ID", "0"))
NEWS_CHANNEL      = int(os.getenv("NEWS_CHANNEL_ID", str(os.getenv("ALERTS_CHANNEL_ID", "0"))))
TECH_SCAN_MINS    = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))
NEWS_SCAN_MINS    = int(os.getenv("NEWS_INTERVAL_MINUTES", "10"))
MARKET_TZ         = pytz.timezone("America/New_York")
MARKET_OPEN       = time(9, 30)
MARKET_CLOSE      = time(16, 0)
PREMARKET_OPEN    = time(4, 0)   # news scan starts at pre-market

# ── Bot Setup ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot          = commands.Bot(command_prefix="!", intents=intents, help_command=None)
tech_scanner = StockScanner()
news_scanner_obj = None  # initialized on_ready


def is_market_open() -> bool:
    now = datetime.now(MARKET_TZ).time()
    return MARKET_OPEN <= now <= MARKET_CLOSE


def is_news_hours() -> bool:
    """News scan runs pre-market through after-hours."""
    now = datetime.now(MARKET_TZ).time()
    return PREMARKET_OPEN <= now <= time(20, 0)


def signal_color(sig: str) -> discord.Color:
    return discord.Color.green() if sig == "BUY" else discord.Color.red()


# ── Embed Builders ─────────────────────────────────────────────────────────────

def build_tech_embed(trade: dict) -> discord.Embed:
    sig   = trade["signal"]
    emoji = "🟢" if sig == "BUY" else "🔴"
    embed = discord.Embed(
        title=f"{emoji} TECHNICAL — {sig} Signal: {trade['ticker']}",
        description=trade.get("reason", "Technical setup detected"),
        color=signal_color(sig),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="📈 Entry",        value=f"**${trade['entry']:.2f}**",   inline=True)
    embed.add_field(name="🎯 Target",       value=f"**${trade['target']:.2f}**",  inline=True)
    embed.add_field(name="🛑 Stop Loss",    value=f"**${trade['stop']:.2f}**",    inline=True)

    rr = abs(trade["target"] - trade["entry"]) / max(abs(trade["entry"] - trade["stop"]), 0.01)
    embed.add_field(name="⚖️ Risk/Reward",  value=f"**1 : {rr:.1f}**",           inline=True)
    embed.add_field(name="📊 Confidence",   value=f"**{trade['confidence']}%**",  inline=True)
    embed.add_field(name="⏱️ Timeframe",    value=f"**{trade['timeframe']}**",    inline=True)

    if trade.get("indicators"):
        embed.add_field(
            name="🔍 Indicators",
            value="\n".join(f"• {i}" for i in trade["indicators"]),
            inline=False,
        )
    embed.set_footer(text="StockSentinel v2 • Technical Signal • Not financial advice")
    return embed


def build_news_embed(catalyst: dict) -> discord.Embed:
    sig        = catalyst.get("signal", "BUY")
    score      = catalyst.get("catalyst_score", 0)
    emoji      = "🟢" if sig == "BUY" else "🔴"
    fire       = "🔥" * min(score // 3, 3)  # 🔥 = score 3+, 🔥🔥 = 6+, 🔥🔥🔥 = 9+

    embed = discord.Embed(
        title=f"{emoji} NEWS CATALYST {fire} — {sig}: {catalyst['ticker']}",
        description=f"**{catalyst.get('headline', '')}**",
        color=signal_color(sig),
        timestamp=datetime.utcnow(),
        url=catalyst.get("url") or None,
    )

    embed.add_field(name="📰 Source",         value=catalyst.get("source", "N/A"),                   inline=True)
    embed.add_field(name="🏷️ Catalyst Type",  value=catalyst.get("catalyst_type", "N/A"),            inline=True)
    embed.add_field(name="💥 Impact Score",   value=f"**{score}/10**",                               inline=True)
    embed.add_field(name="📊 AI Confidence",  value=f"**{catalyst.get('confidence', 0)}%**",          inline=True)
    embed.add_field(name="📉 Expected Move",  value=f"**~{catalyst.get('expected_move_pct', 0):.1f}%**", inline=True)
    embed.add_field(name="⏱️ Timeframe",      value=f"**{catalyst.get('timeframe', 'N/A')}**",        inline=True)

    if catalyst.get("reason"):
        embed.add_field(name="🧠 Why It Matters", value=catalyst["reason"],  inline=False)

    if catalyst.get("entry_strategy"):
        embed.add_field(name="🎯 Entry Strategy", value=catalyst["entry_strategy"], inline=False)

    if catalyst.get("risk_factors"):
        embed.add_field(name="⚠️ Risk Factors",   value=catalyst["risk_factors"],   inline=False)

    if catalyst.get("published"):
        embed.add_field(name="🕐 Published",      value=catalyst["published"],       inline=True)

    embed.set_footer(text="StockSentinel v2 • News Catalyst • Not financial advice")
    return embed


def build_combo_embed(catalyst: dict, tech: dict) -> discord.Embed:
    """Special embed when news catalyst AND technical signal align on same ticker."""
    sig   = catalyst.get("signal", "BUY")
    emoji = "🟢" if sig == "BUY" else "🔴"
    score = catalyst.get("catalyst_score", 0)

    embed = discord.Embed(
        title=f"⚡ HIGH CONVICTION {emoji} {sig}: {catalyst['ticker']}",
        description=(
            f"**News catalyst + technical confirmation aligned!**\n"
            f"_{catalyst.get('headline', '')}_"
        ),
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )

    # News side
    embed.add_field(name="📰 Catalyst",      value=catalyst.get("catalyst_type", "N/A"),             inline=True)
    embed.add_field(name="💥 Impact",        value=f"**{score}/10**",                               inline=True)
    embed.add_field(name="📉 Expected Move", value=f"**~{catalyst.get('expected_move_pct', 0):.1f}%**", inline=True)

    # Technical side
    embed.add_field(name="📈 Entry",         value=f"**${tech['entry']:.2f}**",                      inline=True)
    embed.add_field(name="🎯 Target",        value=f"**${tech['target']:.2f}**",                     inline=True)
    embed.add_field(name="🛑 Stop Loss",     value=f"**${tech['stop']:.2f}**",                       inline=True)

    rr = abs(tech["target"] - tech["entry"]) / max(abs(tech["entry"] - tech["stop"]), 0.01)
    combined_conf = min(int((catalyst.get("confidence", 70) + tech.get("confidence", 70)) / 2) + 10, 95)

    embed.add_field(name="⚖️ Risk/Reward",   value=f"**1 : {rr:.1f}**",                             inline=True)
    embed.add_field(name="🏆 Combined Conf", value=f"**{combined_conf}%**",                          inline=True)
    embed.add_field(name="⏱️ Timeframe",     value=f"**{tech.get('timeframe', '1-5 days')}**",       inline=True)

    if catalyst.get("reason"):
        embed.add_field(name="🧠 Thesis",    value=catalyst["reason"],                               inline=False)
    if catalyst.get("risk_factors"):
        embed.add_field(name="⚠️ Risks",     value=catalyst["risk_factors"],                         inline=False)

    embed.set_footer(text="StockSentinel v2 • ⚡ Combo Signal — News + Technical • Not financial advice")
    return embed


# ── Scan Loops ─────────────────────────────────────────────────────────────────

@tasks.loop(minutes=NEWS_SCAN_MINS)
async def news_scan_loop():
    if not is_news_hours():
        return

    channel = bot.get_channel(NEWS_CHANNEL)
    if channel is None:
        return

    log.info("Running news scan…")
    try:
        catalysts = await asyncio.to_thread(news_scanner_obj.scan)
    except Exception as exc:
        log.error(f"News scan error: {exc}")
        return

    if not catalysts:
        return

    # Also run a quick tech scan to check for combo signals
    tech_signals = {}
    if is_market_open():
        try:
            tech_list = await asyncio.to_thread(tech_scanner.scan)
            tech_signals = {t["ticker"]: t for t in tech_list}
        except Exception:
            pass

    header = discord.Embed(
        title="📡 News Scan Complete",
        description=f"Found **{len(catalysts)}** catalyst(s) — {datetime.now(MARKET_TZ).strftime('%H:%M %Z')}",
        color=discord.Color.blurple(),
    )
    await channel.send(embed=header)

    for catalyst in catalysts:
        ticker = catalyst["ticker"]
        if ticker in tech_signals:
            # COMBO signal — both news and tech align
            await channel.send(embed=build_combo_embed(catalyst, tech_signals[ticker]))
        else:
            await channel.send(embed=build_news_embed(catalyst))
        await asyncio.sleep(0.5)


@tasks.loop(minutes=TECH_SCAN_MINS)
async def tech_scan_loop():
    if not is_market_open():
        return

    channel = bot.get_channel(ALERTS_CHANNEL)
    if channel is None:
        return

    log.info("Running technical scan…")
    try:
        signals = await asyncio.to_thread(tech_scanner.scan)
    except Exception as exc:
        log.error(f"Tech scan error: {exc}")
        return

    if not signals:
        return

    header = discord.Embed(
        title="📊 Technical Scan Complete",
        description=f"Found **{len(signals)}** setup(s) — {datetime.now(MARKET_TZ).strftime('%H:%M %Z')}",
        color=discord.Color.blurple(),
    )
    await channel.send(embed=header)
    for trade in signals:
        await channel.send(embed=build_tech_embed(trade))
        await asyncio.sleep(0.5)


@news_scan_loop.before_loop
@tech_scan_loop.before_loop
async def before_loops():
    await bot.wait_until_ready()


# ── Commands ───────────────────────────────────────────────────────────────────

@bot.command(name="scan")
async def cmd_scan(ctx):
    """Run an immediate technical scan."""
    msg = await ctx.send("🔍 Running technical scan…")
    try:
        signals = await asyncio.to_thread(tech_scanner.scan)
    except Exception as exc:
        await msg.edit(content=f"❌ Scan failed: {exc}")
        return
    await msg.delete()
    if not signals:
        await ctx.send("✅ No high-confidence technical setups right now.")
        return
    for trade in signals:
        await ctx.send(embed=build_tech_embed(trade))
        await asyncio.sleep(0.5)


@bot.command(name="news")
async def cmd_news(ctx, ticker: str = None):
    """Scan news right now. Optionally filter by ticker: !news AAPL"""
    msg = await ctx.send("📰 Scanning news…")
    try:
        catalysts = await asyncio.to_thread(news_scanner_obj.scan)
    except Exception as exc:
        await msg.edit(content=f"❌ News scan failed: {exc}")
        return
    await msg.delete()

    if ticker:
        catalysts = [c for c in catalysts if c["ticker"].upper() == ticker.upper()]

    if not catalysts:
        await ctx.send("✅ No high-impact news catalysts found right now.")
        return

    for c in catalysts:
        await ctx.send(embed=build_news_embed(c))
        await asyncio.sleep(0.5)


@bot.command(name="quote")
async def cmd_quote(ctx, ticker: str):
    """Live quote. Usage: !quote NVDA"""
    ticker = ticker.upper()
    try:
        info  = yf.Ticker(ticker).info
        hist  = yf.download(ticker, period="2d", interval="1d", progress=False, auto_adjust=True)
        if isinstance(hist.columns, __import__("pandas").MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        price = float(hist["Close"].iloc[-1])
        prev  = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
        chg   = (price - prev) / prev * 100

        def fmt(v):
            if not v: return "N/A"
            if v >= 1e12: return f"${v/1e12:.2f}T"
            if v >= 1e9:  return f"${v/1e9:.2f}B"
            return f"${v/1e6:.2f}M"

        color = discord.Color.green() if chg >= 0 else discord.Color.red()
        arrow = "▲" if chg >= 0 else "▼"
        embed = discord.Embed(title=f"📊 {ticker}", color=color, timestamp=datetime.utcnow())
        embed.add_field(name="Price",      value=f"**${price:.2f}**",                     inline=True)
        embed.add_field(name="Change",     value=f"{arrow} {chg:+.2f}%",                  inline=True)
        embed.add_field(name="Volume",     value=f"{int(hist['Volume'].iloc[-1]):,}",      inline=True)
        embed.add_field(name="52W High",   value=f"${info.get('fiftyTwoWeekHigh','N/A')}", inline=True)
        embed.add_field(name="52W Low",    value=f"${info.get('fiftyTwoWeekLow','N/A')}",  inline=True)
        embed.add_field(name="Market Cap", value=fmt(info.get("marketCap")),               inline=True)
        embed.set_footer(text="StockSentinel v2 • Data via yfinance")
        await ctx.send(embed=embed)
    except Exception as exc:
        await ctx.send(f"❌ Could not fetch **{ticker}**: {exc}")


@bot.command(name="watchlist")
async def cmd_watchlist(ctx):
    tickers = tech_scanner.watchlist
    embed = discord.Embed(
        title="👀 Watchlist",
        description=" | ".join(f"`{t}`" for t in tickers),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=f"{len(tickers)} symbols • Edit watchlist.txt to customize")
    await ctx.send(embed=embed)


@bot.command(name="addwatch")
@commands.has_permissions(manage_messages=True)
async def cmd_addwatch(ctx, ticker: str):
    ticker = ticker.upper()
    tech_scanner.add_to_watchlist(ticker)
    news_scanner_obj.watchlist = tech_scanner.watchlist
    await ctx.send(f"✅ **{ticker}** added to the watchlist.")


@bot.command(name="status")
async def cmd_status(ctx):
    open_str = "🟢 OPEN" if is_market_open() else "🔴 CLOSED"
    news_str = "🟢 ACTIVE" if is_news_hours() else "🔴 INACTIVE"
    embed = discord.Embed(title="🤖 StockSentinel v2 Status", color=discord.Color.blurple())
    embed.add_field(name="Market",          value=open_str,                              inline=True)
    embed.add_field(name="News Scanner",    value=news_str,                              inline=True)
    embed.add_field(name="Watchlist",       value=f"{len(tech_scanner.watchlist)} tickers", inline=True)
    embed.add_field(name="Tech Scan",       value=f"Every {TECH_SCAN_MINS} min",         inline=True)
    embed.add_field(name="News Scan",       value=f"Every {NEWS_SCAN_MINS} min",         inline=True)
    embed.add_field(name="Mode",            value="News + Technical",                    inline=True)
    await ctx.send(embed=embed)


@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(title="📖 StockSentinel v2 Commands", color=discord.Color.blurple())
    cmds = [
        ("!scan",          "Run immediate technical pattern scan"),
        ("!news",          "Run immediate news catalyst scan"),
        ("!news AAPL",     "Scan news for a specific ticker"),
        ("!quote NVDA",    "Get live quote for any ticker"),
        ("!watchlist",     "View all monitored tickers"),
        ("!addwatch TSLA", "Add ticker to watchlist (mod only)"),
        ("!status",        "Bot status & scan intervals"),
    ]
    for name, desc in cmds:
        embed.add_field(name=f"`{name}`", value=desc, inline=False)
    embed.set_footer(text="StockSentinel v2 • News + Technical • Not financial advice")
    await ctx.send(embed=embed)


# ── Events ─────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global news_scanner_obj
    news_scanner_obj = NewsScanner(tech_scanner.watchlist)
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="📰 news + 📈 charts")
    )
    tech_scan_loop.start()
    news_scan_loop.start()
    log.info(f"Both scan loops started.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ Missing argument. Try `!help`.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("🔒 You don't have permission to use that command.")
    else:
        log.error(f"Command error: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set in .env")
    bot.run(TOKEN)
