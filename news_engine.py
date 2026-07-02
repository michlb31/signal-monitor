#!/usr/bin/env python3
"""
News Engine — Classificazione eventi macro → mapping su strumenti IC Markets
=============================================================================
Evoluzione forex delle SIGNAL_RULES azionarie: stesso pattern
(regex pesate + time decay + velocity), dominio macro/geopolitico.

Flusso:
  1. collect_titles()   — Google News RSS su ~10 temi macro (feedparser)
  2. classify()         — matcha EVENT_RULES sui titoli → eventi rilevati
  3. map_to_instruments() — espande gli impatti (valuta o strumento diretto)
                            su tutto l'universo, con segno e peso
  4. sentiment.py       — raffina l'intensità (lexicon già esistente)

Output: {symbol: {"score": -1..+1, "events": [...], "n_titles": N}}
  score > 0 = pressione rialzista sullo strumento, < 0 ribassista.

Convenzione impatti:
  ("USD", "BULL", w)     → il dollaro si rafforza (espanso su tutte le coppie USD)
  ("XAUUSD", "BEAR", w)  → impatto diretto sullo strumento
"""

import math
import re
import urllib.parse
from datetime import datetime, timezone, timedelta

import feedparser

from instruments import INSTRUMENTS, pairs_for_currency, CURRENCIES

feedparser.USER_AGENT = "FXSignalMonitor/1.0 (research; micheleguidi83@icloud.com)"

# ─────────────────────────────────────────────
#  TEMI DI RICERCA (Google News RSS)
# ─────────────────────────────────────────────

THEMES = {
    "FED":      "federal reserve interest rates",
    "ECB":      "ECB european central bank rates",
    "BOE":      "bank of england rates",
    "BOJ":      "bank of japan yen",
    "CPI_US":   "US inflation CPI data",
    "JOBS_US":  "nonfarm payrolls US jobs report",
    "OPEC":     "OPEC oil production",
    "GEO":      "geopolitical conflict escalation",
    "CHINA":    "china economy stimulus",
    "DOLLAR":   "US dollar forex",
    "GOLD":     "gold price",
}

# ─────────────────────────────────────────────
#  EVENT RULES — il mapping intelligente
#  Estendere = aggiungere un dict. I pesi verranno
#  ricalibrati dal feedback loop (db outcomes).
# ─────────────────────────────────────────────

