#!/usr/bin/env python3
"""
Cocoa Setup — strategia validata per il CFD sul cacao
======================================================
Il motore generico (news+macro+tech+COT) NON funziona sul cacao: il
backtest 2000-2026 mostra che il trend-following tecnico su questo
strumento perde in TUTTE le 60 combinazioni di parametri testate
(profit factor 0.69-1.07), coerentemente con l'autocorrelazione ≈ 0
misurata in research/cocoa_research.md.

L'unica regola che sopravvive alla validazione:

    LONG-ONLY, comprare gli eccessi di ipervenduto DENTRO un trend rialzista
    ├─ trigger  : RSI(14) < 30
    ├─ filtro   : prezzo > MA200 (si compra il calo, non il crollo)
    ├─ stop     : 3 × ATR(14)
    ├─ trailing : 6 × ATR dal massimo
    └─ uscita   : trailing stop o 60 giorni

Perché long-only: asimmetria STRUTTURALE dell'offerta. Al ribasso c'è un
pavimento (costo di produzione: i coltivatori smettono di vendere), al
rialzo no (un albero nuovo produce dopo 3-4 anni → l'offerta non può
rispondere). Infatti il lato short misura PF 0.91 (perdente) contro 2.95
del lato long, sugli stessi dati.

Validazione (dettagli in research/cocoa_research.md §13):
  in-sample 2000-2015 : PF 2.38 (n=31)
  out-of-sample 2016-26: PF 3.15 (n=18)   ← mai vista in fase di design
  robustezza: PF > 1 su TUTTE le soglie RSI 25/30/35/40 e filtri MA200/MA50/nessuno
  costi: regge fino a $50/t round-trip (il nostro è ~$10)
  bootstrap 5.000 storie: mediana +81%, 5% di probabilità di perdita

⚠️ LIMITE DA CONOSCERE: il 73% del profitto storico viene da UN trade
   (dic 2023 → mar 2024, +28.8R, la bolla). Togliendo i 5 trade migliori
   la strategia va in perdita. È una strategia a coda grassa: molte perdite
   piccole (-1R) in attesa dell'evento raro. Chi non regge 10 perdite di
   fila non deve tradarla. La ladder a 5 TP del sistema la ROVINA
   (amputa il trade che paga: R totale +39.7 → +14.8 con cap a 4R).
"""

import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

SYMBOL = "COCOA"
YF = "CC=F"

# Parametri validati (plateau robusto: 2.5/5/40 → PF 2.61, 3/6/60 → 2.95, 3/8/120 → 3.08)
RSI_ENTRY = 30
STOP_ATR = 3.0
TRAIL_ATR = 6.0
MAX_HOLD_DAYS = 60


def _history(period: str = "3y"):
    import yfinance as yf
    h = yf.Ticker(YF).history(period=period, auto_adjust=True)
    if h.empty:
        return None
    h.index = h.index.tz_localize(None)
    return h


def signal(hist=None) -> dict:
    """
    Stato attuale del setup. Ritorna sempre un dict con:
      active      : True se il setup è ARMATO (trend ok, in attesa del trigger)
      triggered   : True se ENTRARE ORA (RSI<30 + trend ok)
      direction   : "LONG" (mai short: il lato corto è perdente sui dati)
      entry/stop  : livelli operativi se triggered
      note        : spiegazione leggibile per il ticket/Slack
    """
    import ta
    h = hist if hist is not None else _history()
    if h is None or len(h) < 220:
        return {"triggered": False, "active": False, "note": "dati insufficienti"}

    closes = list(h["Close"].values.astype(float))
    cur = closes[-1]
    rsi = ta.rsi(closes)
    atr = ta.atr(h)
    ma200 = ta.ma(h["Close"], 200)
    if not (rsi and atr and ma200):
        return {"triggered": False, "active": False, "note": "indicatori non calcolabili"}

    trend_ok = cur > ma200
    triggered = trend_ok and rsi < RSI_ENTRY

    if triggered:
        note = (f"setup validato: RSI {rsi:.0f} <{RSI_ENTRY} con prezzo sopra MA200 "
                f"(${ma200:,.0f}) — storicamente PF 2.95, win 45%, +0.90R/trade")
    elif trend_ok:
        note = (f"setup ARMATO ma non scattato: serve RSI <{RSI_ENTRY} (ora {rsi:.0f}). "
                f"Trend ok (prezzo ${cur:,.0f} > MA200 ${ma200:,.0f})")
    else:
        note = (f"setup SPENTO: prezzo ${cur:,.0f} sotto MA200 ${ma200:,.0f} — "
                f"si compra il calo in trend, non il crollo")

    return {
        "triggered": triggered, "active": trend_ok, "direction": "LONG",
        "price": round(cur, 1), "rsi": round(rsi, 1), "atr": round(atr, 1),
        "ma200": round(ma200, 1),
        "entry": round(cur, 1) if triggered else None,
        "stop": round(cur - STOP_ATR * atr, 1) if triggered else None,
        "trail_atr": TRAIL_ATR, "max_hold_days": MAX_HOLD_DAYS,
        "exit_plan": (f"trailing stop a {TRAIL_ATR} ATR dal massimo, uscita a "
                      f"{MAX_HOLD_DAYS} giorni. NON usare la ladder a 5 TP: "
                      f"amputa il movimento che rende la strategia profittevole"),
        "note": note,
    }


