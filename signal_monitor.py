#!/usr/bin/env python3
"""
Early Signal Monitor v2 — Stock Catalyst Detector
===================================================
Monitora fonti chiave per individuare segnali precoci prima che un titolo esploda.

Pattern rilevati:
  1. Trump Touch      — Truth Social / Casa Bianca / contratti governo / disclosure acquisti
  2. Big Tech PPA     — Power Purchase Agreement Microsoft/Amazon/Google/Oracle
  3. Analyst Cascade  — Upgrade case minori prima delle grandi banche
  4. Insider Buying   — Form 4 SEC: executive e funzionari che comprano
  5. Congress Trading — STOCK Act: senatori/congressisti comprano prima di votare policy
  6. Gov Contracts    — USASpending.gov: contratti federali prima che escano sui media

Fonti gratuite usate:
  SEC EDGAR 8-K RSS + full-text search
  SEC EDGAR Form 4 (insider trading)
  HouseStockWatcher + SenateStockWatcher (STOCK Act, JSON pubblico)
  USASpending.gov API (contratti federali, API pubblica)
  Federal Register RSS (executive orders/policy)
  Google News RSS per ticker (misura velocita di menzione)
  Reuters / CNBC / MarketWatch RSS
  Utility Dive / Data Center Frontier / NucNet / Seeking Alpha / PR Newswire

Scoring avanzato:
  - Time decay: notizie fresche pesano di piu (1.4x se < 1h, 0.4x se > 48h)
  - Convergence: stesso ticker in N fonti diverse -> score +8 per fonte aggiuntiva
  - Source credibility multiplier (SEC e Gov pesano di piu dei media generalisti)

Uso:
  pip install feedparser requests
  python signal_monitor.py             # run singolo, salva signals.json
  python signal_monitor.py --watch     # loop ogni 30 minuti
  python signal_monitor.py --days 7    # finestra temporale piu ampia
"""

import feedparser
import requests
import json
import re
import time
import argparse
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from email.utils import parsedate_to_datetime
import urllib.parse

# SEC EDGAR richiede User-Agent con nome e email reali, altrimenti blocca
feedparser.USER_AGENT = "EarlySignalMonitor/2.0 (Michele Guidi; research use; micheleguidi83@icloud.com)"

# ─────────────────────────────────────────────
#  CONFIGURAZIONE FONTI RSS
# ─────────────────────────────────────────────

FEEDS = [
    # SEC EDGAR — filing obbligatori in real-time
    {"name": "SEC EDGAR 8-K",       "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=40&output=atom",  "type": "sec",     "base_score": 30, "credibility": 1.3},
    {"name": "SEC Form 4 Insider",  "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&dateb=&owner=include&count=40&output=atom",    "type": "insider", "base_score": 35, "credibility": 1.5},
    # Media specializzati (anticipano i generalisti)
    {"name": "Utility Dive",        "url": "https://www.utilitydive.com/feeds/news/",                                                                        "type": "media",   "base_score": 20, "credibility": 1.2},
    {"name": "Data Center Frontier","url": "https://datacenterfrontier.com/feed/",                                                                           "type": "media",   "base_score": 20, "credibility": 1.2},
    {"name": "NucNet",              "url": "https://www.nucnet.org/rss",                                                                                     "type": "media",   "base_score": 18, "credibility": 1.2},
    {"name": "Federal Register",    "url": "https://www.federalregister.gov/documents/feed/",                                                                 "type": "policy",  "base_score": 25, "credibility": 1.4},
    # Media generalisti con RSS pubblico
    {"name": "Reuters Business",    "url": "https://feeds.reuters.com/reuters/businessNews",                                                                  "type": "media",   "base_score": 15, "credibility": 1.1},
    {"name": "CNBC",                "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",                                                          "type": "media",   "base_score": 15, "credibility": 1.1},
    {"name": "MarketWatch",         "url": "https://feeds.marketwatch.com/marketwatch/topstories/",                                                          "type": "media",   "base_score": 15, "credibility": 1.0},
    {"name": "Seeking Alpha",       "url": "https://seekingalpha.com/market_currents.xml",                                                                   "type": "analyst", "base_score": 15, "credibility": 1.0},
    {"name": "PR Newswire Energy",  "url": "https://www.prnewswire.com/rss/news-releases-list.rss?category=EN",                                             "type": "pr",      "base_score": 15, "credibility": 0.9},
]

