#!/usr/bin/env python3
"""
Early Signal Monitor v3 — Stock Catalyst Detector
===================================================
Monitora fonti chiave per individuare segnali precoci prima che un titolo esploda.

Pattern rilevati:
  1. Trump Touch      — Truth Social / Casa Bianca / contratti governo / disclosure acquisti
  2. Big Tech PPA     — Power Purchase Agreement Microsoft/Amazon/Google/Oracle
  3. Analyst Cascade  — Upgrade case minori prima delle grandi banche
  4. Insider Buying   — Form 4 SEC: executive e funzionari che comprano
  5. Congress Trading — STOCK Act via Capitol Trades RSS
  6. Gov Contracts    — USASpending.gov: contratti federali prima che escano sui media
  7. Smart Money      — ARK Invest (CSV giornaliero), Pelosi tracker, 13F EDGAR
  8. Crypto Policy    — executive order, SEC decisions, ETF approval
  9. Space/Defense    — contratti NASA/SpaceX/DoD, nuovi settori

Settori monitorati:
  Energia AI (CEG, GEV, BE, VST, TLN, OKLO, SMR, NEE, D)
  AI Chips (PLTR, DELL, INTC, AMD, NVDA, AVGO, ORCL)
  Quantum (QBTS, RGTI, IONQ)
  Difesa avanzata (NOC, GD, LDOS, BAH, LMT, RTX, LHX)
  Space (RKLB, LUNR, ASTS, RDW)
  Crypto stocks (COIN, MSTR, RIOT, MARA, CLSK)

Smart Money tracciati (gratis):
  ARK Invest — CSV giornaliero pubblico (Cathie Wood)
  Capitol Trades RSS — acquisti Congress in real-time
  SEC 13F EDGAR — Berkshire, Pershing Square (trimestrale)
  Pelosi Tracker RSS — Nancy Pelosi operazioni

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
    {"name": "PR Newswire Energy",  "url": "https://www.prnewswire.com/rss/news-releases-list.rss?category=EN",  "type": "pr",      "base_score": 15, "credibility": 0.9},
    # Nuovi settori
    {"name": "SpaceNews",           "url": "https://spacenews.com/feed/",                                        "type": "media",   "base_score": 18, "credibility": 1.1},
    {"name": "Defense News",        "url": "https://www.defensenews.com/arc/outboundfeeds/rss/",                 "type": "media",   "base_score": 18, "credibility": 1.1},
    {"name": "CoinDesk",            "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",                   "type": "media",   "base_score": 15, "credibility": 1.0},
    {"name": "Capitol Trades Buy",  "url": "https://www.capitoltrades.com/trades?asset_type=stock&txType=buy&rss=1", "type": "congress", "base_score": 40, "credibility": 1.5},
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
    "dominion":      "D",
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
    # Difesa avanzata
    "lockheed":      "LMT",
    "raytheon":      "RTX",
    "l3harris":      "LHX",
    "northrop":      "NOC",
    "general dynamics": "GD",
    "leidos":        "LDOS",
    "booz allen":    "BAH",
    # Space
    "rocket lab":    "RKLB",
    "intuitive machines": "LUNR",
    "ast spacemobile": "ASTS",
    "redwire":       "RDW",
    # Crypto stocks
    "coinbase":      "COIN",
    "microstrategy": "MSTR",
    "riot platforms": "RIOT",
    "marathon digital": "MARA",
    "cleanspark":    "CLSK",
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
    "dominion":      15,
    # Difesa avanzata
    "northrop":      15,
    "general dynamics": 12,
    "leidos":        10,
    "booz allen":    10,
    # Space — micro cap
    "rocket lab":    8,
    "intuitive machines": 6,
    "ast spacemobile": 6,
    "redwire":       5,
    # Crypto stocks
    "coinbase":      20,
    "microstrategy": 15,
    "riot platforms": 10,
    "marathon digital": 10,
    "cleanspark":    8,
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
    # Nuovi settori: Crypto
    {"name": "Crypto ETF/policy governo",   "pattern": r"(bitcoin|crypto|btc).{0,60}(etf|executive order|sec|approval|reserve|strategic)",                   "score": 40, "tag": "crypto",   "alert": True},
    {"name": "SEC crypto decision",         "pattern": r"sec.{0,40}(crypto|bitcoin|ethereum|digital asset).{0,40}(approv|rule|regulat)",                      "score": 35, "tag": "crypto",   "alert": True},
    {"name": "Crypto + governo USA",        "pattern": r"(national bitcoin reserve|crypto.{0,20}strategic|digital asset.{0,20}reserve)",                      "score": 45, "tag": "crypto",   "alert": True},
    # Nuovi settori: Space / Difesa
    {"name": "Contratto NASA/Space Force",  "pattern": r"nasa|space force|spacex.{0,40}(contract|award|billion|million)",                                     "score": 30, "tag": "space",    "alert": True},
    {"name": "DoD contratto big",           "pattern": r"(department of defense|dod|pentagon).{0,40}(billion|awarded|contract).{0,40}(million|billion)",       "score": 35, "tag": "defense",  "alert": True},
    # Smart Money
    {"name": "ARK Invest buy",              "pattern": r"ark invest|cathie wood|arkk|arkg|arkw|arkf|arkq",                                                    "score": 30, "tag": "smartmoney","alert": True},
    {"name": "Pelosi acquisto",             "pattern": r"pelosi.{0,40}(bought|purchased|call|option|stock)|nancy pelosi.{0,40}(trade|buy)",                   "score": 45, "tag": "pelosi",   "alert": True},
    {"name": "Congress member acquisto",    "pattern": r"(senator|representative|congressman|congresswoman).{0,40}(bought|purchased|calls|options|stock)",     "score": 35, "tag": "congress", "alert": True},
    {"name": "Berkshire/Buffett posizione", "pattern": r"(berkshire|buffett|warren buffett).{0,40}(bought|acquired|stake|position|increased)",                 "score": 40, "tag": "smartmoney","alert": True},
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


def _read_8k_content(accession: str, cik: str) -> str:
    """
    Legge il testo completo di un 8-K via EdgarTools.
    Fallback a stringa vuota se non disponibile o non installato.
    """
    try:
        from edgar import get_filings, set_identity
        set_identity("Michele Guidi micheleguidi83@icloud.com")
        filings = get_filings(cik=cik, form="8-K", limit=1)
        if filings and len(filings) > 0:
            filing = filings[0]
            doc = filing.obj()
            if doc and hasattr(doc, 'text'):
                return doc.text[:3000]  # prime 3000 chars sono sufficienti
    except Exception:
        pass
    return ""


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
                cik = src.get("entity_id", "")
                accession = src.get("period_of_report", "")
                pub_dt = parse_date(date_filed)
                age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)

                # Leggi testo completo 8-K via EdgarTools
                full_text = _read_8k_content(accession, cik)
                # Usa il testo completo per scoring se disponibile, altrimenti keyword+company
                scoring_text = full_text if full_text else (kw + " " + company)
                title = f"[SEC 8-K] {company} — depositato {date_filed}"
                scored = score_text(title, scoring_text, 40, 1.3)
                final = min(int(scored["raw_score"] * time_decay(age_h)), 100)
                # Summary: usa prime 400 chars del testo reale se disponibile
                if full_text:
                    summary_text = full_text[:400].replace("\n", " ").strip()
                else:
                    summary_text = f"Keyword: '{kw}' | CIK: {src.get('entity_id','')}"

                signals.append(Signal(
                    title=title, source="SEC EDGAR (keyword)", source_type="sec",
                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={src.get('entity_id','')}&type=8-K",
                    published=date_filed, published_dt=pub_dt.isoformat(),
                    summary=summary_text,
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


def fetch_ark_trades(days_back: int = 3) -> list:
    """
    ARK Invest pubblica le operazioni giornaliere in CSV pubblico gratuito.
    Cathie Wood e' considerata uno degli investitori piu influenti in tech/innovation.
    Un acquisto ARK su un titolo small/mid cap spesso anticipa un rally.
    """
    signals = []
    ark_funds = [
        ("ARKK", "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv"),
        ("ARKQ", "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv"),
        ("ARKW", "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv"),
    ]
    cutoff = NOW - timedelta(days=days_back)

    for fund_name, url in ark_funds:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            lines = r.text.strip().split("\n")
            if len(lines) < 2:
                continue
            header = [h.strip().strip('"').lower() for h in lines[0].split(",")]

            for line in lines[1:]:
                if not line.strip():
                    continue
                cols = [c.strip().strip('"') for c in line.split(",")]
                if len(cols) < len(header):
                    continue
                row = dict(zip(header, cols))

                ticker = row.get("ticker", "").upper()
                company = row.get("company", "").lower()
                shares = row.get("shares", "0").replace(",", "")
                date_str = row.get("date", "")
                direction = row.get("direction", "").lower()  # "Bought" o "Sold"

                # Solo acquisti su ticker in watchlist
                if "buy" not in direction and "bought" not in direction:
                    continue
                matched = [n for n in WATCHLIST_NAMES if n in company or WATCHLIST.get(n, "") == ticker]
                if not matched and ticker not in WATCHLIST.values():
                    continue

                pub_dt = parse_date(date_str)
                if pub_dt < cutoff:
                    continue

                age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
                final = min(int(55 * time_decay(age_h)), 100)

                signals.append(Signal(
                    title=f"[ARK {fund_name}] Cathie Wood COMPRA {ticker} — {shares} shares",
                    source=f"ARK Invest ({fund_name})", source_type="smartmoney",
                    url=f"https://ark-funds.com/funds/{fund_name.lower()}/",
                    published=date_str, published_dt=pub_dt.isoformat(),
                    summary=f"ARK {fund_name} ha acquistato {shares} shares di {ticker} ({company}). Data: {date_str}",
                    raw_score=55, final_score=final,
                    tags=["smartmoney"], alert=True, pattern="smartmoney",
                    matched_rules=["ARK Invest buy"],
                    tickers_mentioned=matched or [company[:30]],
                    ticker_symbols=[ticker], age_hours=round(age_h, 1),
                ))
        except Exception as e:
            print(f"  ⚠️  ARK {fund_name}: {e}")
    return signals


def fetch_pelosi_tracker(days_back: int = 14) -> list:
    """
    Pelosi Tracker RSS — operazioni di Nancy Pelosi e familiari.
    Storico di performance eccezionale: +24% annuo in media sui trade documentati.
    Fonte: pelositracker.com (RSS pubblico gratuito).
    """
    signals = []
    cutoff = NOW - timedelta(days=days_back)
    urls = [
        "https://www.capitoltrades.com/politicians/P000197?rss=1",  # Pelosi su Capitol Trades
        "https://pelositracker.com/feed/",                           # Pelosi tracker RSS
    ]
    for url in urls:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:20]:
                title = entry.get("title", "")
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))[:400]
                pub_dt = parse_date(entry.get("published", ""))
                if pub_dt < cutoff:
                    continue
                # Filtra solo acquisti (non vendite)
                text = (title + " " + summary).lower()
                if "sell" in text and "buy" not in text and "call" not in text:
                    continue

                age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
                tickers = [n for n in WATCHLIST_NAMES if n in text]
                t_symbols = [WATCHLIST[t] for t in tickers]
                # Cerca ticker nel testo anche come simbolo
                for sym in WATCHLIST.values():
                    if f" {sym.lower()} " in text or f"({sym.lower()})" in text:
                        if sym not in t_symbols:
                            t_symbols.append(sym)

                final = min(int(70 * time_decay(age_h)), 100)
                signals.append(Signal(
                    title=f"[Pelosi] {title}",
                    source="Pelosi Tracker", source_type="pelosi",
                    url=entry.get("link", url),
                    published=entry.get("published", ""), published_dt=pub_dt.isoformat(),
                    summary=summary.strip(),
                    raw_score=70, final_score=final,
                    tags=["pelosi", "congress", "smartmoney"], alert=True, pattern="pelosi",
                    matched_rules=["Pelosi acquisto"],
                    tickers_mentioned=tickers, ticker_symbols=t_symbols,
                    age_hours=round(age_h, 1),
                ))
        except Exception as e:
            print(f"  ⚠️  Pelosi tracker: {e}")
    return signals


def fetch_sec_13f(days_back: int = 45) -> list:
    """
    SEC Form 13F — posizioni trimestrali di grandi fondi (Berkshire, Pershing Square).
    Lag di 45gg dalla fine del trimestre, ma utile per capire dove puntano i big.
    CIK noti: Berkshire=1067983, Pershing Square=1336528, Scion (Burry)=1649339
    """
    signals = []
    funds = [
        ("Berkshire Hathaway (Buffett)", "1067983"),
        ("Pershing Square (Ackman)",     "1336528"),
        ("Scion Asset Mgmt (Burry)",     "1649339"),
    ]
    start = (NOW - timedelta(days=days_back)).strftime("%Y-%m-%d")

    for fund_name, cik in funds:
        url = (
            f"https://efts.sec.gov/LATEST/search-index"
            f"?q=%22{cik}%22&forms=13F-HR"
            f"&dateRange=custom&startdt={start}"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            hits = r.json().get("hits", {}).get("hits", [])
            if not hits:
                continue
            src = hits[0].get("_source", {})
            date_filed = src.get("file_date", "")
            pub_dt = parse_date(date_filed)
            age_h = max((NOW - pub_dt).total_seconds() / 3600, 0)
            title = f"[13F] {fund_name} — nuovo filing {date_filed}"
            summary = f"Controlla il filing per vedere le nuove posizioni aperte/aumentate."
            final = min(int(45 * time_decay(age_h)), 100)
            signals.append(Signal(
                title=title, source="SEC 13F", source_type="smartmoney",
                url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F&dateb=&owner=include&count=5",
                published=date_filed, published_dt=pub_dt.isoformat(),
                summary=summary, raw_score=45, final_score=final,
                tags=["smartmoney"], alert=False, pattern="smartmoney",
                matched_rules=["Berkshire/Buffett posizione" if "Berkshire" in fund_name else "Smart money 13F"],
                tickers_mentioned=[], ticker_symbols=[], age_hours=round(age_h, 1),
            ))
        except Exception as e:
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

    print("\n🦆 ARK Invest (Cathie Wood) trades...")
    sigs = fetch_ark_trades(days_back)
    print(f"  ✓ {len(sigs)} acquisti ARK su watchlist")
    all_signals.extend(sigs)

    print("\n👩 Pelosi Tracker...")
    sigs = fetch_pelosi_tracker(days_back=14)
    print(f"  ✓ {len(sigs)} operazioni Pelosi")
    all_signals.extend(sigs)

    print("\n🏦 SEC 13F (Berkshire, Ackman, Burry)...")
    sigs = fetch_sec_13f(days_back=45)
    print(f"  ✓ {len(sigs)} filing 13F recenti")
    all_signals.extend(sigs)

    # Layer 3a: options scanner
    print("\n📈 Options scanner (unusual activity)...")
    try:
        from options_scanner import scan_options
        opt_sigs = scan_options(days_back=2)
        print(f"  ✓ {len(opt_sigs)} segnali options")
        all_signals.extend(opt_sigs)
    except Exception as e:
        print(f"  ⚠️  Options scanner: {e}")

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

    # Layer 2: arricchimento prezzo + earnings
    print("\n💹 Enricher — prezzo, earnings, timing...")
    try:
        from enricher import enrich_signals, format_context
        output["signals"] = enrich_signals(output["signals"])
        # Mostra contesto per top alert
        enriched_alerts = [s for s in output["signals"] if s.get("alert") and s.get("price_context")]
        if enriched_alerts:
            print(f"\n{'─'*65}")
            print("🎯 TOP ALERT CON CONTESTO PREZZO:")
            print(f"{'─'*65}")
            for s in enriched_alerts[:5]:
                timing = s.get("price_context", {}).get("timing", "")
                emoji = {"ENTRA":"🟢","ASPETTA":"🟡","TARDI":"🔴","PULLBACK":"🔵"}.get(timing,"⚪")
                print(f"\n  {emoji} [{s['final_score']}/100] {s['title'][:80]}")
                print(format_context(s))
        # Salva JSON aggiornato con contesto
        with open("signals.json", "w") as f:
            json.dump(output, f, indent=2, default=str)
    except ImportError:
        print("  ⚠️  enricher.py non trovato o yfinance non installato")
    except Exception as e:
        print(f"  ⚠️  Enricher: {e}")

    # Layer 3b: salva nel database storico
    try:
        from db import save_signals
        save_signals(output["signals"])
    except Exception as e:
        print(f"  ⚠️  DB: {e}")

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

def is_actionable(signal) -> tuple[bool, str]:
    """
    Un segnale è azionabile solo se ha almeno DUE elementi tra:
      1. Velocity anomala (source_type == velocity)
      2. Evento specifico (sec, gov, insider, congress, ppa, nuclear)
      3. Convergence (tag convergence presente)
    Ritorna (bool, motivo).
    """
    has_velocity    = signal.get("source_type") == "velocity"
    has_event       = signal.get("source_type") in ("sec", "gov", "insider", "congress") \
                      or signal.get("pattern") in ("ppa", "nuclear", "trump", "insider", "congress", "gov")
    has_convergence = "convergence" in signal.get("tags", [])

    count = sum([has_velocity, has_event, has_convergence])

    if count >= 2:
        reasons = []
        if has_velocity:    reasons.append("velocity anomala")
        if has_event:       reasons.append("evento specifico")
        if has_convergence: reasons.append("convergence multi-fonte")
        return True, " + ".join(reasons)
    return False, ""


def send_slack_alert(signals: list, webhook_url: str, min_score: int = 70):
    """
    Manda un messaggio Slack con i top alert.
    webhook_url: Slack Incoming Webhook URL (da env var SLACK_WEBHOOK_URL).
    """
    if not webhook_url:
        return

    # Solo segnali azionabili (velocity + evento o convergence)
    actionable = []
    for s in signals:
        if not s.alert or s.final_score < min_score:
            continue
        ok, reason = is_actionable(asdict(s))
        if ok:
            actionable.append((s, reason))

    if not actionable:
        print("  ℹ️  Slack: nessun segnale azionabile (velocity + evento richiesti)")
        return

    top = actionable

    # Header del messaggio
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎯 Early Signal — {len(top)} segnali azionabili"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} | Solo segnali con velocity + evento/convergence"}],
        },
        {"type": "divider"},
    ]

    for s, reason in top[:8]:
        age = f"{s.age_hours:.0f}h fa" if s.age_hours > 0 else "ora"
        tickers_str = " ".join(f"`{t}`" for t in s.ticker_symbols) if s.ticker_symbols else "_n/a_"
        conv = f" 🔀" if s.convergence_boost else ""

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*[{s.final_score}/100] {s.pattern.upper()}*{conv}\n"
                    f"{s.title[:120]}\n"
                    f"Ticker: {tickers_str} | {age}\n"
                    f"✅ _{reason}_"
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
        "text": f"🎯 {len(top)} segnali azionabili — Early Signal Monitor",
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
