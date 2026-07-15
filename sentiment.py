#!/usr/bin/env python3
"""
Sentiment NLP — Analisi del sentiment delle news finanziarie
=============================================================
Trasforma la "velocity" (conteggio articoli) in sentiment reale:
30 articoli su "SMR wins $1B contract" ≠ 30 articoli su "SMR faces SEC probe".

Due backend:
  1. LEXICON (default) — dizionario finanziario stile Loughran-McDonald.
     Zero dipendenze pesanti, istantaneo, robusto su GitHub Actions.
  2. FINBERT (opzionale) — modello transformer ProsusAI/finbert.
     Qualità superiore ma richiede `pip install transformers torch`.
     Si attiva automaticamente se disponibile e SENTIMENT_BACKEND=finbert.

API principale:
  score_sentiment(texts: list[str]) -> dict con:
    - net_score   : float in [-1, +1]  (negativo→positivo)
    - label       : POSITIVE / NEGATIVE / NEUTRAL
    - pos / neg / neu : conteggi
    - confidence  : 0-1 (quanto è netto il segnale)
"""

import os
import re
from functools import lru_cache

# ─────────────────────────────────────────────
#  LEXICON FINANZIARIO (Loughran-McDonald inspired)
# ─────────────────────────────────────────────
# Pesi: parole più forti pesano di più. Tarato su headline di mercato.

_POSITIVE = {
    # Catalyst forti
    "wins": 2.0, "win": 1.5, "awarded": 2.0, "award": 1.5, "secures": 1.8,
    "contract": 1.2, "deal": 1.0, "partnership": 1.3, "approval": 2.0,
    "approved": 2.0, "approves": 1.8, "fda": 0.5, "breakthrough": 2.0,
    # Performance
    "beats": 2.0, "beat": 1.8, "tops": 1.8, "surge": 2.0, "surges": 2.0,
    "soars": 2.0, "soar": 1.8, "jumps": 1.8, "jump": 1.5, "rally": 1.5,
    "rallies": 1.5, "gains": 1.3, "gain": 1.0, "climbs": 1.3, "rises": 1.0,
    "record": 1.5, "high": 0.8, "outperform": 1.8, "strong": 1.2,
    "growth": 1.2, "profit": 1.2, "raises": 1.0, "boost": 1.5, "boosts": 1.5,
    # Analyst / rating
    "upgrade": 2.0, "upgrades": 2.0, "upgraded": 2.0, "buy": 1.2,
    "overweight": 1.5, "bullish": 2.0, "outperformed": 1.8,
    # Business
    "expansion": 1.2, "launches": 1.0, "launch": 0.8, "milestone": 1.3,
    "demand": 0.8, "accelerate": 1.0, "accelerates": 1.0, "wins": 2.0,
    "investment": 0.8, "funding": 1.0, "raised": 0.8, "acquire": 1.0,
    "acquisition": 1.0, "guidance": 0.3, "exceeds": 1.8, "exceeded": 1.8,
}

_NEGATIVE = {
    # Catalyst negativi forti
    "lawsuit": 2.0, "sues": 1.8, "sued": 1.8, "probe": 2.0, "investigation": 1.8,
    "investigates": 1.8, "sec": 0.5, "fraud": 2.5, "scandal": 2.5,
    "recall": 2.0, "halt": 1.8, "halts": 1.8, "halted": 1.8, "ban": 1.8,
    "banned": 1.8, "delay": 1.5, "delays": 1.5, "delayed": 1.5,
    "setback": 1.8, "warning": 1.5, "warns": 1.5,
    # Performance negativa
    "miss": 2.0, "misses": 2.0, "missed": 1.8, "plunge": 2.2, "plunges": 2.2,
    "plummet": 2.2, "plummets": 2.2, "crash": 2.2, "crashes": 2.2,
    "drops": 1.5, "drop": 1.3, "falls": 1.5, "fall": 1.2, "sinks": 1.8,
    "tumble": 2.0, "tumbles": 2.0, "slumps": 1.8, "slump": 1.8,
    "declines": 1.3, "decline": 1.2, "loss": 1.5, "losses": 1.5,
    "weak": 1.5, "weakness": 1.5, "low": 0.8, "slides": 1.5, "slide": 1.3,
    "sell-off": 2.0, "selloff": 2.0, "downturn": 1.5,
    # Analyst / rating
    "downgrade": 2.0, "downgrades": 2.0, "downgraded": 2.0, "sell": 1.2,
    "underweight": 1.5, "bearish": 2.0, "cut": 1.0, "cuts": 1.0,
    "underperform": 1.8, "underperformed": 1.8,
    # Business
    "bankruptcy": 2.5, "bankrupt": 2.5, "layoffs": 1.8, "layoff": 1.8,
    "cuts": 1.0, "concerns": 1.2, "concern": 1.0, "risk": 0.8, "risks": 0.8,
    "fears": 1.5, "fear": 1.3, "slowdown": 1.5, "shortfall": 1.8,
    "disappointing": 2.0, "disappoints": 2.0, "struggles": 1.5, "struggle": 1.3,
}