# ─────────────────────────────────────────────
#  TICKER WATCHLIST
# ─────────────────────────────────────────────

WATCHLIST = {
    # Energia AI
    "constellation": "CEG",
    "ge vernova":    "GEV",
    "bloom energy":  "BE",
    "vistra":        "VST",
    "talen energy":  "TLN",
    "oklo":          "OKLO",
    "nuscale":       "SMR",
    "nextera":       "NEE",
    # Tech / AI chips
    "palantir":      "PLTR",
    "dell":          "DELL",
    "intel":         "INTC",
    "amd":           "AMD",
    "nvidia":        "NVDA",
    "broadcom":      "AVGO",
    "oracle":        "ORCL",
    # Quantum
    "d-wave":        "QBTS",
    "rigetti":       "RGTI",
    "ionq":          "IONQ",
    # Difesa / Gov
    "lockheed":      "LMT",
    "raytheon":      "RTX",
    "l3harris":      "LHX",
}

WATCHLIST_NAMES = list(WATCHLIST.keys())

# Soglie velocity differenziate per dimensione del titolo.
# Large cap: sempre tanti articoli, serve picco anomalo.
# Small/mid cap: anche 8-10 articoli in 48h sono anomali.
VELOCITY_THRESHOLDS = {
    # Large cap — soglia alta
    "nvidia":        60,
    "amd":           40,
    "intel":         35,
    "oracle":        35,
    "broadcom":      30,
    "dell":          25,
    "palantir":      25,
    "nextera":       20,
    # Mid cap — soglia media
    "constellation": 15,
    "ge vernova":    15,
    "bloom energy":  12,
    "vistra":        12,
    "lockheed":      15,
    "raytheon":      15,
    # Small/micro cap — soglia bassa
    "talen energy":  8,
    "oklo":          8,
    "nuscale":       8,
    "d-wave":        8,
    "rigetti":       8,
    "ionq":          8,
    "l3harris":      10,
}

# ─────────────────────────────────────────────
#  KEYWORD SCORING RULES
# ─────────────────────────────────────────────

