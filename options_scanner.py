#!/usr/bin/env python3
"""
Layer 3a — Unusual Options Activity Scanner
=============================================
Le istituzioni comprano call/put SETTIMANE prima di un catalyst pubblico.
E' il segnale piu' anticipatorio che esiste — e' "dark money" che si posiziona
prima che la notizia diventi pubblica.

Fonti gratuite:
  1. Unusual Whales RSS — aggrega flussi opzioni anomali
  2. Barchart unusual options (pagina pubblica scraping-friendly)
  3. yfinance options chain — analisi put/call ratio per ticker watchlist
  4. Google News RSS per "[ticker] options" — articoli che segnalano anomalie

Pattern cercati:
  - Call sweep > $500K su titolo in watchlist (istituzionale, non retail)
  - Put/call ratio anomalo (<0.5 = bullish, >2.0 = bearish)
  - Open interest spike su strike out-of-the-money
  - Volume options >> media = qualcuno sa qualcosa
"""

import feedparser
import requests
import re
import urllib.parse
import yfinance as yf
from datetime import datetime, timezone, timedelta
import time

HEADERS = {"User-Agent": "EarlySignalMonitor/3.0 (research use; micheleguidi83@icloud.com)"}
feedparser.USER_AGENT = "EarlySignalMonitor/3.0 (micheleguidi83@icloud.com)"

# ─────────────────────────────────────────────
#  WATCHLIST (importata dal monitor principale)
# ─────────────────────────────────────────────
from signal_monitor import WATCHLIST, WATCHLIST_NAMES


# ─────────────────────────────────────────────
#  FONTE 1: RSS aggregatori options news
# ─────────────────────────────────────────────

OPTIONS_FEEDS = [
    {
        "name": "Unusual Whales",
        "url": "https://unusualwhales.com/rss",
        "credibility": 1.5,
    },
    {
        "name": "Barchart Options",
        "url": "https://www.barchart.com/options/unusual-activity/stocks?rss=1",
        "credibility": 1.4,
    },
]

OPTIONS_KEYWORDS = [
    r"call sweep",
    r"unusual.{0,10}option",
    r"options.{0,10}(flow|activity|volume|sweep)",
    r"(bullish|bearish).{0,20}(bet|flow|sweep|position)",
    r"open interest.{0,20}(spike|surge|jump)",
    r"\$\d+[km].{0,30}(call|put|option)",
    r"(smart money|dark pool|institutional).{0,30}(call|put|option|position)",
]

def _matches_options_pattern(text: str) -> list:
    return [kw for kw in OPTIONS_KEYWORDS if re.search(kw, text, re.IGNORECASE)]

