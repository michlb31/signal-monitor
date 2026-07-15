#!/usr/bin/env python3
"""
Stock Engine — Azioni CFD IC Markets EU (discovery news-driven)
================================================================
1.697 titoli non si analizzano tutti ogni 30 minuti. Il design ribalta
il problema: sono LE NEWS a nominare i titoli, non noi a interrogarli.

Pipeline:
  1. UNIVERSE   — stocks_icmarkets.csv + stocks_names.json (estratti via
                  OCR dallo screen recording MT5 dell'utente, 10/07/2026)
  2. DISCOVERY  — feed di mercato (CNBC/MarketWatch/Google News) →
                  match titoli per NOME SOCIETÀ (precisione alta) o
                  ticker esplicito ($AAPL, (AAPL)) → sentiment per titolo
  3. DEEP-DIVE  — analisi tecnica (ta.py) SOLO sui top candidati (≤8/run)
  4. GATES      — sentiment+tecnica concordi, no earnings entro 2gg
                  (lezione AVGO: -15% overnight), composite ≥ 0.5
  5. TICKET     — risk_manager con specifiche stock: leva 1:5, margine 20%,
                  frazionabili 0.1 az (USA) / 1 az (EU), commissioni

Specifiche dal PDF ufficiale IC Markets EU (Stocks Specification Sheet).
"""

import csv
import json
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser

ROOT = Path(__file__).parent
feedparser.USER_AGENT = "FXSignalMonitor/1.0 (research; micheleguidi83@icloud.com)"

# ── Specifiche per borsa (PDF ufficiale, verificato 10/07/2026) ──
EXCHANGE_SPECS = {
    "NAS":  {"yf_suffix": "",    "quote": "USD", "min_volume": 0.1, "volume_step": 0.1,
             "commission": ("per_share", 0.02)},
    "NYSE": {"yf_suffix": "",    "quote": "USD", "min_volume": 0.1, "volume_step": 0.1,
             "commission": ("per_share", 0.02)},
    "ETR":  {"yf_suffix": ".DE", "quote": "EUR", "min_volume": 1.0, "volume_step": 1.0,
             "commission": ("pct", 0.001)},
    "AMS":  {"yf_suffix": ".AS", "quote": "EUR", "min_volume": 1.0, "volume_step": 1.0,
             "commission": ("pct", 0.001)},
    "PAR":  {"yf_suffix": ".PA", "quote": "EUR", "min_volume": 1.0, "volume_step": 1.0,
             "commission": ("pct", 0.001)},
    "MAD":  {"yf_suffix": ".MC", "quote": "EUR", "min_volume": 1.0, "volume_step": 1.0,
             "commission": ("pct", 0.001)},
    "LSE":  {"yf_suffix": ".L",  "quote": "GBP", "min_volume": 1.0, "volume_step": 1.0,
             "commission": ("pct", 0.001)},
}

NEWS_FEEDS = [
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    # Query CATALYST-first: cercare "surges OR plunges" significa trovare i
    # movimenti GIÀ avvenuti e arrivare tardi per costruzione
    "https://news.google.com/rss/search?q=stock%20upgrade%20OR%20downgrade%20OR%20guidance%20OR%20earnings%20OR%20contract&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=stock%20market%20movers%20today&hl=en-US&gl=US&ceid=US:en",
]

# Parole troppo generiche per essere chiavi-nome a token singolo
GENERIC_TOKENS = {
    "american", "bank", "capital", "energy", "first", "general", "global",
    "gold", "group", "national", "new", "pacific", "royal", "standard",
    "star", "sun", "united", "west", "digital", "air", "city", "life",
    # Parole inglesi comuni che sono anche primo token di una società.
    # Lezione IBM (14/07): "International Business Machines" → chiave
    # "business" → short su "Business declares war on Pentagon..." che non
    # parlava di IBM. Idem "equity"→EQR, "target"→TGT ("price target"!).
    # Questi titoli restano scopribili via 2-token o ticker esplicito (TGT).
    "business", "equity", "target", "discover", "gap", "shell", "dollar",
    "public", "state", "southern", "western", "universal", "principal",
    "citizens", "regions", "best", "five", "three", "coach", "extra",
    "simon", "church", "waste", "tractor", "progressive", "main", "realty",
    "income", "service", "republic", "ball", "news", "match", "block",
    "fair", "live", "take", "booking", "advance", "morgan", "wells",
    "delta", "phillips", "edison", "host",
}
SUFFIX_TOKENS = {
    "inc", "corp", "corporation", "plc", "sa", "ag", "nv", "se", "spa",
    "group", "holdings", "holding", "the", "co", "ltd", "international",
    "industries", "technologies", "communications", "companies", "company",
    "cfd", "class", "a", "b", "adr", "trust", "fund", "etf", "index",
}