SIGNAL_RULES = [
    # Pattern 1: Trump Touch
    {"name": "Trump menzione diretta",      "pattern": r"\btrump\b",                                                                                         "score": 35, "tag": "trump",   "alert": True},
    {"name": "Truth Social",                "pattern": r"truth social",                                                                                      "score": 40, "tag": "trump",   "alert": True},
    {"name": "White House",                 "pattern": r"white house",                                                                                       "score": 20, "tag": "trump",   "alert": False},
    {"name": "Contratto Pentagon/DoD",      "pattern": r"pentagon|department of defense|\bdod\b|military contract|defense contract",                         "score": 30, "tag": "trump",   "alert": True},
    {"name": "Contratto DOE/governo",       "pattern": r"department of energy|\bdoe\b|federal grant|government contract|loan guarantee",                     "score": 25, "tag": "trump",   "alert": False},
    {"name": "Disclosure acquisto azioni",  "pattern": r"trump.*bought|trump.*purchased|presidential disclosure|form.*278|financial disclosure",              "score": 50, "tag": "trump",   "alert": True},
    # Pattern 2: Big Tech PPA
    {"name": "Power Purchase Agreement",    "pattern": r"power purchase agreement|\bppa\b|offtake agreement",                                                "score": 35, "tag": "ppa",     "alert": True},
    {"name": "Big Tech + energia",          "pattern": r"(microsoft|amazon|google|oracle|meta|openai|apple).{0,60}(energy|power|nuclear|megawatt|gigawatt|data center)", "score": 40, "tag": "ppa", "alert": True},
    {"name": "Riavvio nucleare",            "pattern": r"nuclear restart|restart.*nuclear|three mile island|crane clean energy|reactor.*reopen",              "score": 35, "tag": "nuclear", "alert": True},
    {"name": "Small Modular Reactor",       "pattern": r"small modular reactor|\bsmr\b|bwrx|nuscale|kairos|x-energy|terrapower",                            "score": 30, "tag": "nuclear", "alert": False},
    {"name": "Data center MW massiccia",    "pattern": r"(\d{3,}\s?(megawatt|mw|gigawatt|gw)).{0,60}(data center|ai|artificial intelligence)",               "score": 35, "tag": "ppa",     "alert": True},
    {"name": "Deal AI miliardi",            "pattern": r"\$\s*\d+\.?\d*\s*(billion).{0,80}(ai|artificial intelligence|data center|energy|power)",            "score": 30, "tag": "ppa",     "alert": False},
    # Pattern 3: Analyst Cascade
    {"name": "Analyst upgrade generico",    "pattern": r"upgrade.{0,30}(buy|outperform|strong buy)|initiates.{0,20}buy|raises.*target",                      "score": 20, "tag": "analyst", "alert": False},
    {"name": "Casa minore upgrade early",   "pattern": r"(d\.?a\.? davidson|daiwa|needham|b\.? riley|roth capital|lake street|wedbush).{0,40}(buy|outperform|upgrade)", "score": 30, "tag": "analyst", "alert": True},
    # Pattern 4: Insider / Congress
    {"name": "Insider buy (Form 4)",        "pattern": r"\bacquisition\b|\bpurchase\b.{0,30}(shares|stock|common)",                                          "score": 30, "tag": "insider", "alert": True},
    {"name": "Congress buy (STOCK Act)",    "pattern": r"congress|senator|representative.{0,40}(bought|purchased|stock|shares)",                             "score": 40, "tag": "congress","alert": True},
    # Pattern 5: Gov Contracts
    {"name": "Contratto > $100M",           "pattern": r"\$\s*(\d{3,})\s*(million|billion).{0,40}(contract|agreement|award)",                               "score": 30, "tag": "gov",     "alert": True},
    # Settori specifici
    {"name": "Quantum + governo",           "pattern": r"quantum.{0,40}(grant|contract|billion|million|government|executive order)",                         "score": 35, "tag": "quantum",  "alert": True},
    {"name": "Executive Order energia/AI",  "pattern": r"executive order.{0,60}(energy|artificial intelligence|ai|nuclear|chip)",                            "score": 40, "tag": "policy",   "alert": True},
]

# ─────────────────────────────────────────────
#  DATA STRUCTURE
# ─────────────────────────────────────────────

@dataclass
class Signal:
    title: str
    source: str
    source_type: str
    url: str
    published: str
    published_dt: str       # ISO string per JSON serialization
    summary: str
    raw_score: int
    final_score: int
    tags: list = field(default_factory=list)
    alert: bool = False
    pattern: str = ""
    matched_rules: list = field(default_factory=list)
    tickers_mentioned: list = field(default_factory=list)
    ticker_symbols: list = field(default_factory=list)
    age_hours: float = 0.0
    convergence_boost: int = 0

# ─────────────────────────────────────────────
#  TIME UTILS
# ─────────────────────────────────────────────

def parse_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.now(timezone.utc)
    for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d"]:
        try:
            s = date_str[:len(fmt)+2]
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            pass
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(timezone.utc)

def time_decay(age_hours: float) -> float:
    if age_hours < 1:   return 1.4
    if age_hours < 3:   return 1.2
    if age_hours < 6:   return 1.0
    if age_hours < 12:  return 0.85
    if age_hours < 24:  return 0.70
    if age_hours < 48:  return 0.55
    return 0.40

# ─────────────────────────────────────────────
#  SCORING ENGINE
# ─────────────────────────────────────────────