def gate(symbol: str) -> dict:
    """Hook per decision_engine: sul cacao il motore generico non decide.
    Ritorna {"skip": False} per gli altri strumenti."""
    if symbol != SYMBOL:
        return {"skip": False}
    s = signal()
    return {"skip": True, "allow": s.get("triggered", False),
            "direction": "LONG", "reason": s.get("note", ""), "setup": s}


# ─────────────────────────────────────────────
#  BACKTEST (riproducibile: python cocoa_setup.py --backtest)
# ─────────────────────────────────────────────

def backtest(cost_per_ton: float = 10.0, risk_frac: float = 0.02,
             start: str = "2000-01-01", end: str = None) -> dict:
    """Simulazione event-driven, stop prima del target nello stesso giorno."""
    import numpy as np
    import pandas as pd
    h = _history(period="max")
    if h is None:
        return {}
    c, hi, lo = h["Close"], h["High"], h["Low"]
    tr = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    d = pd.DataFrame({
        "close": c, "high": hi, "low": lo,
        "atr": tr.rolling(14).mean(), "ma200": c.rolling(200).mean(),
        "rsi": 100 - 100 / (1 + c.diff().clip(lower=0).rolling(14).mean() /
                            (-c.diff().clip(upper=0).rolling(14).mean())),
    }).dropna()
    # Il periodo si ritaglia DOPO il calcolo degli indicatori: altrimenti il
    # sotto-campione perde il warm-up di MA200 e i risultati non sono confrontabili
    d = d[d.index >= start]
    if end:
        d = d[d.index < end]

    eq, pos, trades = 10000.0, None, []
    rows, idx = d.to_dict("records"), d.index
    for i in range(1, len(rows)):
        r = rows[i]
        if pos:
            if r["low"] <= pos["stop"]:                       # stop colpito
                pnl = (pos["stop"] - pos["entry"]) - cost_per_ton
                eq += pnl * pos["size"]
                trades.append({"in": pos["date"], "out": idx[i], "R": pnl / pos["risk"],
                               "bars": i - pos["i"], "why": "stop"})
                pos = None
            else:
                pos["stop"] = max(pos["stop"], r["close"] - TRAIL_ATR * r["atr"])
                if i - pos["i"] >= MAX_HOLD_DAYS:
                    pnl = (r["close"] - pos["entry"]) - cost_per_ton
                    eq += pnl * pos["size"]
                    trades.append({"in": pos["date"], "out": idx[i], "R": pnl / pos["risk"],
                                   "bars": i - pos["i"], "why": "time"})
                    pos = None
        if pos is None and r["rsi"] < RSI_ENTRY and r["close"] > r["ma200"]:
            risk = STOP_ATR * r["atr"]
            pos = {"entry": r["close"], "risk": risk, "i": i, "date": idx[i],
                   "stop": r["close"] - risk, "size": (eq * risk_frac) / risk}

    t = pd.DataFrame(trades)
    if t.empty:
        return {"n": 0}
    wins, losses = t[t.R > 0], t[t.R <= 0]
    return {"n": len(t), "win_pct": len(wins) / len(t) * 100,
            "pf": wins.R.sum() / abs(losses.R.sum()) if len(losses) else float("inf"),
            "r_mean": t.R.mean(), "r_total": t.R.sum(),
            "best": t.R.max(), "worst": t.R.min(),
            "avg_days": t.bars.mean(), "trades": t}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Cocoa setup — segnale e backtest")
    p.add_argument("--backtest", action="store_true", help="rilancia la validazione storica")
    args = p.parse_args()

    if args.backtest:
        print("\nBACKTEST — long-only RSI<30 sopra MA200 (stop 3 ATR, trail 6 ATR, 60g)")
        print("═" * 74)
        for lbl, kw in [("COMPLETO   2000-2026", {}),
                        ("in-sample  2000-2015", {"end": "2016-01-01"}),
                        ("out-sample 2016-2026", {"start": "2016-01-01"})]:
            r = backtest(**kw)
            if r.get("n"):
                print(f"  {lbl}: n={r['n']:3d}  win {r['win_pct']:4.1f}%  PF {r['pf']:5.2f}  "
                      f"R medio {r['r_mean']:+5.2f}  R tot {r['r_total']:+6.1f}")
        r = backtest()
        t = r["trades"].sort_values("R", ascending=False)
        print(f"\n  Concentrazione: il miglior trade vale il "
              f"{t.R.iloc[0] / r['r_total'] * 100:.0f}% del profitto totale")
        print(f"  Senza i 5 migliori: R tot {t.iloc[5:].R.sum():+.1f} → la strategia vive "
              f"delle code, non della frequenza")
    else:
        s = signal()
        print("\nCocoa Setup — stato attuale\n" + "═" * 74)
        print(f"  prezzo ${s.get('price', 0):,.0f} | RSI {s.get('rsi')} | "
              f"MA200 ${s.get('ma200', 0):,.0f} | ATR ${s.get('atr', 0):,.0f}")
        print(f"  {'🎫 ENTRARE' if s['triggered'] else ('⏳ ARMATO' if s.get('active') else '❌ SPENTO')}"
              f" — {s['note']}")
        if s["triggered"]:
            print(f"\n  entry ${s['entry']:,.0f} | stop ${s['stop']:,.0f} | {s['exit_plan']}")
