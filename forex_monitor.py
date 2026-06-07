#!/usr/bin/env python3
"""
Forex Monitor — Segnale unificato XAU/USD (e major FX)
=======================================================
Fonde tutti i layer in un'unica valutazione operativa per l'oro:

  1. MACRO BIAS    (forex_macro)   — DXY, yields, real yields, silver, VIX
  2. EVENT RISK    (econ_calendar) — NFP/FOMC/CPI imminenti
  3. POSITIONING   (OpenBB CFTC)   — COT: come sono posizionati i fondi
  4. NEWS SENTIMENT(sentiment)     — buzz su oro/dollaro/Fed/inflazione
  5. TECNICA       (enricher TA)   — RSI/MACD/MA/ATR/supporti su GC=F

Output: bias direzionale composito (LONG/SHORT/FLAT) + confidence +
gestione event-aware (es. "CPI tra 3gg → stringere stop").

Tutto gira senza API key (FRED opzionale per i rendimenti reali).
"""

import warnings
from datetime import datetime, timezone, timedelta

import yfinance as yf

warnings.filterwarnings("ignore")

GOLD = "GC=F"


# ─────────────────────────────────────────────
#  LAYER TECNICO (riusa gli helper di enricher)
# ─────────────────────────────────────────────

def _technical_bias() -> dict:
    from enricher import _rsi, _macd, _atr, _bollinger, _support_resistance
    import pandas as pd

    t = yf.Ticker(GOLD)
    hist = t.history(period="1y", auto_adjust=True)
    if hist.empty:
        return {}
    closes = list(hist["Close"].values.astype(float))
    cur = closes[-1]
    rsi = _rsi(closes)
    _, _, mh, mb = _macd(closes)
    atr = _atr(hist)
    bb_up, bb_mid, bb_lo, bb_pos = _bollinger(closes)
    supp, res = _support_resistance(hist.tail(60))
    ma50 = float(hist["Close"].rolling(50).mean().iloc[-1])
    ma200 = float(hist["Close"].rolling(200).mean().iloc[-1])

    # Bias tecnico: sotto MA200 + MACD bearish = bearish
    score = 0
    if cur < ma200: score -= 1
    if cur < ma50:  score -= 1
    if not mb:      score -= 1
    if rsi < 40:    score -= 0  # oversold: non aggiunge bearish (rischio rimbalzo)
    if cur > ma200: score += 1
    if cur > ma50:  score += 1
    if mb:          score += 1

    bias = "BEARISH" if score <= -2 else ("BULLISH" if score >= 2 else "NEUTRAL")
    return {
        "bias": bias, "score": score, "price": round(cur, 2),
        "rsi": rsi, "macd_bull": mb, "atr": round(atr, 2),
        "ma50": round(ma50, 2), "ma200": round(ma200, 2),
        "support": supp, "resistance": res, "bb_pos": bb_pos,
    }


# ─────────────────────────────────────────────
#  LAYER POSIZIONAMENTO (COT)
# ─────────────────────────────────────────────

def _cot_bias() -> dict:
    try:
        from openbb import obb
        df = obb.cftc.cot(code="088691", provider="cftc").to_dataframe()
        df = df.sort_index().tail(6)
        nc_l = df["non_commercial_positions_long_all"]
        nc_s = df["non_commercial_positions_short_all"]
        net = (nc_l - nc_s)
        net_now = float(net.iloc[-1])
        net_prev = float(net.iloc[-2])
        oi_now = float(df["open_interest_all"].iloc[-1])
        oi_prev = float(df["open_interest_all"].iloc[-2])
        delta_net = net_now - net_prev
        delta_oi_pct = (oi_now - oi_prev) / oi_prev * 100 if oi_prev else 0
        long_pct = nc_l.iloc[-1] / (nc_l.iloc[-1] + nc_s.iloc[-1]) * 100

        # Speculatori che riducono il long + OI in calo = de-risking (bearish breve)
        if delta_net < 0 and delta_oi_pct < -3:
            bias = "BEARISH"
            note = f"Fondi riducono long ({delta_net:+,.0f}), OI {delta_oi_pct:+.0f}% → de-risking"
        elif delta_net > 0:
            bias = "BULLISH"
            note = f"Fondi aumentano long ({delta_net:+,.0f})"
        else:
            bias = "NEUTRAL"
            note = f"Posizionamento stabile ({delta_net:+,.0f})"

        return {"bias": bias, "net_spec": net_now, "long_pct": round(long_pct),
                "delta_net": delta_net, "oi_change_pct": round(delta_oi_pct, 1),
                "note": note, "date": str(df.index[-1])}
    except Exception as e:
        return {"bias": "NEUTRAL", "note": f"COT non disponibile: {str(e)[:50]}"}