def score_text(title: str, summary: str, base_score: int, credibility: float = 1.0) -> dict:
    text = (title + " " + summary).lower()
    total = base_score
    tags = set()
    alert = False
    matched = []

    # Ticker presenti nel testo — calcolati prima delle regole
    tickers = [n for n in WATCHLIST_NAMES if n in text]
    symbols = list(set(WATCHLIST[t] for t in tickers))
    has_ticker = len(tickers) > 0

    for rule in SIGNAL_RULES:
        if not re.search(rule["pattern"], text, re.IGNORECASE):
            continue

        # Fix falsi positivi: regole politiche scorano pieno solo se c'è anche un ticker.
        # "trump", "congress", "gov" senza ticker = rumore generico, contribuisce solo al 20%.
        if rule["tag"] in ("trump", "congress", "gov") and not has_ticker:
            total += int(rule["score"] * 0.2)
            continue

        total += rule["score"]
        tags.add(rule["tag"])
        matched.append(rule["name"])
        if rule.get("alert"):
            alert = True

    total += 10 * len(tickers)
    total = int(total * credibility)

    priority = ["trump", "insider", "congress", "ppa", "nuclear", "gov", "analyst", "quantum", "policy"]
    dominant = next((t for t in priority if t in tags), "generic")

    return {
        "raw_score": min(total, 100),
        "tags": list(tags),
        "alert": alert,
        "pattern": dominant,
        "matched_rules": matched,
        "tickers_mentioned": tickers,
        "ticker_symbols": symbols,
    }

# ─────────────────────────────────────────────
#  FETCHERS
# ─────────────────────────────────────────────

HEADERS = {"User-Agent": "EarlySignalMonitor/2.0 (Michele Guidi; research use; micheleguidi83@icloud.com)"}
NOW = datetime.now(timezone.utc)

def fetch_feed(cfg: dict, days_back: int = 3) -> list:
    signals = []
    cutoff = NOW - timedelta(days=days_back)
    try:
        parsed = feedparser.parse(cfg["url"])
        for entry in parsed.entries[:30]:
            title = entry.get("title", "")
            raw_sum = entry.get("summary", entry.get("description", ""))
            summary = re.sub(r"<[^>]+>", " ", raw_sum)[:600]
            url = entry.get("link", "")
            pub_str = entry.get("published", entry.get("updated", ""))
            pub_dt = parse_date(pub_str)
            if pub_dt < cutoff:
                continue
            age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
            scored = score_text(title, summary, cfg["base_score"], cfg.get("credibility", 1.0))
            if scored["raw_score"] <= 15:
                continue
            final = min(int(scored["raw_score"] * time_decay(age_h)), 100)
            signals.append(Signal(
                title=title, source=cfg["name"], source_type=cfg["type"],
                url=url, published=pub_str, published_dt=pub_dt.isoformat(),
                summary=summary.strip(), raw_score=scored["raw_score"], final_score=final,
                tags=scored["tags"], alert=scored["alert"], pattern=scored["pattern"],
                matched_rules=scored["matched_rules"], tickers_mentioned=scored["tickers_mentioned"],
                ticker_symbols=scored["ticker_symbols"], age_hours=round(age_h, 1),
            ))
    except Exception as e:
        print(f"  ⚠️  {cfg['name']}: {e}")
    return signals


def fetch_sec_full_text(keywords: list, days_back: int = 3) -> list:
    signals = []
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    for kw in keywords:
        url = f"https://efts.sec.gov/LATEST/search-index?q={urllib.parse.quote(kw)}&forms=8-K&dateRange=custom&startdt={start}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            for hit in r.json().get("hits", {}).get("hits", [])[:5]:
                src = hit.get("_source", {})
                company = src.get("entity_name", "Unknown")
                date_filed = src.get("file_date", "")
                pub_dt = parse_date(date_filed)
                age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
                title = f"[SEC 8-K] {company} — depositato {date_filed}"
                scored = score_text(title, kw + " " + company, 40, 1.3)
                final = min(int(scored["raw_score"] * time_decay(age_h)), 100)
                signals.append(Signal(
                    title=title, source="SEC EDGAR (keyword)", source_type="sec",
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={src.get('entity_id','')}&type=8-K",
                    published=date_filed, published_dt=pub_dt.isoformat(),
                    summary=f"Keyword trovata: '{kw}' | CIK: {src.get('entity_id','')}",
                    raw_score=scored["raw_score"], final_score=final,
                    tags=scored["tags"], alert=True, pattern=scored["pattern"],
                    matched_rules=scored["matched_rules"] + [f"SEC keyword: {kw}"],
                    tickers_mentioned=scored["tickers_mentioned"], ticker_symbols=scored["ticker_symbols"],
                    age_hours=round(age_h, 1),
                ))
        except Exception as e:
            print(f"  ⚠️  SEC '{kw}': {e}")
    return signals


