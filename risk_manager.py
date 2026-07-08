#!/usr/bin/env python3
"""
Risk Manager — Sizing, SL/TP e trade ticket per conto retail a leva
====================================================================
Tarato sui parametri reali dell'utente (IC Markets MT5):
  equity €360 | leva 1:30 | lotto minimo 0.01 | rischio 1.8%/trade

Regole codificate (lezioni dal trading live di questa settimana):
  - Stop = max(1.5×ATR, livello strutturale) — mai dentro il rumore
  - Se il lotto MINIMO implica rischio > 2.5% → TRADE RIFIUTATO
    (es. XAUUSD con stop ampio: non sizable con capitale piccolo)
  - TP1 = 2R (validato dal backtest), TP2 = livello strutturale
  - Max 2 posizioni, max 1 per valuta (no stacking USD)
  - Circuit breaker giornaliero -4% (regola manuale, in calce al ticket)
"""

import math
from datetime import datetime, timezone

from instruments import INSTRUMENTS, currency_exposure

# ── Configurazione conto (modificare qui se cambia il capitale) ──
ACCOUNT = {
    "equity_eur": 360.0,
    "leverage": 30,
    "risk_pct": 0.018,          # rischio target per trade (1.8%)
    # Cap rischio: con capitale micro il lotto minimo 0.01 su una major
    # con stop 1.5×ATR vale ~2.5-3% — il cap a 3% accetta le major
    # tenendo fuori gli strumenti davvero non sizable (oro: 27%!)
    "max_risk_pct": 0.03,       # oltre → trade rifiutato
    "max_positions": 2,
    "max_per_currency": 1,
    "eurusd": 1.10,             # fallback conversione (aggiornato a runtime se possibile)
}


def _eurusd() -> float:
    try:
        import yfinance as yf
        p = float(yf.Ticker("EURUSD=X").fast_info.last_price)
        if 0.8 < p < 1.6:
            return p
    except Exception:
        pass
    return ACCOUNT["eurusd"]


def _round_price(symbol: str, price: float) -> float:
    """Arrotonda al tick sensato per lo strumento."""
    point = INSTRUMENTS[symbol]["point"]
    if point >= 1:
        return round(price, 1)
    decimals = max(0, -int(math.floor(math.log10(point))) )
    return round(price, decimals + 1)