# ─────────────────────────────────────────────
#  UNIVERSE
# ─────────────────────────────────────────────

def load_universe() -> dict:
    """Carica i 1.697 titoli confermati con metadati completi per il risk manager."""
    names = json.loads((ROOT / "stocks_names.json").read_text())
    uni = {}
    with open(ROOT / "stocks_icmarkets.csv") as f:
        for row in csv.DictReader(f):
            if row["affidabilita"] != "confermato":
                continue
            sym = row["symbol"]
            ticker, exch = sym.rsplit(".", 1)
            spec = EXCHANGE_SPECS[exch]
            uni[sym] = {
                "cls": "stock", "exchange": exch,
                "name": names.get(sym, ticker),
                "yf": ticker.replace(".", "-") + spec["yf_suffix"],
                "quote": spec["quote"], "base": None,
                "leverage": 5,                       # PDF: 1:5, margine 20%
                "point": 1.0,                        # 1 punto = 1 unità di prezzo
                "usd_per_point_lot": 1.0,            # 1 azione: 1$/€/£ per punto
                "min_volume": spec["min_volume"],
                "volume_step": spec["volume_step"],
                "commission": spec["commission"],
                "tags": ["STOCK"],
            }
    return uni


def _name_keys(universe: dict) -> dict:
    """Chiavi di match nome→simbolo (precision-first)."""
    keys = {}
    for sym, m in universe.items():
        tokens = [t for t in re.findall(r"[a-z0-9]+", m["name"].lower())
                  if t not in SUFFIX_TOKENS]
        if not tokens:
            continue
        if len(tokens[0]) >= 4 and tokens[0] not in GENERIC_TOKENS:
            keys.setdefault(tokens[0], set()).add(sym)      # es. "apple"
        if len(tokens) >= 2:
            keys.setdefault(" ".join(tokens[:2]), set()).add(sym)  # es. "banco santander"
    return keys


# ─────────────────────────────────────────────
#  DISCOVERY (news → candidati)
# ─────────────────────────────────────────────

def _recency(age_h: float) -> float:
    # Decadimento AGGRESSIVO: una notizia di 12h fa è nel prezzo da 12h.
    # Il vecchio profilo (24h → 0.4) produceva segnali in ritardo di un giorno.
    if age_h < 1:  return 1.0
    if age_h < 3:  return 0.7
    if age_h < 6:  return 0.45
    if age_h < 12: return 0.25
    return 0.1


def _match_title(title: str, name_keys: dict, ticker_by_bare: dict) -> set:
    """Simboli citati in un titolo: nome società (con esclusività dello span
    più lungo) o ticker esplicito. Estratta da discover() per testabilità."""
    low = title.lower()
    # 1) match per nome società con ESCLUSIVITÀ DEL MATCH PIÙ LUNGO:
    #    "Morgan Stanley" non deve attivare "Stanley Black & Decker"
    #    (il cui key 1-token "stanley" è contenuto nello span più lungo).
    spans = []   # (start, end, key_len, syms)
    for key, syms in name_keys.items():
        if len(syms) > 2:      # chiave ambigua → salta
            continue
        for mm in re.finditer(rf"\b{re.escape(key)}\b", low):
            # Chiave 1-token: nel titolo ORIGINALE deve essere un nome
            # proprio (Maiuscolo) — "as equity trading jumps" non è
            # Equity Residential, "Apple beats" sì
            if " " not in key and not title[mm.start()].isupper():
                continue
            spans.append((mm.start(), mm.end(), len(key), syms))
    matched = set()
    for s0, e0, klen, syms in spans:
        contained = any(
            (s1 <= s0 and e0 <= e1) and k1 > klen and other != syms
            for s1, e1, k1, other in spans)
        if not contained:
            matched |= syms
    # 2) ticker solo se ESPLICITO: $AAPL, (AAPL), AAPL:
    for m in re.finditer(r"[\$\(]([A-Z]{2,6})[\):]?", title):
        bare = m.group(1)
        if bare in ticker_by_bare:
            matched |= ticker_by_bare[bare]
    return matched