def fetch_congressional_trades(days_back: int = 7) -> list:
    """
    Insider buying da due fonti:
    1. SEC Form 4 RSS — depositi obbligatori entro 2gg dall'acquisto (funziona sempre)
    2. Capitol Trades RSS — aggrega STOCK Act filings di senatori e congressisti
    """
    signals = []
    cutoff = NOW - timedelta(days=days_back)

    # ── Fonte 1: SEC Form 4 (insider aziendale + funzionari) ──────────
    # Il feed RSS Form 4 e gia configurato in FEEDS (SEC Form 4 Insider).
    # Qui aggiungiamo una ricerca full-text mirata sui ticker watchlist.
    for company_name, ticker in list(WATCHLIST.items())[:12]:
        url = (
            f"https://efts.sec.gov/LATEST/search-index"
            f"?q={urllib.parse.quote(company_name)}"
            f"&forms=4"
            f"&dateRange=custom&startdt={(NOW - timedelta(days=days_back)).strftime('%Y-%m-%d')}"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code != 200:
                continue
            for hit in r.json().get("hits", {}).get("hits", [])[:3]:
                src = hit.get("_source", {})
                date_filed = src.get("file_date", "")
                pub_dt = parse_date(date_filed)
                if pub_dt < cutoff:
                    continue
                age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
                title = f"[Form 4] Insider acquisto {ticker} — depositato {date_filed}"
                final = min(int(60 * time_decay(age_h)), 100)
                signals.append(Signal(
                    title=title,
                    source="SEC Form 4 (Insider)", source_type="insider",
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={src.get('entity_id','')}&type=4",
                    published=date_filed, published_dt=pub_dt.isoformat(),
                    summary=f"Insider transaction su {company_name.title()} ({ticker}) — verifica il filing per quantita e ruolo.",
                    raw_score=60, final_score=final,
                    tags=["insider"], alert=True, pattern="insider",
                    matched_rules=["Insider buy (Form 4)"],
                    tickers_mentioned=[company_name], ticker_symbols=[ticker],
                    age_hours=round(age_h, 1),
                ))
        except Exception:
            pass

    # ── Fonte 2: Capitol Trades RSS (STOCK Act congress) ─────────────
    # Feed RSS pubblico, aggrega acquisti di senatori e rappresentanti
    cap_feeds = [
        "https://www.capitoltrades.com/trades?asset_type=stock&txType=buy&rss=1",
    ]
    for feed_url in cap_feeds:
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:30]:
                title = entry.get("title", "")
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))[:400]
                pub_dt = parse_date(entry.get("published", ""))
                if pub_dt < cutoff:
                    continue
                # Controlla se riguarda ticker watchlist
                text = (title + " " + summary).lower()
                matched_names = [n for n in WATCHLIST_NAMES if n in text]
                matched_tickers = [t for t in WATCHLIST.values() if t.lower() in text]
                if not matched_names and not matched_tickers:
                    continue
                age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
                final = min(int(70 * time_decay(age_h)), 100)
                signals.append(Signal(
                    title=f"[Congress Buy] {title}",
                    source="Capitol Trades", source_type="congress",
                    url=entry.get("link", "https://www.capitoltrades.com"),
                    published=entry.get("published", ""), published_dt=pub_dt.isoformat(),
                    summary=summary.strip(),
                    raw_score=70, final_score=final,
                    tags=["congress", "insider"], alert=True, pattern="congress",
                    matched_rules=["Congress buy (STOCK Act)"],
                    tickers_mentioned=matched_names,
                    ticker_symbols=matched_tickers,
                    age_hours=round(age_h, 1),
                ))
        except Exception as e:
            print(f"  ⚠️  Capitol Trades: {e}")

    return signals