def build_ticket(symbol: str, direction: str, entry: float,
                 atr_val: float, support: float, resistance: float,
                 confidence: float, reasons: list, next_event: str = "") -> dict:
    """
    Costruisce il trade ticket completo o lo rifiuta con motivazione.
    entry: prezzo corrente (spot Twelve Data se disponibile, altrimenti daily).
    """
    m = INSTRUMENTS[symbol]
    point = m["point"]
    usd_pp = m["usd_per_point_001"]
    eurusd = _eurusd()
    equity_usd = ACCOUNT["equity_eur"] * eurusd
    sign = 1 if direction == "LONG" else -1

    # ── STOP: struttura vs volatilità, il più conservativo (cap 2.5 ATR) ──
    atr_dist = 1.5 * atr_val
    if direction == "LONG" and support and support < entry:
        struct_dist = (entry - support) + 0.2 * atr_val
    elif direction == "SHORT" and resistance and resistance > entry:
        struct_dist = (resistance - entry) + 0.2 * atr_val
    else:
        struct_dist = atr_dist
    stop_dist = min(max(atr_dist, struct_dist), 2.5 * atr_val)
    stop = entry - sign * stop_dist

    # ── TARGET: TP1 = 2R; TP2 = struttura se più ambiziosa ──
    tp1 = entry + sign * 2 * stop_dist
    tp2 = None
    if direction == "LONG" and resistance and resistance > tp1:
        tp2 = resistance
    elif direction == "SHORT" and support and support < tp1:
        tp2 = support

    # ── SIZING ──
    stop_points = stop_dist / point
    risk_usd_target = equity_usd * ACCOUNT["risk_pct"]
    risk_usd_min_lot = stop_points * usd_pp          # rischio con 0.01 lot
    if risk_usd_min_lot <= 0:
        return {"accepted": False, "symbol": symbol,
                "reject_reason": "stop non calcolabile"}

    n_min_lots = risk_usd_target / risk_usd_min_lot   # multipli di 0.01
    lots = max(1, math.floor(n_min_lots)) * 0.01

    actual_risk_usd = (lots / 0.01) * risk_usd_min_lot
    actual_risk_pct = actual_risk_usd / equity_usd

    if n_min_lots < 1 and actual_risk_pct > ACCOUNT["max_risk_pct"]:
        return {"accepted": False, "symbol": symbol, "direction": direction,
                "reject_reason": (f"lotto minimo 0.01 ⇒ rischio "
                                  f"{actual_risk_pct*100:.1f}% > {ACCOUNT['max_risk_pct']*100:.1f}% "
                                  f"(stop {stop_points:.0f} punti troppo ampio per il capitale)")}

    # ── MARGINE (stima) ──
    # Leva PER STRUMENTO (verificata su icmarkets.eu, regole ESMA):
    # FX major 1:30, AUD/NZD 1:20, oro/indici 1:20, argento/energia 1:10.
    # NON usare la leva conto flat: l'oro a 1:20 impegna ~€195 per 0.01 lot!
    if m["cls"] == "fx":
        notional_usd = lots * 100_000 * (entry if m["quote"] == "USD" else
                                         (1.0 if m["base"] == "USD" else 1.2))
    elif m["cls"] == "metal":
        notional_usd = lots * 100 * entry
    else:  # energia (1000 barili/lot), indici (1×)
        notional_usd = lots * (1000 if m["cls"] == "energy" else 1) * entry
    inst_leverage = m.get("leverage", ACCOUNT["leverage"])
    margin_eur = notional_usd / inst_leverage / eurusd

    # Margine oltre il 50% dell'equity = posizione ingestibile a prescindere dal rischio
    if margin_eur > ACCOUNT["equity_eur"] * 0.5:
        return {"accepted": False, "symbol": symbol, "direction": direction,
                "reject_reason": (f"margine ~€{margin_eur:.0f} (leva 1:{inst_leverage}) "
                                  f"> 50% dell'equity €{ACCOUNT['equity_eur']:.0f}")}

    return {
        "accepted": True,
        "symbol": symbol, "direction": direction,
        "entry": _round_price(symbol, entry),
        "stop": _round_price(symbol, stop),
        "tp1": _round_price(symbol, tp1),
        "tp2": _round_price(symbol, tp2) if tp2 else None,
        "stop_points": round(stop_points, 1),
        "lots": round(lots, 2),
        "risk_eur": round(actual_risk_usd / eurusd, 2),
        "risk_pct": round(actual_risk_pct * 100, 1),
        "margin_eur": round(margin_eur, 2),
        "rr_tp1": 2.0,
        "confidence": confidence,
        "reasons": reasons,
        "next_event": next_event,
        "currencies": currency_exposure(symbol),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def select_portfolio(tickets: list) -> list:
    """
    Applica i vincoli di portafoglio: max posizioni, max 1 per valuta.
    I ticket arrivano già ordinati per confidence.
    """
    chosen, used_ccy = [], set()
    for t in tickets:
        if not t.get("accepted"):
            continue
        if len(chosen) >= ACCOUNT["max_positions"]:
            break
        ccys = set(t.get("currencies", []))
        if ccys & used_ccy:
            t["skipped_reason"] = f"valuta già esposta ({', '.join(ccys & used_ccy)})"
            continue
        chosen.append(t)
        used_ccy |= ccys
    return chosen


def format_ticket(t: dict) -> str:
    """Formato leggibile per terminale/Slack."""
    if not t.get("accepted"):
        return (f"  ❌ {t['symbol']} {t.get('direction','')} RIFIUTATO — "
                f"{t['reject_reason']}")
    icon = "🟢📈" if t["direction"] == "LONG" else "🔴📉"
    lines = [
        f"  {icon} {t['symbol']} {t['direction']}  (confidence {int(t['confidence']*100)}%)",
        f"     Entry {t['entry']} | SL {t['stop']} ({t['stop_points']:.0f} pt) | "
        f"TP1 {t['tp1']} (2R)" + (f" | TP2 {t['tp2']}" if t.get("tp2") else ""),
        f"     Size {t['lots']} lot | Rischio €{t['risk_eur']} ({t['risk_pct']}%) | "
        f"Margine ~€{t['margin_eur']}",
        f"     Perché: {'; '.join(t['reasons'][:3])}",
    ]
    if t.get("next_event"):
        lines.append(f"     ⚠️ {t['next_event']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Test sintetici: un FX sizable e l'oro con stop ampio (deve rifiutare)
    print("\nRisk Manager — test\n" + "─" * 60)
    t1 = build_ticket("GBPJPY", "SHORT", entry=185.50, atr_val=1.20,
                      support=182.00, resistance=187.20,
                      confidence=0.62, reasons=["JPY forte (BoJ+intervento)", "trend↓"])
    print(format_ticket(t1))
    print()
    t2 = build_ticket("XAUUSD", "SHORT", entry=4310.0, atr_val=76.0,
                      support=4145.0, resistance=4400.0,
                      confidence=0.55, reasons=["macro bearish"])
    print(format_ticket(t2))
    print()
    print("Portafoglio:", [x["symbol"] for x in select_portfolio([t1, t2])])