# ─────────────────────────────────────────────
#  LAYER NEWS SENTIMENT (forex keywords)
# ─────────────────────────────────────────────

FOREX_QUERIES = ["gold price", "us dollar", "federal reserve rates", "inflation cpi"]


def _news_bias() -> dict:
    import feedparser
    import urllib.parse
    try:
        from sentiment import score_sentiment
    except Exception:
        return {"bias": "NEUTRAL", "note": "sentiment non disponibile"}

    titles = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    for q in FOREX_QUERIES:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en"
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries[:15]:
                titles.append(e.get("title", ""))
        except Exception:
            pass

    if not titles:
        return {"bias": "NEUTRAL", "note": "nessuna news"}

    # NB: sentiment positivo sulle news di "gold" = oro forte (bullish).
    # Ma "dollar/Fed/inflation" positivo è ambiguo → usiamo solo il segnale netto aggregato.
    s = score_sentiment(titles)
    bias = "BULLISH" if s["label"] == "POSITIVE" else (
           "BEARISH" if s["label"] == "NEGATIVE" else "NEUTRAL")
    return {"bias": bias, "net": s["net_score"], "n": s["n"],
            "note": f"{s['n']} titoli, sentiment {s['label']} ({s['net_score']:+.2f})"}


# ─────────────────────────────────────────────
#  COMPOSITORE
# ─────────────────────────────────────────────

def analyze_xau() -> dict:
    from forex_macro import get_macro_bias, format_macro, correlations
    from econ_calendar import event_risk_flag, format_calendar

    macro = get_macro_bias()
    tech  = _technical_bias()
    cot   = _cot_bias()
    news  = _news_bias()
    event = event_risk_flag()

    # Pesi dei layer nel voto composito
    BIAS_VAL = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}
    weights = {"macro": 2.0, "tech": 1.5, "cot": 1.5, "news": 1.0}
    composite = (
        BIAS_VAL.get(macro.get("bias"), 0) * weights["macro"] +
        BIAS_VAL.get(tech.get("bias"), 0) * weights["tech"] +
        BIAS_VAL.get(cot.get("bias"), 0) * weights["cot"] +
        BIAS_VAL.get(news.get("bias"), 0) * weights["news"]
    )
    max_w = sum(weights.values())
    confidence = abs(composite) / max_w

    if composite <= -2.0:
        direction = "SHORT"
    elif composite >= 2.0:
        direction = "LONG"
    else:
        direction = "FLAT"

    return {
        "direction": direction,
        "composite_score": round(composite, 2),
        "confidence": round(confidence, 2),
        "macro": macro, "tech": tech, "cot": cot, "news": news, "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def format_report(a: dict) -> str:
    from forex_macro import format_macro
    from econ_calendar import format_calendar

    d = a["direction"]
    icon = {"LONG": "🟢📈", "SHORT": "🔴📉", "FLAT": "🟡"}.get(d, "⚪")
    conf_bar = "█" * int(a["confidence"] * 10)

    lines = [
        "═" * 64,
        f"  XAU/USD — SEGNALE COMPOSITO",
        f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "═" * 64,
        "",
        f"  {icon}  DIREZIONE: {d}   (score {a['composite_score']:+.1f}, confidence {int(a['confidence']*100)}% {conf_bar})",
        "",
        "  ── Layer ───────────────────────────────────────────────",
    ]
    for name, key in [("MACRO   ", "macro"), ("TECNICA ", "tech"),
                      ("COT     ", "cot"), ("NEWS    ", "news")]:
        layer = a[key]
        b = layer.get("bias", "?")
        bi = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(b, "⚪")
        note = layer.get("note", "")
        lines.append(f"  {bi} {name} {b:8s} {note[:48]}")

    lines += ["", "  ── Event Risk ──────────────────────────────────────────",
              f"  {a['event']['message']}"]

    t = a["tech"]
    if t:
        lines += ["", "  ── Livelli tecnici (GC=F) ──────────────────────────────",
                  f"  Prezzo ${t['price']:.0f} | RSI {t['rsi']:.0f} | MA200 ${t['ma200']:.0f} | "
                  f"ATR ${t['atr']:.0f}",
                  f"  Support ${t['support']:.0f} | Resistance ${t['resistance']:.0f} | BB {t['bb_pos']}"]
    lines.append("═" * 64)
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\nAnalisi XAU/USD in corso (macro + tecnica + COT + news + calendario)...\n")
    a = analyze_xau()
    print(format_report(a))