EVENT_RULES = [
    # ── FED / politica monetaria USA ──────────────────────────────
    {"name": "Fed hawkish",
     "pattern": r"(fed|fomc|powell)\b.{0,80}(hawkish|higher for longer|rate hike|raise rates|tighten|restrictive|no cuts)",
     "impacts": [("USD", "BULL", 0.9), ("XAUUSD", "BEAR", 0.85), ("USTEC", "BEAR", 0.7),
                 ("US500", "BEAR", 0.6), ("JP225", "BEAR", 0.4)]},
    {"name": "Fed dovish",
     "pattern": r"(fed|fomc|powell)\b.{0,80}(dovish|rate cut|cut rates|cuts rates|easing|pivot|pause)",
     "impacts": [("USD", "BEAR", 0.9), ("XAUUSD", "BULL", 0.85), ("USTEC", "BULL", 0.7),
                 ("US500", "BULL", 0.6)]},
    # ── Inflazione USA ─────────────────────────────────────────────
    {"name": "CPI USA caldo",
     "pattern": r"(cpi|inflation)\b.{0,60}(hot|hotter|above (forecast|expectation|estimate)s?|higher than expected|accelerat|surge|jump|rise[sd]? more)",
     "impacts": [("USD", "BULL", 0.8), ("XAUUSD", "BEAR", 0.7), ("US500", "BEAR", 0.6),
                 ("USTEC", "BEAR", 0.65)]},
    {"name": "CPI USA freddo",
     "pattern": r"(cpi|inflation)\b.{0,60}(cool|cooler|below (forecast|expectation|estimate)s?|lower than expected|slow|ease[sd]?|fell|drops)",
     "impacts": [("USD", "BEAR", 0.8), ("XAUUSD", "BULL", 0.7), ("US500", "BULL", 0.6),
                 ("USTEC", "BULL", 0.65)]},
    # ── Occupazione USA ───────────────────────────────────────────
    {"name": "Jobs USA forti",
     "pattern": r"(nonfarm|payrolls|jobs report|employment)\b.{0,60}(strong|beat|above|surge|robust|blowout|tops)",
     "impacts": [("USD", "BULL", 0.8), ("XAUUSD", "BEAR", 0.6)]},
    {"name": "Jobs USA deboli",
     "pattern": r"(nonfarm|payrolls|jobs report|unemployment)\b.{0,60}(weak|miss|below|disappoint|slump|falls short|rises)",
     "impacts": [("USD", "BEAR", 0.8), ("XAUUSD", "BULL", 0.6), ("US500", "BEAR", 0.35)]},
    # ── BCE ────────────────────────────────────────────────────────
    {"name": "BCE hawkish",
     "pattern": r"(ecb|lagarde)\b.{0,80}(hawkish|rate hike|raise rates|tighten|restrictive)",
     "impacts": [("EUR", "BULL", 0.85), ("GER40", "BEAR", 0.45)]},
    {"name": "BCE dovish",
     "pattern": r"(ecb|lagarde)\b.{0,80}(dovish|rate cut|cut rates|cuts rates|easing|pause)",
     "impacts": [("EUR", "BEAR", 0.85), ("GER40", "BULL", 0.45)]},
    # ── BoE ────────────────────────────────────────────────────────
    {"name": "BoE hawkish",
     "pattern": r"(bank of england|boe|bailey)\b.{0,80}(hawkish|rate hike|raise rates|tighten)",
     "impacts": [("GBP", "BULL", 0.85), ("UK100", "BEAR", 0.4)]},
    {"name": "BoE dovish",
     "pattern": r"(bank of england|boe|bailey)\b.{0,80}(dovish|rate cut|cut rates|cuts rates|easing)",
     "impacts": [("GBP", "BEAR", 0.85), ("UK100", "BULL", 0.4)]},
    # ── BoJ / yen ─────────────────────────────────────────────────
    {"name": "BoJ hawkish",
     "pattern": r"(bank of japan|boj|ueda)\b.{0,80}(hawkish|rate hike|raise rates|tighten|ends? negative)",
     "impacts": [("JPY", "BULL", 0.9), ("JP225", "BEAR", 0.55)]},
    {"name": "BoJ dovish",
     "pattern": r"(bank of japan|boj|ueda)\b.{0,80}(dovish|hold|maintain|ultra-?loose|stimulus)",
     "impacts": [("JPY", "BEAR", 0.8), ("JP225", "BULL", 0.5)]},
    {"name": "Intervento FX Giappone",
     "pattern": r"(japan|mof|tokyo)\b.{0,60}(intervention|intervene[sd]?|prop up|defend).{0,30}(yen|currency)?",
     "impacts": [("JPY", "BULL", 0.9)]},
    # ── Geopolitica ───────────────────────────────────────────────
    {"name": "Escalation geopolitica",
     "pattern": r"(escalat|missile|strike[s]?|attack|invasion|war)\b.{0,80}(iran|israel|russia|ukraine|middle east|taiwan|red sea)",
     "impacts": [("XAUUSD", "BULL", 0.85), ("XTIUSD", "BULL", 0.75), ("XBRUSD", "BULL", 0.75),
                 ("JPY", "BULL", 0.5), ("CHF", "BULL", 0.5), ("US500", "BEAR", 0.45)]},
    {"name": "De-escalation geopolitica",
     "pattern": r"(ceasefire|cease-fire|peace (deal|talks|agreement)|de-?escalat|truce|diplomatic breakthrough)",
     "impacts": [("XAUUSD", "BEAR", 0.8), ("XTIUSD", "BEAR", 0.6), ("XBRUSD", "BEAR", 0.6),
                 ("US500", "BULL", 0.4)]},
    # ── OPEC / petrolio ───────────────────────────────────────────
    {"name": "OPEC taglia produzione",
     "pattern": r"(opec|saudi)\b.{0,60}(cut|reduce|curb|extend cuts?).{0,40}(production|output|supply)",
     "impacts": [("XTIUSD", "BULL", 0.9), ("XBRUSD", "BULL", 0.9), ("CAD", "BULL", 0.45)]},
    {"name": "OPEC aumenta produzione",
     "pattern": r"(opec|saudi)\b.{0,60}(raise|boost|increase|hike).{0,40}(production|output|supply)",
     "impacts": [("XTIUSD", "BEAR", 0.9), ("XBRUSD", "BEAR", 0.9), ("CAD", "BEAR", 0.4)]},
    {"name": "Domanda petrolio debole",
     "pattern": r"(oil|crude)\b.{0,60}(demand (concerns|worries|slump)|glut|oversupply|inventories (rise|build|surge))",
     "impacts": [("XTIUSD", "BEAR", 0.7), ("XBRUSD", "BEAR", 0.7)]},
    # ── Risk sentiment ────────────────────────────────────────────
    {"name": "Risk-off",
     "pattern": r"(sell-?off|market (rout|panic|plunge|turmoil)|vix (spike|surge)|stocks (tumble|plunge|crash)|flight to safety)",
     "impacts": [("JPY", "BULL", 0.6), ("CHF", "BULL", 0.6), ("XAUUSD", "BULL", 0.5),
                 ("US500", "BEAR", 0.7), ("USTEC", "BEAR", 0.7), ("AUD", "BEAR", 0.5)]},
    {"name": "Risk-on",
     "pattern": r"(stocks? (rally|surge|record high)|risk appetite|optimism (grows|returns)|relief rally)",
     "impacts": [("US500", "BULL", 0.6), ("USTEC", "BULL", 0.6), ("JPY", "BEAR", 0.45),
                 ("XAUUSD", "BEAR", 0.35), ("AUD", "BULL", 0.4)]},
    # ── Cina ──────────────────────────────────────────────────────
    {"name": "Cina stimolo",
     "pattern": r"(china|beijing|pboc)\b.{0,70}(stimulus|rate cut|easing|support (measures|package)|boost)",
     "impacts": [("AUD", "BULL", 0.6), ("AUS200", "BULL", 0.5), ("XTIUSD", "BULL", 0.4),
                 ("NZD", "BULL", 0.5)]},
    {"name": "Cina debolezza",
     "pattern": r"(china|chinese)\b.{0,70}(slowdown|deflation|property crisis|weak (data|demand|growth)|contraction)",
     "impacts": [("AUD", "BEAR", 0.6), ("AUS200", "BEAR", 0.5), ("XTIUSD", "BEAR", 0.4),
                 ("NZD", "BEAR", 0.5)]},
    # ── Dollaro diretto ───────────────────────────────────────────
    {"name": "Dollaro forte",
     "pattern": r"(dollar|dxy|greenback)\b.{0,50}(surge|rally|rallies|strengthen|soar|climb|jump|multi-?\w+ high)",
     "impacts": [("USD", "BULL", 0.6), ("XAUUSD", "BEAR", 0.5)]},
    {"name": "Dollaro debole",
     "pattern": r"(dollar|dxy|greenback)\b.{0,50}(fall|drop|weaken|slump|slide|tumble|multi-?\w+ low)",
     "impacts": [("USD", "BEAR", 0.6), ("XAUUSD", "BULL", 0.5)]},
    # ── Fiscale USA ───────────────────────────────────────────────
    {"name": "Stress fiscale USA",
     "pattern": r"(government shutdown|debt ceiling|credit (downgrade|rating cut)|fiscal crisis)",
     "impacts": [("USD", "BEAR", 0.55), ("XAUUSD", "BULL", 0.55), ("US500", "BEAR", 0.4)]},
]


