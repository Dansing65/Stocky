"""
news_scanner.py — Real-time news catalyst engine for StockSentinel v2

Sources:
  - Finnhub (free real-time news API)
  - SEC EDGAR (insider filings, 8-K events)
  - NewsAPI (broad financial news)
  - Reddit WallStreetBets / stocks sentiment

Each headline is scored by Claude AI for:
  - Bullish / Bearish / Neutral sentiment
  - Catalyst strength (1-10)
  - Expected move magnitude
  - Suggested entry / target / stop
"""

import os
import re
import json
import logging
import hashlib
import requests
import anthropic
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

FINNHUB_KEY  = os.getenv("FINNHUB_API_KEY", "")
NEWSAPI_KEY  = os.getenv("NEWS_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MIN_CATALYST_SCORE = int(os.getenv("MIN_CATALYST_SCORE", "6"))  # 1-10

# ── Seen-news deduplication ───────────────────────────────────────────────────
_seen_hashes: set[str] = set()

def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

def _is_new(text: str) -> bool:
    h = _hash(text)
    if h in _seen_hashes:
        return False
    _seen_hashes.add(h)
    return True

def _clean_seen(max_size: int = 2000):
    """Prevent memory leak on long runs."""
    global _seen_hashes
    if len(_seen_hashes) > max_size:
        _seen_hashes = set(list(_seen_hashes)[-1000:])


# ── News Sources ──────────────────────────────────────────────────────────────

def fetch_finnhub_news(tickers: list[str]) -> list[dict]:
    """Fetch company news from Finnhub for each ticker."""
    if not FINNHUB_KEY:
        log.warning("FINNHUB_API_KEY not set — skipping Finnhub")
        return []

    articles = []
    today    = datetime.utcnow().strftime("%Y-%m-%d")
    week_ago = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")

    for ticker in tickers:
        try:
            url = (
                f"https://finnhub.io/api/v1/company-news"
                f"?symbol={ticker}&from={week_ago}&to={today}&token={FINNHUB_KEY}"
            )
            res  = requests.get(url, timeout=10)
            data = res.json()
            for item in data[:5]:  # top 5 per ticker
                headline = item.get("headline", "")
                if headline and _is_new(headline):
                    articles.append({
                        "ticker":    ticker,
                        "headline":  headline,
                        "summary":   item.get("summary", ""),
                        "source":    item.get("source", "Finnhub"),
                        "url":       item.get("url", ""),
                        "published": datetime.utcfromtimestamp(
                            item.get("datetime", 0)
                        ).strftime("%Y-%m-%d %H:%M UTC"),
                    })
        except Exception as exc:
            log.warning(f"Finnhub error for {ticker}: {exc}")

    log.info(f"Finnhub: {len(articles)} new articles")
    return articles


def fetch_newsapi(tickers: list[str]) -> list[dict]:
    """Fetch broad financial news from NewsAPI."""
    if not NEWSAPI_KEY:
        log.warning("NEWS_API_KEY not set — skipping NewsAPI")
        return []

    articles = []
    query    = " OR ".join(tickers[:10])  # API limit

    try:
        url = (
            f"https://newsapi.org/v2/everything"
            f"?q={query}&language=en&sortBy=publishedAt"
            f"&pageSize=20&apiKey={NEWSAPI_KEY}"
        )
        res  = requests.get(url, timeout=10)
        data = res.json()

        for item in data.get("articles", []):
            headline = item.get("title", "")
            if not headline or "[Removed]" in headline:
                continue
            # Try to detect which ticker this is about
            ticker = _detect_ticker(headline + " " + item.get("description", ""), tickers)
            if not ticker:
                continue
            if _is_new(headline):
                articles.append({
                    "ticker":    ticker,
                    "headline":  headline,
                    "summary":   item.get("description", ""),
                    "source":    item.get("source", {}).get("name", "NewsAPI"),
                    "url":       item.get("url", ""),
                    "published": item.get("publishedAt", "")[:16].replace("T", " ") + " UTC",
                })
    except Exception as exc:
        log.warning(f"NewsAPI error: {exc}")

    log.info(f"NewsAPI: {len(articles)} new articles")
    return articles


def fetch_sec_filings(tickers: list[str]) -> list[dict]:
    """Check SEC EDGAR for recent 8-K filings and insider transactions."""
    articles = []

    for ticker in tickers[:10]:  # be gentle with EDGAR
        try:
            # Get CIK from ticker
            cik_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={  (datetime.utcnow()-timedelta(days=3)).strftime('%Y-%m-%d')}&forms=8-K"
            res  = requests.get(cik_url, timeout=10,
                                headers={"User-Agent": "StockSentinel bot@example.com"})
            data = res.json()
            hits = data.get("hits", {}).get("hits", [])

            for hit in hits[:2]:
                src    = hit.get("_source", {})
                title  = src.get("file_date", "") + " — " + src.get("form_type", "8-K") + f" filing for {ticker}"
                if _is_new(title):
                    articles.append({
                        "ticker":    ticker,
                        "headline":  f"{ticker} filed an {src.get('form_type','8-K')} with the SEC",
                        "summary":   f"Filing date: {src.get('file_date','')}. Entity: {src.get('entity_name',ticker)}.",
                        "source":    "SEC EDGAR",
                        "url":       f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=8-K",
                        "published": src.get("file_date", "") + " UTC",
                    })
        except Exception as exc:
            log.debug(f"SEC EDGAR error for {ticker}: {exc}")

    log.info(f"SEC EDGAR: {len(articles)} new filings")
    return articles


def _detect_ticker(text: str, tickers: list[str]) -> str | None:
    """Return first ticker found in text, or None."""
    text_upper = text.upper()
    for ticker in tickers:
        # Match $TICKER or standalone word
        if f"${ticker}" in text_upper or re.search(rf"\b{ticker}\b", text_upper):
            return ticker
    return None


# ── AI Catalyst Scorer ────────────────────────────────────────────────────────

_ai_client = None

def _get_ai_client():
    global _ai_client
    if _ai_client is None:
        if not ANTHROPIC_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _ai_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    return _ai_client


SCORE_PROMPT = """You are an expert stock trader analyzing financial news to identify high-probability trade catalysts.

Analyze this news article and return ONLY a valid JSON object — no markdown, no explanation, just raw JSON.

Ticker: {ticker}
Headline: {headline}
Summary: {summary}
Source: {source}

Return this exact JSON structure:
{{
  "signal": "BUY" or "SELL" or "NEUTRAL",
  "catalyst_score": <integer 1-10, where 10 = massive catalyst like FDA approval or earnings beat>,
  "confidence": <integer 50-95>,
  "reason": "<1-2 sentence explanation of why this matters>",
  "expected_move_pct": <estimated % price move, e.g. 5.0>,
  "timeframe": "<e.g. 1-2 days or 3-5 days>",
  "catalyst_type": "<one of: Earnings, FDA/Regulatory, Insider Activity, Partnership/Contract, Analyst Rating, Macro Event, Short Squeeze, Legal/Lawsuit, Product Launch, SEC Filing, Other>",
  "entry_strategy": "<brief note on how to enter, e.g. buy the open, wait for pullback to support>",
  "risk_factors": "<what could invalidate this thesis>"
}}

Scoring guide:
- 9-10: Earnings beat/miss, FDA approval/rejection, major acquisition
- 7-8: Analyst upgrade/downgrade, major contract win, insider buying cluster  
- 5-6: Minor partnership, product update, general positive news
- 1-4: Vague or speculative news, minor mentions

Only give BUY/SELL for scores >= 5. Otherwise return NEUTRAL."""


def score_with_ai(article: dict) -> dict | None:
    """Use Claude to score a news article as a trade catalyst."""
    try:
        client = _get_ai_client()
        prompt = SCORE_PROMPT.format(
            ticker=article["ticker"],
            headline=article["headline"],
            summary=article["summary"][:500],
            source=article["source"],
        )
        msg = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"```json|```", "", raw).strip()
        scored = json.loads(raw)
        scored.update(article)  # merge original fields in
        return scored
    except json.JSONDecodeError as exc:
        log.warning(f"AI returned invalid JSON for {article['ticker']}: {exc}")
        return None
    except Exception as exc:
        log.warning(f"AI scoring error: {exc}")
        return None


# ── Main Entry ────────────────────────────────────────────────────────────────

class NewsScanner:
    def __init__(self, watchlist: list[str]):
        self.watchlist = watchlist

    def scan(self) -> list[dict]:
        """Fetch all news, score with AI, return high-impact catalysts."""
        _clean_seen()

        # Gather raw articles from all sources in parallel
        all_articles = []
        all_articles += fetch_finnhub_news(self.watchlist)
        all_articles += fetch_newsapi(self.watchlist)
        all_articles += fetch_sec_filings(self.watchlist)

        if not all_articles:
            log.info("No new articles found this cycle.")
            return []

        log.info(f"Scoring {len(all_articles)} articles with AI…")

        catalysts = []
        for article in all_articles:
            scored = score_with_ai(article)
            if scored is None:
                continue
            score  = scored.get("catalyst_score", 0)
            signal = scored.get("signal", "NEUTRAL")
            if score >= MIN_CATALYST_SCORE and signal != "NEUTRAL":
                catalysts.append(scored)

        # Sort by catalyst score descending
        catalysts.sort(key=lambda x: x.get("catalyst_score", 0), reverse=True)
        log.info(f"News scan complete — {len(catalysts)} high-impact catalyst(s) found.")
        return catalysts