def fetch_gov_contracts(days_back: int = 3) -> list:
    signals = []
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    for company_name, ticker in list(WATCHLIST.items())[:10]:
        payload = {
            "filters": {
                "time_period": [{"start_date": start, "end_date": end}],
                "award_type_codes": ["A", "B", "C", "D"],
                "recipient_search_text": [company_name.title()],
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Description", "Action Date"],
            "limit": 3, "page": 1,
        }
        try:
            r = requests.post("https://api.usaspending.gov/api/v2/search/spending_by_award/", json=payload, headers=HEADERS, timeout=15)
            for award in r.json().get("results", []):
                amount = award.get("Award Amount", 0) or 0
                if amount < 10_000_000:
                    continue
                pub_dt = parse_date(award.get("Action Date", ""))
                age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
                amt_str = f"${amount/1e6:.0f}M" if amount < 1e9 else f"${amount/1e9:.1f}B"
                raw = 50 if amount > 100_000_000 else 35
                final = min(int(raw * time_decay(age_h)), 100)
                signals.append(Signal(
                    title=f"[Gov Contract] {award.get('Recipient Name', company_name.title())} — {amt_str}",
                    source="USASpending.gov", source_type="gov",
                    url=f"https://www.usaspending.gov/award/{award.get('Award ID','')}",
                    published=award.get("Action Date", ""), published_dt=pub_dt.isoformat(),
                    summary=award.get("Description", "N/A"),
                    raw_score=raw, final_score=final,
                    tags=["gov", "trump"], alert=amount > 100_000_000, pattern="gov",
                    matched_rules=["Contratto > $100M" if amount > 1e8 else "Contratto federale nuovo"],
                    tickers_mentioned=[company_name], ticker_symbols=[ticker],
                    age_hours=round(age_h, 1),
                ))
        except Exception:
            pass
    return signals


def fetch_google_news_velocity(days_back: int = 2) -> list:
    signals = []
    ticker_counts = defaultdict(int)
    cutoff = NOW - timedelta(days=days_back)
    for company_name in WATCHLIST_NAMES:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(company_name + ' stock')}&hl=en-US&gl=US&ceid=US:en"
        try:
            parsed = feedparser.parse(url)
            count = sum(1 for e in parsed.entries if parse_date(e.get("published", "")) > cutoff)
            ticker_counts[company_name] = count
        except Exception:
            pass

    for company_name, count in ticker_counts.items():
        threshold = VELOCITY_THRESHOLDS.get(company_name, 10)
        if count < threshold:
            continue  # sotto soglia calibrata per questo ticker — non è anomalo

        ticker = WATCHLIST[company_name]
        # Score proporzionale a quanto si supera la soglia, non al valore assoluto
        excess_ratio = count / threshold          # es. 96/25 = 3.84x per DELL
        v_score = min(int(30 + excess_ratio * 15), 75)
        alert = excess_ratio >= 2.0              # alert solo se almeno 2x la soglia
        signals.append(Signal(
            title=f"[News Velocity] {company_name.title()} ({ticker}): {count} articoli ({excess_ratio:.1f}x soglia)",
            source="Google News Velocity", source_type="velocity",
            url=f"https://news.google.com/search?q={urllib.parse.quote(company_name)}",
            published=NOW.isoformat(), published_dt=NOW.isoformat(),
            summary=f"{count} menzioni in {days_back*24}h vs soglia {threshold} — rapporto {excess_ratio:.1f}x.",
            raw_score=v_score, final_score=v_score,
            tags=["velocity"], alert=alert, pattern="velocity",
            matched_rules=[f"Velocity {excess_ratio:.1f}x soglia ({count}/{threshold})"],
            tickers_mentioned=[company_name], ticker_symbols=[ticker], age_hours=0,
        ))
    return signals

# ─────────────────────────────────────────────
#  CONVERGENCE ENGINE
# ─────────────────────────────────────────────

def apply_convergence(signals: list) -> list:
    """Stesso ticker in N fonti diverse -> score +8 per fonte extra."""
    ticker_sources = defaultdict(set)
    for s in signals:
        for t in s.tickers_mentioned:
            ticker_sources[t].add(s.source)
    for s in signals:
        boost = 0
        for t in s.tickers_mentioned:
            n = len(ticker_sources[t])
            if n > 1:
                boost = max(boost, (n - 1) * 8)
        if boost:
            s.convergence_boost = boost
            s.final_score = min(s.final_score + boost, 100)
            if boost >= 16:
                s.alert = True
                if "convergence" not in s.tags:
                    s.tags.append("convergence")
    return signals

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

