#!/usr/bin/env python3
"""
Decision Engine — Confidence scoring multi-layer per strumento
===============================================================
Per ogni strumento dell'universo combina 4 layer indipendenti:

  NEWS  (0.30) — eventi macro mappati (news_engine)
  MACRO (0.30) — forza relativa valute / intermarket (DXY, yields, VIX)
  TECH  (0.25) — trend + momentum su daily (ta.py, dati yfinance)
  COT   (0.15) — flusso e affollamento posizionamento CFTC

composite ∈ [-1, +1]  →  direction = segno, confidence = |composite|

Gate di apertura (tutti obbligatori):
  1. confidence ≥ MIN_CONFIDENCE
  2. macro e tech concordi con la direzione (news mai da sola)
  3. event guard: nessun evento HIGH rilevante entro EVENT_GUARD_DAYS
  4. RSI non estremo contro la direzione (anti-inseguimento)

Data budget: yfinance daily (gratis, cache per run) per TA e strength;
Twelve Data usato solo a valle per il prezzo spot dei candidati (quota).
"""

import math
import warnings
from datetime import datetime, timezone

import yfinance as yf

import ta
from instruments import INSTRUMENTS, CURRENCIES, COT_CODES, currency_exposure

warnings.filterwarnings("ignore")

# ── Parametri (calibrabili dal backtest) ─────────────────────────
WEIGHTS = {"news": 0.30, "macro": 0.30, "tech": 0.25, "cot": 0.15}
MIN_CONFIDENCE   = 0.45
EVENT_GUARD_DAYS = 1      # blocca nuove entry se evento HIGH entro N giorni
RSI_EXTREME_HI   = 74
RSI_EXTREME_LO   = 26

# Cache per run (evita richieste duplicate)
_hist_cache: dict = {}
_cot_cache: dict = {}


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


# ─────────────────────────────────────────────
#  DATI (yfinance daily, cache)
# ─────────────────────────────────────────────

def _hist(yf_symbol: str, period: str = "1y"):
    key = f"{yf_symbol}:{period}"
    if key not in _hist_cache:
        try:
            h = yf.Ticker(yf_symbol).history(period=period, auto_adjust=True)
            h.index = h.index.date
            _hist_cache[key] = h if not h.empty else None
        except Exception:
            _hist_cache[key] = None
    return _hist_cache[key]


def _pct_change(yf_symbol: str, days: int) -> float:
    h = _hist(yf_symbol)
    if h is None or len(h) < days + 1:
        return 0.0
    c = h["Close"]
    return (float(c.iloc[-1]) / float(c.iloc[-1 - days]) - 1) * 100


# ─────────────────────────────────────────────
#  LAYER MACRO
# ─────────────────────────────────────────────

def currency_strength() -> dict:
    """
    Forza relativa di ogni valuta, blend 1g (40%) + 5g (60%), in unità
    normalizzate (~[-1,+1]). Derivata dalle 7 coppie USD.
    """
    vs_usd = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "JPY": "USDJPY=X",
              "CHF": "USDCHF=X", "CAD": "USDCAD=X", "AUD": "AUDUSD=X", "NZD": "NZDUSD=X"}
    inverted = {"JPY", "CHF", "CAD"}  # coppie USDxxx: xxx forte = pair giù

    raw = {}
    for ccy, sym in vs_usd.items():
        blend = 0.4 * _pct_change(sym, 1) + 0.6 * _pct_change(sym, 5)
        raw[ccy] = -blend if ccy in inverted else blend
    raw["USD"] = -sum(raw.values()) / max(len(raw), 1)

    # normalizza: 1.5% blend ≈ forza piena
    return {c: round(_clip(v / 1.5), 3) for c, v in raw.items()}


