"""
StockSentinel Discord Bot
Scans the market and alerts on high-probability trade setups.
"""

import discord
from discord.ext import commands, tasks
import asyncio
import os
import logging
from dotenv import load_dotenv
from scanner import StockScanner
from datetime import datetime, time
import pytz

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN            = os.getenv("DISCORD_TOKEN")
ALERTS_CHANNEL   = int(os.getenv("ALERTS_CHANNEL_ID", "0"))
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))  # minutes
MARKET_TZ        = pytz.timezone("America/New_York")
MARKET_OPEN      = time(9, 30)
MARKET_CLOSE     = time(16, 0)

# ── Bot Setup ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
scanner = StockScanner()


def is_market_open() -> bool:
    now = datetime.now(MARKET_TZ).time()
    return MARKET_OPEN <= now <= MARKET_CLOSE


def signal_color(signal_type: str) -> discord.Color:
    return discord.Color.green() if signal_type == "BUY" else discord.Color.red()


def build_trade_embed(trade: dict) -> discord.Embed:
    """Turn a trade signal dict into a rich Discord embed."""
    sig   = trade["signal"]       # "BUY" | "SELL"
    emoji = "🟢" if sig == "BUY" else "🔴"

    embed = discord.Embed(
        title=f"{emoji}  {sig} Signal — {trade['ticker']}",
        description=trade.get("reason", "Technical setup detected"),
        color=signal_color(sig),
        timestamp=datetime.utcnow(),
    )

    embed.add_field(name="📈 Entry Price",   value=f"**${trade['entry']:.2f}**",  inline=True)
    embed.add_field(name="🎯 Price Target",  value=f"**${trade['target']:.2f}**", inline=True)
    embed.add_field(name="🛑 Stop Loss",     value=f"**${trade['stop']:.2f}**",   inline=True)

    rr = abs(trade["target"] - trade["entry"]) / abs(trade["entry"] - trade["stop"])
    embed.add_field(name="⚖️  Risk / Reward", value=f"**1 : {rr:.1f}**",         inline=True)
    embed.add_field(name="📊 Confidence",    value=f"**{trade['confidence']}%**",  inline=True)
    embed.add_field(name="⏱️  Timeframe",    value=f"**{trade['timeframe']}**",   inline=True)

    if trade.get("indicators"):
        embed.add_field(
            name="🔍 Indicators",
            value="\n".join(f"• {i}" for i in trade["indicators"]),
            inline=False,
        )

    embed.set_footer(text="StockSentinel • Not financial advice — DYOR")
    return embed


# ── Scheduled Scan ─────────────────────────────────────────────────────────────
@tasks.loop(minutes=SCAN_INTERVAL)
async def market_scan():
    if not is_market_open():
        log.info("Market closed — skipping scan.")
        return

    channel = bot.get_channel(ALERTS_CHANNEL)
    if channel is None:
        log.warning("Alerts channel not found. Check ALERTS_CHANNEL_ID in .env")
        return

    log.info("Running market scan…")
    try:
        signals = await asyncio.to_thread(scanner.scan)
    except Exception as exc:
        log.error(f"Scan error: {exc}")
        return

    if not signals:
        log.info("No setups found this cycle.")
        return

    header = discord.Embed(
        title="📡  Market Scan Complete",
        description=f"Found **{len(signals)}** trade setup(s) — {datetime.now(MARKET_TZ).strftime('%H:%M %Z')}",
        color=discord.Color.blurple(),
    )
    await channel.send(embed=header)

    for trade in signals:
        await channel.send(embed=build_trade_embed(trade))
        await asyncio.sleep(0.5)  # rate-limit friendly


@market_scan.before_loop
async def before_scan():
    await bot.wait_until_ready()


# ── Commands ───────────────────────────────────────────────────────────────────
@bot.command(name="scan")
async def cmd_scan(ctx):
    """Trigger an immediate market scan."""
    msg = await ctx.send("🔍 Running scan now…")
    try:
        signals = await asyncio.to_thread(scanner.scan)
    except Exception as exc:
        await msg.edit(content=f"❌ Scan failed: {exc}")
        return

    await msg.delete()
    if not signals:
        await ctx.send("✅ Scan complete — no high-confidence setups right now.")
        return

    await ctx.send(f"✅ Found **{len(signals)}** setup(s):")
    for trade in signals:
        await ctx.send(embed=build_trade_embed(trade))
        await asyncio.sleep(0.5)


