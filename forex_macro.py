#!/usr/bin/env python3
"""
Forex Macro — Intermarket bias per XAU/USD e major FX
======================================================
I metalli e il forex si muovono sui DRIVER MACRO, non su news aziendali.
Questo modulo costruisce un "bias fondamentale" combinando:

  - DXY (US Dollar Index)        → dollaro su = oro/EUR giù
  - Rendimenti Treasury (5/10/30Y)→ yield su = oro giù
  - Rendimenti REALI (TIPS/DFII10)→ il driver #1 dell'oro (FRED, opz.)
  - Silver                        → conferma/divergenza metalli (corr +0.80)
  - VIX                           → risk-on/off, safe haven flows
  - Crude oil                     → proxy inflazione

Output: bias BULLISH / BEARISH / NEUTRAL con punteggio e breakdown,
da incrociare con l'analisi tecnica per decidere LONG/SHORT.

yfinance copre tutto SENZA api key. I rendimenti reali (FRED) sono
opzionali: imposta la env var FRED_API_KEY (gratuita su fred.stlouisfed.org).
"""

import os
import warnings
from datetime import datetime, timezone

import yfinance as yf
import pandas as pd
import requests

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
#  STRUMENTI INTERMARKET
# ─────────────────────────────────────────────

INSTRUMENTS = {
    "gold":   "GC=F",       # oro (XAU proxy)
    "dxy":    "DX-Y.NYB",   # dollar index
    "y10":    "^TNX",       # 10Y yield
    "y5":     "^FVX",       # 5Y yield
    "y30":    "^TYX",       # 30Y yield
    "y3m":    "^IRX",       # 13-week T-bill (per la pendenza della curva)
    "silver": "SI=F",
    "vix":    "^VIX",
    "oil":    "CL=F",
}

# Quanto ciascun driver "pesa" sul bias oro (segno = direzione su oro)
# Negativo = quando sale, l'oro tende a scendere
DRIVER_WEIGHTS = {
    "dxy":    -1.5,   # dollaro forte → oro debole (peso alto)
    "y10":    -1.3,   # yield nominali su → oro giù
    "y5":     -1.0,
    "real_yield": -2.0,  # rendimento reale: driver più forte (se disponibile)
    "silver": +1.2,   # silver su → conferma forza metalli
    "vix":    +0.5,   # VIX su → safe haven (ma debole, può invertirsi in deleveraging)
}


def _fetch_changes(period: str = "5d") -> dict:
    """Recupera prezzo e variazione % giornaliera per ogni strumento."""
    out = {}
    for name, tk in INSTRUMENTS.items():
        try:
            h = yf.Ticker(tk).history(period=period)["Close"]
            h.index = h.index.date
            if len(h) >= 2:
                price = float(h.iloc[-1])
                chg = (price / float(h.iloc[-2]) - 1) * 100
                out[name] = {"price": price, "chg_pct": round(chg, 2)}
        except Exception:
            pass
    return out


def get_real_yield() -> dict:
    """
    Rendimento reale 10Y (DFII10) via FRED — il miglior predittore dell'oro.
    Ritorna {} se FRED_API_KEY non è impostata.
    """
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        return {}
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": "DFII10", "api_key": key, "file_type": "json",
            "sort_order": "desc", "limit": 5,
        }
        r = requests.get(url, params=params, timeout=12)
        obs = [o for o in r.json().get("observations", []) if o["value"] != "."]
        if len(obs) >= 2:
            cur = float(obs[0]["value"])
            prev = float(obs[1]["value"])
            return {"value": cur, "change": round(cur - prev, 3), "date": obs[0]["date"]}
    except Exception:
        pass
    return {}