def macro_scores() -> dict:
    """Score macro per ogni strumento dell'universo."""
    strength = currency_strength()
    dxy_1d = _pct_change("DX-Y.NYB", 1)
    vix_1d = _pct_change("^VIX", 1)
    y10_1d = _pct_change("^TNX", 1)
    risk = _clip(-(vix_1d / 8.0) * 0.6 - (y10_1d / 2.0) * 0.4)  # >0 = risk-on

    out = {}
    for sym, m in INSTRUMENTS.items():
        if m["cls"] == "fx":
            out[sym] = round(_clip(strength.get(m["base"], 0) - strength.get(m["quote"], 0)), 3)
        elif sym in ("XAUUSD", "XAGUSD"):
            try:
                from forex_macro import get_macro_bias
                gm = get_macro_bias()
                out[sym] = round(_clip(gm.get("score", 0) / 8.0), 3)
            except Exception:
                out[sym] = round(_clip(-dxy_1d / 0.8 * 0.5), 3)
        elif m["cls"] == "energy":
            out[sym] = round(_clip(-dxy_1d / 0.8 * 0.4 + risk * 0.2), 3) if sym != "XNGUSD" else 0.0
        elif m["cls"] == "index":
            out[sym] = round(risk * (1.0 if m["quote"] == "USD" else 0.8), 3)
        else:
            out[sym] = 0.0
    out["_strength"] = strength
    return out


# ─────────────────────────────────────────────
#  LAYER TECNICO
# ─────────────────────────────────────────────

def tech_score(symbol: str) -> dict:
    """Trend + momentum su daily. Ritorna score e contesto per il ticket."""
    m = INSTRUMENTS[symbol]
    h = _hist(m["yf"])
    if h is None or len(h) < 60:
        return {"score": 0.0, "note": "dati insufficienti"}

    closes = list(h["Close"].values.astype(float))
    cur = closes[-1]
    rsi_v = ta.rsi(closes)
    _, _, _, macd_bull = ta.macd(closes)
    atr_v = ta.atr(h)
    ma50 = ta.ma(h["Close"], 50)
    ma200 = ta.ma(h["Close"], 200)
    supp, res = ta.support_resistance(h)

    s = 0.0
    if ma50:
        s += 0.35 if cur > ma50 else -0.35
    if ma50 and ma200:
        s += 0.25 if ma50 > ma200 else -0.25
    s += 0.25 if macd_bull else -0.25

    # anti-inseguimento: RSI estremo contro la direzione dimezza lo score
    if s > 0 and rsi_v >= RSI_EXTREME_HI:
        s *= 0.5
    if s < 0 and rsi_v <= RSI_EXTREME_LO:
        s *= 0.5

    return {"score": round(_clip(s), 3), "price": cur, "rsi": rsi_v,
            "atr": atr_v, "ma50": ma50, "ma200": ma200,
            "support": supp, "resistance": res, "macd_bull": macd_bull}


# ─────────────────────────────────────────────
#  LAYER COT
# ─────────────────────────────────────────────

def cot_score(symbol: str) -> float:
    """
    Flusso settimanale del posizionamento spec + penalità affollamento.
    Applicato a: strumento diretto (oro/argento/WTI) o valuta base/quote.
    """
    m = INSTRUMENTS[symbol]
    # scegli il codice: strumento diretto > base > quote(non USD)
    code_key = None
    if symbol in COT_CODES:
        code_key = symbol
    elif m.get("base") in COT_CODES:
        code_key = m["base"]
    elif m.get("quote") in COT_CODES and m["quote"] != "USD":
        code_key = m["quote"]
    if not code_key:
        return 0.0

    if code_key not in _cot_cache:
        try:
            from openbb import obb
            df = obb.cftc.cot(code=COT_CODES[code_key], provider="cftc").to_dataframe().sort_index()
            nl = df["non_commercial_positions_long_all"]
            ns = df["non_commercial_positions_short_all"]
            net = nl - ns
            d_net = float(net.iloc[-1] - net.iloc[-2])
            crowd = float(nl.iloc[-1] / (nl.iloc[-1] + ns.iloc[-1]))  # % long
            flow = _clip(d_net / 20000.0) * 0.7
            contrarian = -0.3 if crowd > 0.85 else (0.3 if crowd < 0.15 else 0.0)
            _cot_cache[code_key] = round(_clip(flow + contrarian), 3)
        except Exception:
            _cot_cache[code_key] = 0.0

    base_score = _cot_cache[code_key]
    # se il codice è la valuta QUOTE, il segno si inverte sullo strumento
    if code_key == m.get("quote"):
        return -base_score
    return base_score