@bot.command(name="quote")
async def cmd_quote(ctx, ticker: str):
    """Get a live quote for a ticker. Usage: !quote AAPL"""
    ticker = ticker.upper()
    try:
        data = await asyncio.to_thread(scanner.get_quote, ticker)
    except Exception as exc:
        await ctx.send(f"❌ Could not fetch quote for **{ticker}**: {exc}")
        return

    color = discord.Color.green() if data["change_pct"] >= 0 else discord.Color.red()
    arrow = "▲" if data["change_pct"] >= 0 else "▼"

    embed = discord.Embed(title=f"📊 {ticker}", color=color, timestamp=datetime.utcnow())
    embed.add_field(name="Price",  value=f"**${data['price']:.2f}**",                       inline=True)
    embed.add_field(name="Change", value=f"{arrow} {data['change_pct']:+.2f}%",             inline=True)
    embed.add_field(name="Volume", value=f"{data['volume']:,}",                              inline=True)
    embed.add_field(name="52W High", value=f"${data.get('week52_high', 'N/A')}",            inline=True)
    embed.add_field(name="52W Low",  value=f"${data.get('week52_low',  'N/A')}",            inline=True)
    embed.add_field(name="Market Cap", value=data.get("market_cap", "N/A"),                 inline=True)
    embed.set_footer(text="StockSentinel • Data via yfinance")
    await ctx.send(embed=embed)


@bot.command(name="watchlist")
async def cmd_watchlist(ctx):
    """Show the current watchlist being scanned."""
    tickers = scanner.watchlist
    embed = discord.Embed(
        title="👀 Current Watchlist",
        description=" | ".join(f"`{t}`" for t in tickers),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=f"{len(tickers)} symbols • Edit watchlist.txt to customize")
    await ctx.send(embed=embed)


@bot.command(name="addwatch")
@commands.has_permissions(manage_messages=True)
async def cmd_addwatch(ctx, ticker: str):
    """Add a ticker to the watchlist. Usage: !addwatch TSLA"""
    ticker = ticker.upper()
    scanner.add_to_watchlist(ticker)
    await ctx.send(f"✅ **{ticker}** added to the watchlist.")


@bot.command(name="status")
async def cmd_status(ctx):
    """Show bot status."""
    open_str = "🟢 OPEN" if is_market_open() else "🔴 CLOSED"
    embed = discord.Embed(title="🤖 StockSentinel Status", color=discord.Color.blurple())
    embed.add_field(name="Market",        value=open_str,                             inline=True)
    embed.add_field(name="Scan Interval", value=f"Every {SCAN_INTERVAL} min",         inline=True)
    embed.add_field(name="Watchlist",     value=f"{len(scanner.watchlist)} symbols",  inline=True)
    embed.add_field(name="Next Scan",     value=f"<t:{int(market_scan.next_iteration.timestamp())}:R>"
                    if market_scan.next_iteration else "N/A",                          inline=True)
    await ctx.send(embed=embed)


@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(title="📖 StockSentinel Commands", color=discord.Color.blurple())
    cmds = [
        ("!scan",          "Run an immediate market scan"),
        ("!quote <TICK>",  "Get a live quote for any ticker"),
        ("!watchlist",     "View all tickers being scanned"),
        ("!addwatch <T>",  "Add a ticker to the watchlist (mod only)"),
        ("!status",        "Bot status & next scan time"),
    ]
    for name, desc in cmds:
        embed.add_field(name=f"`{name}`", value=desc, inline=False)
    embed.set_footer(text="StockSentinel • Not financial advice")
    await ctx.send(embed=embed)


# ── Events ─────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="📈 the market")
    )
    market_scan.start()
    log.info(f"Scan loop started — every {SCAN_INTERVAL} minutes.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing argument. Try `!help`.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("🔒 You don't have permission to use that command.")
    else:
        log.error(f"Unhandled command error: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not set in .env")
    bot.run(TOKEN)