# ─────────────────────────────────────────────
#  RACCOLTA TITOLI
# ─────────────────────────────────────────────

def collect_titles(days_back: float = 1.5, per_theme: int = 15) -> list:
    """Raccoglie titoli recenti dai temi macro. Ritorna [(title, age_hours)]."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    out, seen = [], set()
    for tag, query in THEMES.items():
        url = (f"https://news.google.com/rss/search?"
               f"q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en")
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries[:per_theme]:
                title = e.get("title", "").strip()
                if not title or title.lower() in seen:
                    continue
                try:
                    from email.utils import parsedate_to_datetime
                    pub = parsedate_to_datetime(e.get("published", ""))
                except Exception:
                    pub = datetime.now(timezone.utc)
                if pub < cutoff:
                    continue
                age_h = max((datetime.now(timezone.utc) - pub).total_seconds() / 3600, 0)
                seen.add(title.lower())
                out.append((title, age_h))
        except Exception:
            pass
    return out


def _recency(age_hours: float) -> float:
    """Time decay (stessa filosofia del monitor azionario, tarata sul forex)."""
    if age_hours < 2:   return 1.0
    if age_hours < 6:   return 0.85
    if age_hours < 12:  return 0.65
    if age_hours < 24:  return 0.45
    return 0.25


# ─────────────────────────────────────────────
#  CLASSIFICAZIONE + MAPPING
# ─────────────────────────────────────────────

# Negazioni che invertono/invalidano il senso della frase matchata
# (es. "Rate Cuts Are Still OFF THE TABLE" NON è dovish)
NEGATION_VETO = re.compile(
    r"off the table|rule[sd]? out|no (rate )?(cut|hike)|not (cut|hike|consider)"
    r"|unlikely|won'?t|will not|denies|dismiss|push(es|ed)? back",
    re.IGNORECASE)


def classify(titles: list) -> list:
    """Matcha le EVENT_RULES. Ritorna eventi con forza = f(n_match, recency).
    I titoli con negazione esplicita vengono scartati (anti falso-positivo)."""
    events = []
    for rule in EVENT_RULES:
        rx = re.compile(rule["pattern"], re.IGNORECASE)
        matches = [(t, age) for t, age in titles
                   if rx.search(t) and not NEGATION_VETO.search(t)]
        if not matches:
            continue
        best_recency = max(_recency(age) for _, age in matches)
        # log-scale sul numero di titoli: 1→1.0, 3→1.5, 7→2.0 (cap)
        breadth = min(1.0 + math.log2(len(matches)) * 0.5, 2.0)
        events.append({
            "rule": rule["name"],
            "strength": round(best_recency * breadth, 2),
            "n_matches": len(matches),
            "impacts": rule["impacts"],
            "examples": [t for t, _ in matches[:2]],
        })
    return sorted(events, key=lambda e: -e["strength"])


def map_to_instruments(events: list) -> dict:
    """Espande gli impatti su tutto l'universo. Score finale in [-1, +1]."""
    raw = {}  # symbol -> somma contributi

    def add(symbol, signed_weight, event_name):
        if symbol not in INSTRUMENTS:
            return
        raw.setdefault(symbol, {"sum": 0.0, "events": set()})
        raw[symbol]["sum"] += signed_weight
        raw[symbol]["events"].add(event_name)

    for ev in events:
        for target, direction, weight in ev["impacts"]:
            signed = weight * ev["strength"] * (1 if direction == "BULL" else -1)
            if target in CURRENCIES:
                for pair, sign in pairs_for_currency(target):
                    add(pair, signed * sign, ev["rule"])
            else:
                add(target, signed, ev["rule"])

    out = {}
    for sym, d in raw.items():
        # tanh squash: somma 2.0 → ~0.76, 3.0 → ~0.90
        out[sym] = {
            "score": round(math.tanh(d["sum"] / 2.0), 3),
            "events": sorted(d["events"]),
        }
    return out