# ─────────────────────────────────────────────
#  EVENT GUARD
# ─────────────────────────────────────────────

def event_guard(symbol: str) -> dict:
    """Blocca strumenti esposti a un evento HIGH imminente (per ora: eventi USA)."""
    try:
        from econ_calendar import next_high_impact
        nxt = next_high_impact()
    except Exception:
        return {"blocked": False}
    if not nxt:
        return {"blocked": False}
    d = nxt.get("days_until", 99)
    us_exposed = ("USD" in currency_exposure(symbol)
                  or any(t in INSTRUMENTS[symbol]["tags"] for t in ("FED", "CPI_US", "JOBS_US")))
    if us_exposed and d <= EVENT_GUARD_DAYS:
        return {"blocked": True,
                "reason": f"{nxt['event']} tra {d}gg — event guard attivo (rientra post-evento)"}
    return {"blocked": False, "next_event": f"{nxt['event']} tra {d}gg"}


# ─────────────────────────────────────────────
#  COMPOSITORE
# ─────────────────────────────────────────────

def evaluate_universe(news_by_instrument: dict) -> list:
    """
    Valuta tutto l'universo. Ritorna lista ordinata per confidence:
    [{symbol, direction, confidence, layers, tech, gate}]
    """
    macro = macro_scores()
    results = []

    for sym in INSTRUMENTS:
        n = news_by_instrument.get(sym, {}).get("score", 0.0)
        news_events = news_by_instrument.get(sym, {}).get("events", [])
        mac = macro.get(sym, 0.0)
        t = tech_score(sym)
        c = cot_score(sym)

        composite = (WEIGHTS["news"] * n + WEIGHTS["macro"] * mac +
                     WEIGHTS["tech"] * t["score"] + WEIGHTS["cot"] * c)
        direction = "LONG" if composite > 0 else "SHORT"
        confidence = abs(composite)
        sign = 1 if composite > 0 else -1

        # ── GATES ──────────────────────────────────────────────
        gate, reasons = True, []
        if confidence < MIN_CONFIDENCE:
            gate = False; reasons.append(f"confidence {confidence:.2f} < {MIN_CONFIDENCE}")
        if mac * sign < 0.05:
            gate = False; reasons.append("macro non concorde")
        if t["score"] * sign < 0.05:
            gate = False; reasons.append("tecnica non concorde")
        rsi_v = t.get("rsi", 50)
        if sign > 0 and rsi_v >= RSI_EXTREME_HI:
            gate = False; reasons.append(f"RSI {rsi_v:.0f} ipercomprato")
        if sign < 0 and rsi_v <= RSI_EXTREME_LO:
            gate = False; reasons.append(f"RSI {rsi_v:.0f} ipervenduto")
        ev = event_guard(sym)
        if ev.get("blocked"):
            gate = False; reasons.append(ev["reason"])

        results.append({
            "symbol": sym, "direction": direction,
            "confidence": round(confidence, 3),
            "layers": {"news": round(n, 3), "macro": mac,
                       "tech": t["score"], "cot": round(c, 3)},
            "news_events": news_events,
            "tech": t, "gate": gate, "gate_reasons": reasons,
            "next_event": ev.get("next_event", ""),
        })

    results.sort(key=lambda r: -r["confidence"])
    return results


if __name__ == "__main__":
    from news_engine import analyze_news
    print("\nDecision Engine — valutazione universo\n" + "═" * 66)
    news = analyze_news()
    res = evaluate_universe(news["by_instrument"])
    print(f"{'':2}{'Strumento':<9}{'Dir':<6}{'Conf':>5}  {'news':>6}{'macro':>7}{'tech':>6}{'cot':>6}  Gate")
    for r in res:
        ok = "✅" if r["gate"] else "—"
        L = r["layers"]
        print(f"{ok:2}{r['symbol']:<9}{r['direction']:<6}{r['confidence']:>5.2f}  "
              f"{L['news']:>6.2f}{L['macro']:>7.2f}{L['tech']:>6.2f}{L['cot']:>6.2f}  "
              f"{'; '.join(r['gate_reasons'][:2]) if not r['gate'] else 'PASS'}")