def discover(days_back: float = 1.0, verbose: bool = False) -> list:
    """Scansiona i feed e mappa le news sui 1.697 titoli. Ritorna candidati."""
    universe = load_universe()
    name_keys = _name_keys(universe)
    ticker_by_bare = {}
    for sym in universe:
        ticker_by_bare.setdefault(sym.rsplit(".", 1)[0], set()).add(sym)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    titles = []
    for url in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries[:40]:
                t = e.get("title", "").strip()
                if not t:
                    continue
                try:
                    from email.utils import parsedate_to_datetime
                    pub = parsedate_to_datetime(e.get("published", ""))
                except Exception:
                    pub = datetime.now(timezone.utc)
                if pub < cutoff:
                    continue
                age = max((datetime.now(timezone.utc) - pub).total_seconds() / 3600, 0)
                titles.append((t, age))
        except Exception:
            pass

    from sentiment import score_sentiment

    hits = {}   # sym -> {"mentions": [...], "score_sum": float}
    for title, age in titles:
        matched = _match_title(title, name_keys, ticker_by_bare)
        if not matched:
            continue
        s = score_sentiment([title])
        signed = s["net_score"] * _recency(age)
        for sym in matched:
            h = hits.setdefault(sym, {"mentions": [], "score_sum": 0.0})
            h["mentions"].append(title[:90])
            h["score_sum"] += signed

    candidates = []
    for sym, h in hits.items():
        n = len(h["mentions"])
        news_score = max(-1.0, min(1.0, h["score_sum"] / max(n, 1) * (1 + 0.3 * (n - 1))))
        candidates.append({
            "symbol": sym, "name": universe[sym]["name"],
            "n_mentions": n, "news_score": round(news_score, 3),
            "titles": h["mentions"][:3], "meta": universe[sym],
        })
    candidates.sort(key=lambda c: (-abs(c["news_score"]), -c["n_mentions"]))
    if verbose:
        print(f"  ✓ {len(titles)} titoli news, {len(candidates)} azioni menzionate")
    return candidates


# ─────────────────────────────────────────────
#  DEEP-DIVE (tecnica + gates, solo sui top)
# ─────────────────────────────────────────────

def analyze_candidates(candidates: list, max_deep: int = 8,
                       verbose: bool = False) -> list:
    """Analisi tecnica sui top candidati + gates. Ritorna i qualificati."""
    import yfinance as yf
    import ta

    out = []
    deep = [c for c in candidates if c["n_mentions"] >= 1 and abs(c["news_score"]) >= 0.15]
    for c in deep[:max_deep]:
        try:
            t = yf.Ticker(c["meta"]["yf"])
            h = t.history(period="1y", auto_adjust=True)
            if len(h) < 60:
                continue
            closes = list(h["Close"].values.astype(float))
            cur = closes[-1]
            rsi = ta.rsi(closes)
            _, _, _, macd_bull = ta.macd(closes)
            atr = ta.atr(h)
            ma50 = ta.ma(h["Close"], 50)
            ma200 = ta.ma(h["Close"], 200)
            supp, res = ta.support_resistance(h)
            # Estensione del prezzo: quanto del movimento è GIÀ avvenuto
            ema20 = ta.ema(closes, 20)[-1] if len(closes) >= 20 else cur
            stretch = (cur - ema20) / atr if atr else 0.0
            burst = (cur - closes[-4]) / atr if atr and len(closes) >= 4 else 0.0

            tech = 0.0
            if ma50:
                tech += 0.35 if cur > ma50 else -0.35
            if ma50 and ma200:
                tech += 0.25 if ma50 > ma200 else -0.25
            tech += 0.25 if macd_bull else -0.25
            if tech > 0 and rsi >= 74: tech *= 0.5
            if tech < 0 and rsi <= 26: tech *= 0.5

            # Earnings: blackout ≤2gg (lezione AVGO -15% overnight);
            # a 3-7gg si attiva invece lo studio del DRIFT PRE-EARNINGS
            # (eventstudy): se storicamente il titolo sale verso la
            # trimestrale, il segnale concorde riceve un bonus.
            blackout = False
            drift_bonus, drift_note = 0.0, ""
            try:
                cal = t.calendar
                ed = cal.get("Earnings Date") if cal is not None else None
                if ed is not None:
                    ed0 = list(ed)[0] if hasattr(ed, "__iter__") and not isinstance(ed, str) else ed
                    if hasattr(ed0, "date"):
                        ed0 = ed0.date()
                    days = (ed0 - datetime.now().date()).days
                    if 0 <= days <= 2:
                        blackout = True
                        c["gate_reason"] = f"earnings tra {days}gg — blackout"
                    elif 3 <= days <= 7:
                        from eventstudy import earnings_drift
                        dr = earnings_drift(c["meta"]["yf"])
                        if dr.get("favorable_long"):
                            drift_bonus = +0.10
                            drift_note = (f"drift pre-earnings favorevole: "
                                          f"{dr['mean_pct']:+.1f}% medio nei 5gg pre "
                                          f"({int(dr['pos_rate']*100)}%, n={dr['n']}) — earnings tra {days}gg")
                        elif dr.get("favorable_short"):
                            drift_bonus = -0.10
                            drift_note = (f"drift pre-earnings negativo: "
                                          f"{dr['mean_pct']:+.1f}% medio nei 5gg pre "
                                          f"({int(dr['pos_rate']*100)}%, n={dr['n']}) — earnings tra {days}gg")
            except Exception:
                pass

            composite = 0.5 * c["news_score"] + 0.5 * tech + drift_bonus
            if drift_note:
                c["drift_note"] = drift_note
            direction = "LONG" if composite > 0 else "SHORT"
            sign = 1 if composite > 0 else -1

            # ANTI-INSEGUIMENTO: la news spesso RACCONTA un movimento già
            # avvenuto (il "ritardo enorme" dei segnali nasce qui). Se il
            # prezzo è già lontano dalla sua media, non si insegue.
            chase = (sign > 0 and (stretch > 2.2 or burst > 2.5)) or \
                    (sign < 0 and (stretch < -2.2 or burst < -2.5))
            if chase and "gate_reason" not in c:
                c["gate_reason"] = (f"già esteso ({stretch:+.1f} ATR da EMA20, "
                                    f"{burst:+.1f} ATR in 3gg) — non inseguire")

            gate = (not blackout and not chase
                    and abs(composite) >= 0.5
                    and c["news_score"] * sign > 0.1
                    and tech * sign > 0.1)
            if not gate and "gate_reason" not in c:
                c["gate_reason"] = (f"composite {abs(composite):.2f} < 0.5"
                                    if abs(composite) < 0.5 else "news/tech non concordi")

            # Esteso ma non estremo → niente ingresso a mercato: ordine
            # LIMIT sul ritracciamento verso la media (dove "si livella")
            if gate and abs(stretch) > 1.2:
                c["entry_mode"] = "pullback"
                c["entry_limit"] = round(ema20 + (0.3 * atr if sign > 0 else -0.3 * atr), 2)

            c.update({"tech_score": round(tech, 3), "composite": round(composite, 3),
                      "direction": direction, "gate": gate,
                      "price": round(cur, 2), "rsi": rsi, "atr": atr,
                      "stretch": round(stretch, 2), "ema20": round(ema20, 2),
                      "support": supp, "resistance": res})
            out.append(c)
            if verbose:
                flag = "✅" if gate else "  "
                print(f"  {flag} {c['symbol']:12s} {direction:5s} comp={composite:+.2f} "
                      f"(news {c['news_score']:+.2f} / tech {tech:+.2f}) "
                      f"| {c.get('gate_reason','PASS')}")
        except Exception:
            pass
    return out