def fetch_options_rss(days_back: int = 2) -> list:
    """Scansiona RSS di news su unusual options activity."""
    signals = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    for feed_cfg in OPTIONS_FEEDS:
        try:
            parsed = feedparser.parse(feed_cfg["url"])
            for entry in parsed.entries[:30]:
                title = entry.get("title", "")
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))[:400]
                pub_str = entry.get("published", "")
                url = entry.get("link", "")
                text = (title + " " + summary).lower()

                # Filtra: deve menzionare ticker watchlist E pattern options
                tickers = [n for n in WATCHLIST_NAMES if n in text]
                symbols = [WATCHLIST[t] for t in tickers]
                # Cerca anche per simbolo ($DELL, DELL, etc.)
                for sym in WATCHLIST.values():
                    if re.search(rf'\b{sym}\b', title + " " + summary, re.IGNORECASE):
                        if sym not in symbols:
                            symbols.append(sym)

                if not symbols:
                    continue

                matched_patterns = _matches_options_pattern(text)
                if not matched_patterns:
                    continue

                # Stima importo dal testo
                amount_match = re.search(r'\$(\d+\.?\d*)\s*([km])', text, re.IGNORECASE)
                amount_str = ""
                score_amount = 0
                if amount_match:
                    val = float(amount_match.group(1))
                    unit = amount_match.group(2).lower()
                    if unit == 'k':
                        val_usd = val * 1000
                    else:
                        val_usd = val * 1_000_000
                    amount_str = f"${val:.0f}{unit.upper()}"
                    if val_usd >= 1_000_000:
                        score_amount = 20
                    elif val_usd >= 500_000:
                        score_amount = 12

                raw_score = int((35 + score_amount + len(matched_patterns) * 5) * feed_cfg["credibility"])
                raw_score = min(raw_score, 100)

                # Parse data
                from email.utils import parsedate_to_datetime
                try:
                    pub_dt = parsedate_to_datetime(pub_str)
                except Exception:
                    pub_dt = datetime.now(timezone.utc)
                if pub_dt < cutoff:
                    continue
                age_h = max((datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600, 0)

                signals.append({
                    "title": f"[Options] {title[:100]}",
                    "source": feed_cfg["name"],
                    "source_type": "options",
                    "url": url,
                    "published": pub_str,
                    "published_dt": pub_dt.isoformat(),
                    "summary": f"{amount_str} | {summary[:200]}".strip(" |"),
                    "raw_score": raw_score,
                    "final_score": raw_score,
                    "tags": ["options"],
                    "alert": raw_score >= 55,
                    "pattern": "options",
                    "matched_rules": matched_patterns[:3],
                    "tickers_mentioned": tickers,
                    "ticker_symbols": symbols,
                    "age_hours": round(age_h, 1),
                    "convergence_boost": 0,
                })
        except Exception as e:
            print(f"  ⚠️  Options RSS {feed_cfg['name']}: {e}")
    return signals


# ─────────────────────────────────────────────
#  FONTE 2: Google News "[ticker] options"
# ─────────────────────────────────────────────

def fetch_options_news_velocity(days_back: int = 2) -> list:
    """
    Cerca news su options per i ticker in watchlist.
    Se una small cap inizia ad avere articoli su "unusual options",
    e' spesso 2-5 giorni prima di un movimento.
    """
    signals = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    for company, ticker in list(WATCHLIST.items())[:15]:  # limita chiamate
        query = f"{company} stock options unusual activity"
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        try:
            parsed = feedparser.parse(url)
            count = 0
            for entry in parsed.entries:
                text = (entry.get("title","") + " " + entry.get("summary","")).lower()
                if any(re.search(kw, text, re.IGNORECASE) for kw in OPTIONS_KEYWORDS):
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(entry.get("published",""))
                    except Exception:
                        pub_dt = datetime.now(timezone.utc)
                    if pub_dt > cutoff:
                        count += 1
            if count >= 2:
                score = min(30 + count * 8, 65)
                signals.append({
                    "title": f"[Options Buzz] {company.title()} ({ticker}): {count} articoli options in {days_back}gg",
                    "source": "Google News Options",
                    "source_type": "options",
                    "url": f"https://news.google.com/search?q={urllib.parse.quote(query)}",
                    "published": datetime.now(timezone.utc).isoformat(),
                    "published_dt": datetime.now(timezone.utc).isoformat(),
                    "summary": f"Attivita' options media in crescita su {ticker} — possibile posizionamento istituzionale.",
                    "raw_score": score,
                    "final_score": score,
                    "tags": ["options"],
                    "alert": count >= 4,
                    "pattern": "options",
                    "matched_rules": [f"Options news velocity: {count} articoli"],
                    "tickers_mentioned": [company],
                    "ticker_symbols": [ticker],
                    "age_hours": 0,
                    "convergence_boost": 0,
                })
            time.sleep(0.2)
        except Exception:
            pass
    return signals


# ─────────────────────────────────────────────
#  FONTE 3: yfinance put/call ratio
# ─────────────────────────────────────────────

def fetch_putcall_anomalies(tickers_to_check: list = None) -> list:
    """
    Analizza il put/call ratio delle options chain via yfinance.
    Put/call < 0.4 = molto bullish (molte call rispetto alle put).
    Put/call > 2.5 = molto bearish.
    Anomalie rispetto alla norma = qualcuno si sta posizionando.
    """
    signals = []
    if tickers_to_check is None:
        # Controlla solo i ticker mid/small cap (piu' informativi)
        tickers_to_check = [
            t for name, t in WATCHLIST.items()
            if name not in ('nvidia', 'amd', 'intel', 'oracle', 'broadcom', 'dell')
        ]

    for ticker_str in tickers_to_check[:12]:
        try:
            t = yf.Ticker(ticker_str)
            expirations = t.options
            if not expirations:
                continue

            # Usa la scadenza piu' vicina (next 30gg)
            exp = expirations[0]
            chain = t.option_chain(exp)
            calls = chain.calls
            puts  = chain.puts

            total_call_vol = calls['volume'].fillna(0).sum()
            total_put_vol  = puts['volume'].fillna(0).sum()

            if total_call_vol + total_put_vol < 100:  # volume troppo basso
                continue

            pc_ratio = total_put_vol / total_call_vol if total_call_vol > 0 else 99

            # OTM call volume anomalo (segnale di accumulo bullish)
            last_price = float(t.fast_info.last_price)
            otm_calls = calls[calls['strike'] > last_price * 1.10]  # call oltre +10%
            otm_call_vol = otm_calls['volume'].fillna(0).sum()
            otm_call_oi  = otm_calls['openInterest'].fillna(0).sum()

            is_bullish_anomaly = pc_ratio < 0.35 or (otm_call_vol > 500 and otm_call_vol > total_call_vol * 0.3)
            is_bearish_anomaly = pc_ratio > 2.5

            if not (is_bullish_anomaly or is_bearish_anomaly):
                continue

            direction = "BULLISH" if is_bullish_anomaly else "BEARISH"
            score = 55 if is_bullish_anomaly else 45
            name = [n for n, s in WATCHLIST.items() if s == ticker_str]
            name = name[0] if name else ticker_str.lower()

            signals.append({
                "title": f"[Options P/C] {ticker_str} ratio {pc_ratio:.2f} — segnale {direction}",
                "source": "yfinance Options Chain",
                "source_type": "options",
                "url": f"https://finance.yahoo.com/quote/{ticker_str}/options",
                "published": datetime.now(timezone.utc).isoformat(),
                "published_dt": datetime.now(timezone.utc).isoformat(),
                "summary": (
                    f"Put/Call ratio: {pc_ratio:.2f} | "
                    f"Call vol: {int(total_call_vol):,} | Put vol: {int(total_put_vol):,} | "
                    f"OTM call vol: {int(otm_call_vol):,} (OI: {int(otm_call_oi):,})"
                ),
                "raw_score": score,
                "final_score": score,
                "tags": ["options", direction.lower()],
                "alert": score >= 55,
                "pattern": "options",
                "matched_rules": [f"P/C ratio anomalo: {pc_ratio:.2f}", direction],
                "tickers_mentioned": [name],
                "ticker_symbols": [ticker_str],
                "age_hours": 0,
                "convergence_boost": 0,
            })
            time.sleep(0.5)
        except Exception:
            pass
    return signals


# ─────────────────────────────────────────────
#  MAIN SCANNER
# ─────────────────────────────────────────────

def scan_options(days_back: int = 2) -> list:
    """Entry point: scansiona tutte le fonti options."""
    all_sigs = []

    print("  Unusual options RSS...")
    sigs = fetch_options_rss(days_back)
    print(f"    → {len(sigs)} segnali")
    all_sigs.extend(sigs)

    print("  Options news velocity...")
    sigs = fetch_options_news_velocity(days_back)
    print(f"    → {len(sigs)} ticker con buzz options")
    all_sigs.extend(sigs)

    print("  Put/call ratio anomalies (OpenBB multi-scadenza → yfinance fallback)...")
    obb_sigs = []
    try:
        from openbb_layer import fetch_openbb_options_chains
        obb_sigs = fetch_openbb_options_chains()
    except Exception:
        pass
    if obb_sigs:
        print(f"    → {len(obb_sigs)} anomalie (OpenBB multi-expiry)")
        all_sigs.extend(obb_sigs)
    else:
        sigs = fetch_putcall_anomalies()
        print(f"    → {len(sigs)} anomalie P/C (yfinance fallback)")
        all_sigs.extend(sigs)

    return all_sigs


if __name__ == "__main__":
    print(f"\nOptions Scanner — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'─'*50}")
    signals = scan_options(days_back=2)
    signals.sort(key=lambda s: s['final_score'], reverse=True)
    for s in signals:
        flag = "🚨" if s['alert'] else "📌"
        print(f"{flag} [{s['final_score']:3d}] {s['source'][:20]}: {s['title'][:80]}")