# Verbi di PURA price-action: raccontano un movimento GIÀ avvenuto sul
# grafico (quindi già prezzato), non un catalyst nuovo. Pesarli come i
# fondamentali significa comprare DOPO la salita ("Stock Gains as...") —
# la causa n.1 dei segnali in ritardo. Restano direzionali ma valgono il 40%.
_PRICE_ACTION = {
    "surge", "surges", "soars", "soar", "jumps", "jump", "rally", "rallies",
    "gains", "gain", "climbs", "rises", "record", "high",
    "plunge", "plunges", "plummet", "plummets", "crash", "crashes",
    "drops", "drop", "falls", "fall", "sinks", "tumble", "tumbles",
    "slumps", "slump", "slides", "slide", "sell-off", "selloff",
    "declines", "decline", "low",
}
_PRICE_ACTION_W = 0.4

# Negatori che invertono il sentiment della parola seguente
_NEGATORS = {"not", "no", "never", "without", "fails", "fail", "failed", "lacks", "lack"}


def _tokenize(text: str) -> list:
    return re.findall(r"[a-z\-]+", text.lower())


def _lexicon_score(text: str) -> float:
    """Score grezzo di un singolo testo: somma pesi pos - neg, normalizzato."""
    tokens = _tokenize(text)
    score = 0.0
    hits = 0
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i > 0 else ""
        flip = -1.0 if prev in _NEGATORS else 1.0
        damp = _PRICE_ACTION_W if tok in _PRICE_ACTION else 1.0
        if tok in _POSITIVE:
            score += _POSITIVE[tok] * damp * flip
            hits += 1
        elif tok in _NEGATIVE:
            score -= _NEGATIVE[tok] * damp * flip
            hits += 1
    if hits == 0:
        return 0.0
    # Normalizza per non far esplodere headline lunghe; clamp a [-1, 1]
    norm = score / (hits ** 0.5)
    return max(-1.0, min(1.0, norm / 2.0))


# ─────────────────────────────────────────────
#  BACKEND FINBERT (opzionale, lazy)
# ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_finbert():
    """Carica FinBERT una sola volta. Ritorna None se non disponibile."""
    try:
        from transformers import pipeline
        return pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            truncation=True,
            max_length=128,
        )
    except Exception:
        return None


def _finbert_score(texts: list) -> list:
    """Ritorna lista di score in [-1,1] per ogni testo, o None se FinBERT off."""
    clf = _get_finbert()
    if clf is None:
        return None
    out = []
    try:
        for r in clf(texts):
            lbl = r["label"].lower()
            sc  = r["score"]
            if lbl == "positive":
                out.append(sc)
            elif lbl == "negative":
                out.append(-sc)
            else:
                out.append(0.0)
        return out
    except Exception:
        return None


# ─────────────────────────────────────────────
#  API PRINCIPALE
# ─────────────────────────────────────────────