SEC_KEYWORDS = [
    '"power purchase agreement" "data center"',
    '"nuclear" "microsoft" OR "amazon" OR "google"',
    '"small modular reactor"',
    '"artificial intelligence" "government contract"',
    '"quantum computing" "award"',
]

def run_monitor(days_back: int = 3, verbose: bool = True) -> list:
    global NOW
    NOW = datetime.now(timezone.utc)
    all_signals = []

    print(f"\n{'='*65}")
    print(f"  EARLY SIGNAL MONITOR v2 — {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Finestra: {days_back}gg | Watchlist: {len(WATCHLIST)} ticker | Fonti: {len(FEEDS)+4}")
    print(f"{'='*65}\n")

    print("📡 RSS feeds...")
    for cfg in FEEDS:
        sigs = fetch_feed(cfg, days_back)
        if sigs: print(f"  ✓ {cfg['name']}: {len(sigs)}")
        all_signals.extend(sigs)

    print("\n📄 SEC full-text search...")
    sigs = fetch_sec_full_text(SEC_KEYWORDS, days_back)
    print(f"  ✓ {len(sigs)} 8-K trovati")
    all_signals.extend(sigs)

    print("\n🏛  Congressional trading (STOCK Act)...")
    sigs = fetch_congressional_trades(days_back=7)
    print(f"  ✓ {len(sigs)} acquisti watchlist")
    all_signals.extend(sigs)

    print("\n💰 USASpending.gov contratti...")
    sigs = fetch_gov_contracts(days_back)
    print(f"  ✓ {len(sigs)} contratti rilevanti")
    all_signals.extend(sigs)

    print("\n📰 Google News velocity...")
    sigs = fetch_google_news_velocity(days_back=2)
    print(f"  ✓ {len(sigs)} ticker con velocity anomala")
    all_signals.extend(sigs)

    # Deduplica + convergence + sort
    seen, unique = set(), []
    for s in all_signals:
        key = s.url or s.title
        if key not in seen:
            seen.add(key)
            unique.append(s)

    unique = apply_convergence(unique)
    unique.sort(key=lambda s: (s.final_score, s.raw_score), reverse=True)

    alerts = [s for s in unique if s.alert]
    convergence = [s for s in unique if "convergence" in s.tags]

    print(f"\n{'─'*65}")
    print(f"🚨 TOP ALERT ({len(alerts)} totali — mostrando top 10):")
    print(f"{'─'*65}")
    for s in alerts[:10]:
        age = f"{s.age_hours:.0f}h fa" if s.age_hours < 48 else f"{s.age_hours/24:.0f}gg fa"
        conv = f" [+{s.convergence_boost} conv]" if s.convergence_boost else ""
        print(f"\n  [{s.final_score}/100]{conv} {s.source_type.upper()} — {s.pattern.upper()}")
        print(f"  📌 {s.title[:105]}")
        print(f"  ⏱  {age} | {', '.join(s.ticker_symbols) or ', '.join(s.tickers_mentioned) or 'n/a'}")
        if verbose:
            print(f"  📋 {', '.join(s.matched_rules[:3])}")
        print(f"  🔗 {s.url[:80]}")

    if convergence:
        print(f"\n{'─'*65}")
        print(f"🔀 CONVERGENCE ({len(convergence)} — stesso ticker in fonti multiple):")
        for s in convergence[:5]:
            print(f"  [{s.final_score}] {', '.join(s.ticker_symbols)}: {s.title[:80]}")

    print(f"\n{'─'*65}")
    print(f"📊 TOP 20 SEGNALI:")
    for s in unique[:20]:
        flag = "🚨" if s.alert else "📌"
        conv = "🔀" if "convergence" in s.tags else "  "
        age = f"{s.age_hours:.0f}h" if s.age_hours < 48 else f"{s.age_hours/24:.0f}d"
        print(f"  {flag}{conv} [{s.final_score:3d}] [{s.pattern:10s}] [{age:>4}] {s.source[:18]}: {s.title[:58]}")

    # Salva JSON
    output = {
        "generated_at": NOW.isoformat(),
        "days_back": days_back,
        "total_signals": len(unique),
        "alerts": len(alerts),
        "convergence_alerts": len(convergence),
        "signals": [asdict(s) for s in unique],
    }
    with open("signals.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n✅ signals.json — {len(unique)} segnali, {len(alerts)} alert, {len(convergence)} convergence")
    return unique