def scan(verbose: bool = False) -> dict:
    """Pipeline completa. Ritorna candidati analizzati + ticket qualificati."""
    from risk_manager import build_ticket

    cands = discover(verbose=verbose)
    analyzed = analyze_candidates(cands, verbose=verbose)
    tickets = []
    for c in analyzed:
        if not c.get("gate"):
            continue
        reasons = [f"news: {c['titles'][0][:60]}",
                   f"sentiment {c['news_score']:+.2f} / tech {c['tech_score']:+.2f} concordi"]
        if c.get("drift_note"):
            reasons.append(c["drift_note"])
        entry = c["price"]
        if c.get("entry_mode") == "pullback":
            entry = c["entry_limit"]
            reasons.append(f"prezzo esteso {c.get('stretch', 0):+.1f} ATR da EMA20 → "
                           f"ordine LIMIT a {entry} sul ritracciamento (NON a mercato)")
        tk = build_ticket(c["symbol"], c["direction"], entry,
                          atr_val=c["atr"], support=c["support"],
                          resistance=c["resistance"],
                          confidence=abs(c["composite"]), reasons=reasons,
                          meta=c["meta"])
        tk["asset_class"] = "stock"
        tk["company"] = c["name"]
        tk["entry_type"] = "LIMIT" if c.get("entry_mode") == "pullback" else "MARKET"
        tickets.append(tk)
    return {"candidates": analyzed, "tickets": tickets,
            "n_discovered": len(cands)}


if __name__ == "__main__":
    print("\nStock Engine — scan live\n" + "═" * 64)
    uni = load_universe()
    print(f"Universo: {len(uni)} azioni CFD IC Markets EU "
          f"(estratte da MT5 il 10/07/2026)\n")
    r = scan(verbose=True)
    print(f"\n🎫 Ticket qualificati: {len(r['tickets'])}")
    from risk_manager import format_ticket
    for tk in r["tickets"]:
        print(format_ticket(tk))
