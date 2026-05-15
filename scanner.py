"""
scanner.py — Market scanning engine for StockSentinel

Strategy mix:
  1. RSI Oversold Bounce       — RSI < 30 + price near support
  2. MACD Bullish Crossover    — MACD line crosses above signal
  3. Breakout with Volume      — Price breaks 20-day high on 2× avg volume
  4. EMA Golden Cross (short)  — 9 EMA crosses above 21 EMA
  5. Bearish Reversal (short)  — RSI > 70 + bearish engulfing candle
"""

import yfinance as yf
import pandas as pd
import numpy as np
import logging
import os

log = logging.getLogger(__name__)

WATCHLIST_FILE = "watchlist.txt"
DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
    "META", "GOOGL", "AMD", "SPY",  "QQQ",
    "SOFI", "PLTR", "COIN", "RBLX", "SNAP",
    "NIO",  "F",    "BAC",  "JPM",  "XOM",
]

MIN_CONFIDENCE = 60   # Only alert on setups scoring ≥ this
ATR_MULT_TARGET = 2.0  # Target = entry ± ATR × this
ATR_MULT_STOP   = 1.0  # Stop   = entry ∓ ATR × this


# ── Indicators ────────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast   = series.ewm(span=fast, adjust=False).mean()
    ema_slow   = series.ewm(span=slow, adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


# ── Scanner ───────────────────────────────────────────────────────────────────

class StockScanner:
    def __init__(self):
        self.watchlist = self._load_watchlist()

    # ── Watchlist management ──────────────────────────────────────────────────

    def _load_watchlist(self) -> list[str]:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE) as f:
                tickers = [l.strip().upper() for l in f if l.strip()]
            if tickers:
                return tickers
        # Write default and return it
        self._save_watchlist(DEFAULT_WATCHLIST)
        return list(DEFAULT_WATCHLIST)

    def _save_watchlist(self, tickers: list[str]):
        with open(WATCHLIST_FILE, "w") as f:
            f.write("\n".join(tickers))

    def add_to_watchlist(self, ticker: str):
        if ticker not in self.watchlist:
            self.watchlist.append(ticker)
            self._save_watchlist(self.watchlist)

    # ── Data fetching ─────────────────────────────────────────────────────────

    def _fetch(self, ticker: str, period="3mo", interval="1d") -> pd.DataFrame | None:
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             progress=False, auto_adjust=True)
            if df.empty or len(df) < 30:
                return None
            # Flatten multi-level columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception as exc:
            log.warning(f"Failed to fetch {ticker}: {exc}")
            return None

    def get_quote(self, ticker: str) -> dict:
        info = yf.Ticker(ticker).info
        df   = self._fetch(ticker, period="5d")
        price = df["Close"].iloc[-1] if df is not None else info.get("currentPrice", 0)
        prev  = df["Close"].iloc[-2] if df is not None and len(df) > 1 else price
        chg   = (price - prev) / prev * 100 if prev else 0

        def fmt_cap(v):
            if not v: return "N/A"
            if v >= 1e12: return f"${v/1e12:.2f}T"
            if v >= 1e9:  return f"${v/1e9:.2f}B"
            return f"${v/1e6:.2f}M"

        return {
            "price":       round(float(price), 2),
            "change_pct":  round(float(chg), 2),
            "volume":      int(df["Volume"].iloc[-1]) if df is not None else 0,
            "week52_high": round(float(info.get("fiftyTwoWeekHigh", 0)), 2),
            "week52_low":  round(float(info.get("fiftyTwoWeekLow",  0)), 2),
            "market_cap":  fmt_cap(info.get("marketCap")),
        }

    # ── Signal detection ──────────────────────────────────────────────────────

    def _check_rsi_bounce(self, ticker, df) -> dict | None:
        """RSI < 30 (oversold) with a bullish candle today."""
        r   = rsi(df["Close"])
        _atr = atr(df)
        if len(r) < 2: return None

        prev_rsi  = float(r.iloc[-2])
        today_rsi = float(r.iloc[-1])
        close     = float(df["Close"].iloc[-1])
        _atr_val  = float(_atr.iloc[-1])

        if prev_rsi < 30 and today_rsi > prev_rsi:
            # Bullish engulfing check
            open_today  = float(df["Open"].iloc[-1])
            open_prev   = float(df["Open"].iloc[-2])
            close_prev  = float(df["Close"].iloc[-2])
            bullish_eng = open_today < close_prev and close > open_prev

            confidence = 65 + (5 if bullish_eng else 0) + max(0, int((30 - prev_rsi)))
            confidence = min(confidence, 95)

            return {
                "ticker":     ticker,
                "signal":     "BUY",
                "entry":      round(close, 2),
                "target":     round(close + _atr_val * ATR_MULT_TARGET, 2),
                "stop":       round(close - _atr_val * ATR_MULT_STOP,   2),
                "confidence": confidence,
                "timeframe":  "1–3 days",
                "reason":     f"RSI Oversold Bounce — RSI was {prev_rsi:.1f}",
                "indicators": [
                    f"RSI(14): {today_rsi:.1f}  (was {prev_rsi:.1f})",
                    f"ATR(14): ${_atr_val:.2f}",
                    "Bullish engulfing candle" if bullish_eng else "Candle reversal",
                ],
            }
        return None

    def _check_macd_cross(self, ticker, df) -> dict | None:
        """MACD line crosses above signal line."""
        m, s, _ = macd(df["Close"])
        _atr_val = float(atr(df).iloc[-1])
        close    = float(df["Close"].iloc[-1])

        if len(m) < 2: return None
        bullish_cross = float(m.iloc[-2]) < float(s.iloc[-2]) and float(m.iloc[-1]) > float(s.iloc[-1])
        bearish_cross = float(m.iloc[-2]) > float(s.iloc[-2]) and float(m.iloc[-1]) < float(s.iloc[-1])

        if bullish_cross:
            hist_diff = abs(float(m.iloc[-1]) - float(s.iloc[-1]))
            confidence = min(60 + int(hist_diff / close * 10000), 90)
            return {
                "ticker":     ticker,
                "signal":     "BUY",
                "entry":      round(close, 2),
                "target":     round(close + _atr_val * ATR_MULT_TARGET, 2),
                "stop":       round(close - _atr_val * ATR_MULT_STOP,   2),
                "confidence": confidence,
                "timeframe":  "3–7 days",
                "reason":     "MACD Bullish Crossover",
                "indicators": [
                    f"MACD: {float(m.iloc[-1]):.3f}",
                    f"Signal: {float(s.iloc[-1]):.3f}",
                    f"ATR(14): ${_atr_val:.2f}",
                ],
            }

        if bearish_cross:
            confidence = 62
            return {
                "ticker":     ticker,
                "signal":     "SELL",
                "entry":      round(close, 2),
                "target":     round(close - _atr_val * ATR_MULT_TARGET, 2),
                "stop":       round(close + _atr_val * ATR_MULT_STOP,   2),
                "confidence": confidence,
                "timeframe":  "3–7 days",
                "reason":     "MACD Bearish Crossover",
                "indicators": [
                    f"MACD: {float(m.iloc[-1]):.3f}",
                    f"Signal: {float(s.iloc[-1]):.3f}",
                    f"ATR(14): ${_atr_val:.2f}",
                ],
            }
        return None

    def _check_breakout(self, ticker, df) -> dict | None:
        """Price breaks 20-day high on above-average volume."""
        if len(df) < 21: return None
        close      = float(df["Close"].iloc[-1])
        high_20    = float(df["High"].iloc[-21:-1].max())
        vol_today  = float(df["Volume"].iloc[-1])
        vol_avg    = float(df["Volume"].iloc[-21:-1].mean())
        _atr_val   = float(atr(df).iloc[-1])

        if close > high_20 and vol_today > vol_avg * 1.8:
            vol_mult   = vol_today / vol_avg
            confidence = min(65 + int((vol_mult - 1.8) * 10), 92)
            return {
                "ticker":     ticker,
                "signal":     "BUY",
                "entry":      round(close, 2),
                "target":     round(close + _atr_val * ATR_MULT_TARGET, 2),
                "stop":       round(high_20, 2),
                "confidence": confidence,
                "timeframe":  "1–5 days",
                "reason":     f"Volume Breakout above 20-day high (${high_20:.2f})",
                "indicators": [
                    f"20-day High: ${high_20:.2f}",
                    f"Volume: {vol_today:,.0f}  ({vol_mult:.1f}× avg)",
                    f"ATR(14): ${_atr_val:.2f}",
                ],
            }
        return None

    def _check_ema_cross(self, ticker, df) -> dict | None:
        """9 EMA crosses above 21 EMA (golden cross on short timeframe)."""
        e9   = ema(df["Close"], 9)
        e21  = ema(df["Close"], 21)
        if len(e9) < 2: return None
        _atr_val = float(atr(df).iloc[-1])
        close    = float(df["Close"].iloc[-1])

        bull_cross = float(e9.iloc[-2]) < float(e21.iloc[-2]) and float(e9.iloc[-1]) > float(e21.iloc[-1])
        bear_cross = float(e9.iloc[-2]) > float(e21.iloc[-2]) and float(e9.iloc[-1]) < float(e21.iloc[-1])

        if bull_cross:
            return {
                "ticker":     ticker,
                "signal":     "BUY",
                "entry":      round(close, 2),
                "target":     round(close + _atr_val * 1.5, 2),
                "stop":       round(float(e21.iloc[-1]), 2),
                "confidence": 68,
                "timeframe":  "2–5 days",
                "reason":     "EMA 9/21 Golden Cross",
                "indicators": [
                    f"EMA(9):  ${float(e9.iloc[-1]):.2f}",
                    f"EMA(21): ${float(e21.iloc[-1]):.2f}",
                ],
            }
        if bear_cross:
            return {
                "ticker":     ticker,
                "signal":     "SELL",
                "entry":      round(close, 2),
                "target":     round(close - _atr_val * 1.5, 2),
                "stop":       round(float(e21.iloc[-1]), 2),
                "confidence": 65,
                "timeframe":  "2–5 days",
                "reason":     "EMA 9/21 Death Cross",
                "indicators": [
                    f"EMA(9):  ${float(e9.iloc[-1]):.2f}",
                    f"EMA(21): ${float(e21.iloc[-1]):.2f}",
                ],
            }
        return None

    # ── Main scan ─────────────────────────────────────────────────────────────

    def scan(self) -> list[dict]:
        signals = []
        strategies = [
            self._check_rsi_bounce,
            self._check_macd_cross,
            self._check_breakout,
            self._check_ema_cross,
        ]

        for ticker in self.watchlist:
            df = self._fetch(ticker)
            if df is None:
                continue
            for strategy in strategies:
                result = strategy(ticker, df)
                if result and result["confidence"] >= MIN_CONFIDENCE:
                    signals.append(result)
                    break  # one signal per ticker per scan

        # Sort by confidence descending
        signals.sort(key=lambda x: x["confidence"], reverse=True)
        log.info(f"Scan complete — {len(signals)} signal(s) found.")
        return signals