def score_sentiment(texts: list) -> dict:
    """
    Analizza una lista di testi (titoli di news) e ritorna il sentiment aggregato.

    Returns dict:
      net_score  : float [-1,+1]
      label      : POSITIVE / NEGATIVE / NEUTRAL
      pos, neg, neu : conteggi articoli per categoria
      confidence : 0-1 (frazione di articoli con segnale netto)
      backend    : 'finbert' | 'lexicon'
      n          : numero testi analizzati
    """
    texts = [t for t in (texts or []) if t and t.strip()]
    if not texts:
        return {"net_score": 0.0, "label": "NEUTRAL", "pos": 0, "neg": 0,
                "neu": 0, "confidence": 0.0, "backend": "none", "n": 0}

    backend = "lexicon"
    scores = None
    if os.environ.get("SENTIMENT_BACKEND", "lexicon").lower() == "finbert":
        scores = _finbert_score(texts)
        if scores is not None:
            backend = "finbert"
    if scores is None:
        scores = [_lexicon_score(t) for t in texts]

    pos = sum(1 for s in scores if s > 0.15)
    neg = sum(1 for s in scores if s < -0.15)
    neu = len(scores) - pos - neg
    net = sum(scores) / len(scores)

    if net > 0.12:
        label = "POSITIVE"
    elif net < -0.12:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"

    confidence = (pos + neg) / len(scores)

    return {
        "net_score": round(net, 3),
        "label": label,
        "pos": pos, "neg": neg, "neu": neu,
        "confidence": round(confidence, 2),
        "backend": backend,
        "n": len(texts),
    }


def sentiment_score_adjustment(sent: dict, base_alert: bool = False) -> tuple:
    """
    Traduce il sentiment in un aggiustamento di score per il segnale.
    Ritorna (delta_score, note, flip_direction).

    Logica:
      - Sentiment fortemente positivo + buzz → boost (catalyst reale)
      - Sentiment fortemente negativo → penalità o flip a bearish
        (la velocity è guidata da cattive notizie, non da hype rialzista)
    """
    net  = sent.get("net_score", 0.0)
    conf = sent.get("confidence", 0.0)
    label = sent.get("label", "NEUTRAL")

    delta = 0
    note = ""
    flip = False

    if label == "POSITIVE" and conf >= 0.3:
        delta = int(round(net * conf * 25))      # max ~+18
        note = f"Sentiment POSITIVO ({net:+.2f}, {int(conf*100)}% articoli netti) — catalyst rialzista"
    elif label == "NEGATIVE" and conf >= 0.3:
        delta = -int(round(abs(net) * conf * 30))  # penalità più aggressiva
        note = f"Sentiment NEGATIVO ({net:+.2f}, {int(conf*100)}% articoli netti) — buzz da cattive notizie"
        if net < -0.35 and conf >= 0.5:
            flip = True
            note += " → possibile segnale SHORT"
    elif label == "NEUTRAL":
        note = f"Sentiment neutro ({net:+.2f}) — buzz senza direzione chiara"

    return delta, note, flip


# ─────────────────────────────────────────────
#  TEST STANDALONE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ["NuScale wins $1B government contract for SMR deployment",
         "NuScale SMR awarded DOE grant, shares surge",
         "Analysts upgrade NuScale to buy on nuclear demand"],
        ["Broadcom plunges 14% as guidance disappoints",
         "Broadcom faces selloff after weak software sales",
         "AVGO tumbles, analysts cut price targets"],
        ["Intel announces new CEO amid restructuring",
         "Intel reports quarterly results in line with estimates"],
        ["Rocket Lab stock rises after successful launch",
         "Rocket Lab faces SEC probe over disclosures, shares drop"],
    ]
    print(f"\nSentiment NLP test — backend: {os.environ.get('SENTIMENT_BACKEND','lexicon')}\n" + "─"*60)
    for batch in tests:
        s = score_sentiment(batch)
        delta, note, flip = sentiment_score_adjustment(s)
        print(f"\n  {batch[0][:60]}...")
        print(f"  → {s['label']} | net {s['net_score']:+.2f} | conf {s['confidence']} "
              f"| pos:{s['pos']} neg:{s['neg']} neu:{s['neu']} [{s['backend']}]")
        print(f"  → score delta: {delta:+d} | flip_short: {flip}")
        print(f"  → {note}")