def analyze_news(days_back: float = 1.5) -> dict:
    """Pipeline completa. Ritorna {events, by_instrument, n_titles}."""
    titles = collect_titles(days_back=days_back)
    events = classify(titles)
    mapped = map_to_instruments(events)

    # Raffinamento sentiment (lexicon esistente) sull'intero corpus
    sentiment_net = 0.0
    try:
        from sentiment import score_sentiment
        s = score_sentiment([t for t, _ in titles])
        sentiment_net = s.get("net_score", 0.0)
    except Exception:
        pass

    return {
        "n_titles": len(titles),
        "events": events,
        "by_instrument": mapped,
        "corpus_sentiment": sentiment_net,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────
#  TEST STANDALONE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\nNews Engine — analisi macro live\n" + "═" * 62)
    r = analyze_news()
    print(f"Titoli raccolti: {r['n_titles']} | Sentiment corpus: {r['corpus_sentiment']:+.2f}\n")
    print("EVENTI RILEVATI:")
    for ev in r["events"][:10]:
        print(f"  [{ev['strength']:.2f}] {ev['rule']} ({ev['n_matches']} titoli)")
        print(f"        es: {ev['examples'][0][:75]}")
    print("\nIMPATTO SU STRUMENTI (|score| ≥ 0.15):")
    ranked = sorted(r["by_instrument"].items(), key=lambda kv: -abs(kv[1]["score"]))
    for sym, d in ranked:
        if abs(d["score"]) < 0.15:
            continue
        arrow = "📈" if d["score"] > 0 else "📉"
        print(f"  {arrow} {sym:8s} {d['score']:+.2f}  ← {', '.join(d['events'][:3])}")