def watch_mode(interval: int = 30, days_back: int = 3):
    print(f"👁  Watch mode — ogni {interval} min. Ctrl+C per uscire.\n")
    while True:
        try:
            run_monitor(days_back=days_back, verbose=False)
            nxt = (datetime.now() + timedelta(minutes=interval)).strftime("%H:%M")
            print(f"\n⏰ Prossimo check alle {nxt}...")
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            print("\n🛑 Fermato.")
            break


# ─────────────────────────────────────────────
#  SLACK NOTIFICATIONS
# ─────────────────────────────────────────────

def send_slack_alert(signals: list, webhook_url: str, min_score: int = 70):
    """
    Manda un messaggio Slack con i top alert.
    webhook_url: Slack Incoming Webhook URL (da env var SLACK_WEBHOOK_URL).
    """
    if not webhook_url:
        return

    top = [s for s in signals if s.alert and s.final_score >= min_score]
    if not top:
        return

    # Header del messaggio
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚨 Early Signal Monitor — {len(top)} alert"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} | Soglia: {min_score}+"}],
        },
        {"type": "divider"},
    ]

    for s in top[:8]:  # max 8 per non intasare
        age = f"{s.age_hours:.0f}h fa" if s.age_hours > 0 else "ora"
        tickers_str = " ".join(f"`{t}`" for t in s.ticker_symbols) if s.ticker_symbols else "_n/a_"
        conv = f" 🔀 *+{s.convergence_boost} convergence*" if s.convergence_boost else ""
        rules_str = " · ".join(s.matched_rules[:2])

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*[{s.final_score}/100] {s.pattern.upper()}*{conv}\n"
                    f"{s.title[:120]}\n"
                    f"Ticker: {tickers_str} | {age} | _{rules_str}_"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Apri"},
                "url": s.url[:3000] if s.url else "https://finance.yahoo.com",
            },
        })
        blocks.append({"type": "divider"})

    payload = {
        "text": f"🚨 {len(top)} segnali ad alta priorità — Early Signal Monitor",
        "blocks": blocks,
    }

    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"  ✅ Slack: {len(top)} alert inviati")
        else:
            print(f"  ⚠️  Slack error: {r.status_code} {r.text}")
    except Exception as e:
        print(f"  ⚠️  Slack: {e}")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import os

    parser = argparse.ArgumentParser(description="Early Signal Monitor v2")
    parser.add_argument("--watch",         action="store_true", help="Loop continuo")
    parser.add_argument("--interval",      type=int, default=30, help="Minuti tra check")
    parser.add_argument("--days",          type=int, default=3,  help="Finestra temporale")
    parser.add_argument("--quiet",         action="store_true",  help="Output ridotto")
    parser.add_argument("--min-score",     type=int, default=70, help="Score minimo per alert Slack")
    parser.add_argument("--slack-webhook", type=str, default="",  help="Slack webhook URL (o usa env SLACK_WEBHOOK_URL)")
    args = parser.parse_args()

    # Slack webhook: CLI arg > env var > niente
    slack_webhook = args.slack_webhook or os.environ.get("SLACK_WEBHOOK_URL", "")

    if args.watch:
        print(f"👁  Watch mode — ogni {args.interval} min. Ctrl+C per uscire.\n")
        while True:
            try:
                signals = run_monitor(days_back=args.days, verbose=not args.quiet)
                if slack_webhook:
                    send_slack_alert(signals, slack_webhook, args.min_score)
                nxt = (datetime.now() + timedelta(minutes=args.interval)).strftime("%H:%M")
                print(f"\n⏰ Prossimo check alle {nxt}...")
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                print("\n🛑 Fermato.")
                break
    else:
        signals = run_monitor(days_back=args.days, verbose=not args.quiet)
        if slack_webhook:
            send_slack_alert(signals, slack_webhook, args.min_score)