def correlations(period: str = "90d") -> dict:
    """Correlazioni giornaliere oro vs driver principali."""
    data = {}
    for name in ["gold", "dxy", "y10", "silver"]:
        try:
            h = yf.Ticker(INSTRUMENTS[name]).history(period=period)["Close"]
            h.index = h.index.date
            data[name] = h
        except Exception:
            pass
    df = pd.DataFrame(data).dropna()
    if len(df) < 20:
        return {}
    rets = df.pct_change().dropna()
    out = {}
    for d in ["dxy", "y10", "silver"]:
        if d in rets:
            out[d] = round(rets["gold"].corr(rets[d]), 2)
    return out


def get_macro_bias() -> dict:
    """
    Calcola il bias macro per XAU/USD combinando tutti i driver.
    Ritorna dict con: bias, score, label per terminale, breakdown, drivers.
    """
    changes = _fetch_changes()
    real = get_real_yield()

    if "gold" not in changes:
        return {"bias": "NEUTRAL", "score": 0, "error": "dati gold non disponibili"}

    score = 0.0
    breakdown = []

    # Driver da yfinance
    for driver in ["dxy", "y10", "y5", "silver", "vix"]:
        if driver in changes:
            chg = changes[driver]["chg_pct"]
            w = DRIVER_WEIGHTS.get(driver, 0)
            contrib = (chg / abs(chg)) * w if chg != 0 else 0  # segno × peso
            # scala per magnitudine (cap a 2x)
            mag = min(abs(chg) / 0.5, 2.0)
            contrib *= mag
            score += contrib
            arrow = "↑" if chg > 0 else "↓"
            impact = "bearish" if contrib < 0 else ("bullish" if contrib > 0 else "neutro")
            breakdown.append(f"{driver.upper()} {chg:+.2f}%{arrow} → {impact} oro")

    # Rendimento reale (FRED) — peso maggiore
    if real:
        rchg = real["change"]
        w = DRIVER_WEIGHTS["real_yield"]
        contrib = (rchg / abs(rchg)) * w if rchg != 0 else 0
        contrib *= min(abs(rchg) / 0.05, 2.0)
        score += contrib
        impact = "bearish" if contrib < 0 else "bullish"
        breakdown.append(f"REAL YIELD {real['value']:.2f}% ({rchg:+.3f}) → {impact} oro [FRED]")

    # Pendenza curva dei rendimenti (10Y − 3M): inversione = stress → bullish oro
    if "y10" in changes and "y3m" in changes:
        slope = changes["y10"]["price"] - changes["y3m"]["price"]
        if slope < 0:
            score += 0.5
            breakdown.append(f"CURVA INVERTITA (10Y−3M = {slope:+.2f}) → bullish oro")
        else:
            breakdown.append(f"Curva 10Y−3M: {slope:+.2f} (normale)")

    # Classificazione
    if score >= 2.0:
        bias = "BULLISH"
    elif score <= -2.0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "score": round(score, 2),
        "gold_price": changes["gold"]["price"],
        "gold_chg": changes["gold"]["chg_pct"],
        "breakdown": breakdown,
        "real_yield": real,
        "has_fred": bool(real),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def format_macro(m: dict) -> str:
    """Formatta il bias macro per output leggibile."""
    if m.get("error"):
        return f"⚠️  {m['error']}"
    icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(m["bias"], "⚪")
    lines = [
        f"{icon} MACRO BIAS XAU/USD: {m['bias']} (score {m['score']:+.1f})",
        f"   Oro: ${m['gold_price']:.0f} ({m['gold_chg']:+.2f}%)",
    ]
    for b in m["breakdown"]:
        lines.append(f"   • {b}")
    if not m["has_fred"]:
        lines.append("   ℹ️  Rendimenti reali non attivi (imposta FRED_API_KEY per il driver #1)")
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  TEST STANDALONE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nForex Macro — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n" + "═" * 60)
    m = get_macro_bias()
    print(format_macro(m))
    print("\n" + "─" * 60)
    print("Correlazioni oro vs driver (90gg):")
    for d, c in correlations().items():
        print(f"   gold vs {d.upper()}: {c:+.2f}")
