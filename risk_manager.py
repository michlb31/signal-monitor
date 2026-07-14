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
    "equity_eur": 400.0,
    "leverage": 30,
    "risk_pct": 0.018,          # rischio target per trade (1.8%)
    # Cap rischio: con capitale micro il lotto minimo 0.01 su una major
    # con stop stretto vale ~2-2.5% — il cap a 3% accetta le major
    # tenendo fuori gli strumenti davvero non sizable (oro: 27%!)
    "max_risk_pct": 0.03,       # oltre → trade rifiutato
    "max_positions": 2,
    "max_per_currency": 1,
    "eurusd": 1.10,             # fallback conversione (aggiornato a runtime se possibile)
    # ── Posizioni STRETTE (richiesta capitale micro, 2026-07-09) ──
    # Stop base 1.2×ATR, mai oltre 1.4×ATR anche se la struttura è più
    # lontana (accettiamo stop "dentro la struttura" pur di restare sizable).
    # Trade-off esplicito: più whipsaw in cambio di size/rischio gestibili.
    "atr_stop_mult": 1.2,
    "atr_stop_min": 1.0,
    "atr_stop_max": 1.4,
    # Ladder di 5 take profit in multipli di R (scalare l'uscita)
    "tp_multiples": [1.0, 1.5, 2.0, 3.0, 4.0],
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


def _round_price(point: float, price: float) -> float:
    """Arrotonda al tick sensato per lo strumento (dal suo point)."""
    if price is None:
        return None
    if point >= 1:
        return round(price, 2)
    decimals = max(0, -int(math.floor(math.log10(point))))
    return round(price, decimals + 1)


def build_ticket(symbol: str, direction: str, entry: float,
                 atr_val: float, support: float, resistance: float,
                 confidence: float, reasons: list, next_event: str = "",
                 meta: dict = None) -> dict:
    """
    Costruisce il trade ticket completo o lo rifiuta con motivazione.
    entry: prezzo corrente (spot Twelve Data se disponibile, altrimenti daily).
    meta: metadati strumento esterni all'universo FX (es. azioni da stock_engine).
    """
    m = meta or INSTRUMENTS[symbol]
    point = m["point"]
    # P/L per punto per 1.0 lot (retrocompatibile col campo _001 dell'universo FX)
    usd_pp_lot = m.get("usd_per_point_lot", m.get("usd_per_point_001", 0) * 100)
    vol_step = m.get("volume_step", 0.01)
    min_vol  = m.get("min_volume", 0.01)
    eurusd = _eurusd()
    equity_usd = ACCOUNT["equity_eur"] * eurusd
    sign = 1 if direction == "LONG" else -1

    # ── STOP STRETTO: clamp della struttura in [1.0, 1.4]×ATR ──
    # La struttura può stringere lo stop, mai allargarlo oltre il cap:
    # con €400 uno stop largo rende il trade non sizable o troppo rischioso.
    if direction == "LONG" and support and support < entry:
        struct_dist = (entry - support) + 0.2 * atr_val
    elif direction == "SHORT" and resistance and resistance > entry:
        struct_dist = (resistance - entry) + 0.2 * atr_val
    else:
        struct_dist = None

    lo = ACCOUNT["atr_stop_min"] * atr_val
    hi = ACCOUNT["atr_stop_max"] * atr_val
    if struct_dist is None:
        stop_dist = ACCOUNT["atr_stop_mult"] * atr_val
        inside_structure = False
    else:
        stop_dist = min(max(struct_dist, lo), hi)
        inside_structure = struct_dist > hi   # stop più stretto della struttura
    stop = entry - sign * stop_dist

    # ── LADDER 5 TAKE PROFIT (multipli di R) ──
    tps = [entry + sign * m * stop_dist for m in ACCOUNT["tp_multiples"]]
    tp1 = tps[0]            # 1R — target di riferimento del journal
    tp2 = tps[2]            # 2R — compat con dashboard/alert esistenti

    # ── SIZING (generalizzato: step/minimi variabili per classe) ──
    # FX/metalli/energia/indici: step 0.01 lot. Azioni USA: 0.1 az; EU: 1 az.
    stop_points = stop_dist / point
    risk_usd_target = equity_usd * ACCOUNT["risk_pct"]
    risk_per_lot = stop_points * usd_pp_lot          # rischio per 1.0 lot
    if risk_per_lot <= 0:
        return {"accepted": False, "symbol": symbol,
                "reject_reason": "stop non calcolabile"}

    lots_raw = risk_usd_target / risk_per_lot
    lots = math.floor(lots_raw / vol_step) * vol_step
    lots = max(min_vol, round(lots, 4))

    actual_risk_usd = lots * risk_per_lot
    actual_risk_pct = actual_risk_usd / equity_usd

    if lots_raw < min_vol and actual_risk_pct > ACCOUNT["max_risk_pct"]:
        return {"accepted": False, "symbol": symbol, "direction": direction,
                "reject_reason": (f"volume minimo {min_vol:g} ⇒ rischio "
                                  f"{actual_risk_pct*100:.1f}% > {ACCOUNT['max_risk_pct']*100:.1f}% "
                                  f"(stop {stop_points:.0f} punti troppo ampio per il capitale)")}

    # ── MARGINE (stima) ──
    # Leva PER STRUMENTO (verificata su icmarkets.eu, regole ESMA):
    # FX major 1:30, AUD/NZD 1:20, oro/indici 1:20, argento/energia 1:10,
    # azioni 1:5 (margine 20%, dal PDF Stocks Specification Sheet).
    ccy_usd = {"USD": 1.0, "EUR": eurusd, "GBP": eurusd * 1.17}.get(m.get("quote"), 1.0)
    if m["cls"] == "fx":
        notional_usd = lots * 100_000 * (entry if m["quote"] == "USD" else
                                         (1.0 if m["base"] == "USD" else 1.2))
    elif m["cls"] == "metal":
        notional_usd = lots * 100 * entry
    elif m["cls"] == "stock":
        notional_usd = lots * entry * ccy_usd        # 1 lot = 1 azione
    else:  # energia (1000 barili/lot), soft cacao (10 t/lot, stima da verificare su MT5), indici (1×)
        _mult = 1000 if m["cls"] == "energy" else (10 if m["cls"] == "soft" else 1)
        notional_usd = lots * _mult * entry
    inst_leverage = m.get("leverage", ACCOUNT["leverage"])
    margin_eur = notional_usd / inst_leverage / eurusd

    # Margine oltre il 50% dell'equity = posizione ingestibile a prescindere dal rischio
    if margin_eur > ACCOUNT["equity_eur"] * 0.5:
        return {"accepted": False, "symbol": symbol, "direction": direction,
                "reject_reason": (f"margine ~€{margin_eur:.0f} (leva 1:{inst_leverage}) "
                                  f"> 50% dell'equity €{ACCOUNT['equity_eur']:.0f}")}

    # ── COSTI: spread/commissioni + swap stimato (modulo "meccanica CFD") ──
    spread_pts = m.get("spread", 0)
    spread_cost_eur = spread_pts * usd_pp_lot * lots / eurusd
    # Gate qualità: se lo spread mangia >15% dello stop, il trade parte troppo in salita
    if spread_pts and stop_points > 0 and spread_pts / stop_points > 0.15:
        return {"accepted": False, "symbol": symbol, "direction": direction,
                "reject_reason": (f"spread {spread_pts} pt = "
                                  f"{spread_pts/stop_points*100:.0f}% dello stop — costi proibitivi")}

    # Commissioni azioni (PDF): USA $0.02/az per lato; EU 0.10% per lato
    commission_eur = None
    if m.get("commission"):
        ctype, cval = m["commission"]
        if ctype == "per_share":
            commission_eur = round(max(cval * lots, 0.02) * 2 / eurusd, 2)
        else:  # pct del nozionale
            commission_eur = round(cval * lots * entry * ccy_usd * 2 / eurusd, 2)

    # Swap giornaliero stimato dal differenziale tassi (solo FX; senza markup broker)
    swap_eur_day = None
    if m["cls"] == "fx":
        try:
            from decision_engine import policy_rates
            r = policy_rates()
            diff = r.get(m["base"], 0) - r.get(m["quote"], 0)   # LONG: incassi base, paghi quote
            swap_eur_day = round(sign * diff / 100 / 365 * notional_usd / eurusd, 2)
        except Exception:
            pass

    # Nota earnings season per gli indici USA
    season_note = ""
    if m["cls"] == "index" and m["quote"] == "USD":
        try:
            from instruments import earnings_season
            season_note = earnings_season()
        except Exception:
            pass

    # Scale-out: con 5 TP servono ≥5 step di volume per chiudere 1/5 alla volta
    lots_final = round(lots, 2)
    if lots_final >= 5 * vol_step:
        exit_plan = "scala 1/5 della size a ogni TP; a TP1 sposta lo stop a breakeven"
    else:
        exit_plan = ("size minima: uscita unica (consigliato TP2-TP3); "
                     "a TP1 sposta lo stop a breakeven")

    return {
        "accepted": True,
        "symbol": symbol, "direction": direction,
        "entry": _round_price(point, entry),
        "stop": _round_price(point, stop),
        "tp1": _round_price(point, tp1),
        "tp2": _round_price(point, tp2) if tp2 else None,
        "tps": [_round_price(point, t) for t in tps],
        "tp_multiples": ACCOUNT["tp_multiples"],
        "exit_plan": exit_plan,
        "inside_structure": inside_structure,
        "stop_points": round(stop_points, 1),
        "lots": lots_final,
        "risk_eur": round(actual_risk_usd / eurusd, 2),
        "risk_pct": round(actual_risk_pct * 100, 1),
        "margin_eur": round(margin_eur, 2),
        "rr_tp1": 2.0,
        "confidence": confidence,
        "reasons": reasons,
        "next_event": next_event,
        # le azioni non entrano nel vincolo valute FX (correlazione diversa)
        "currencies": [] if m["cls"] == "stock" else currency_exposure(symbol),
        "spread_cost_eur": round(spread_cost_eur, 2),
        "commission_eur": commission_eur,
        "swap_eur_day": swap_eur_day,
        "season_note": season_note,
        "yf": m.get("yf"),          # per il journal (outcome tracking)
        "asset_class": m["cls"],
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
    tps = t.get("tps") or [t.get("tp1")]
    mults = t.get("tp_multiples", [])
    ladder = " → ".join(f"{p}" for p in tps)
    mult_lbl = "/".join(f"{m:g}R" for m in mults) if mults else ""
    lines = [
        f"  {icon} {t['symbol']} {t['direction']}  (confidence {int(t['confidence']*100)}%)",
        f"     Entry {t['entry']} | SL {t['stop']} ({t['stop_points']:.0f} pt"
        + (", dentro la struttura" if t.get("inside_structure") else "") + ")",
        f"     TP ladder ({mult_lbl}): {ladder}",
        f"     Size {t['lots']} lot | Rischio €{t['risk_eur']} ({t['risk_pct']}%) | "
        f"Margine ~€{t['margin_eur']}",
        f"     Piano uscita: {t.get('exit_plan','')}",
        f"     Perché: {'; '.join(t['reasons'][:3])}",
    ]
    costs = f"     Costi: spread ~€{t.get('spread_cost_eur', 0)}"
    if t.get("commission_eur") is not None:
        costs += f" | commissioni ~€{t['commission_eur']} (A/R)"
    if t.get("swap_eur_day") is not None:
        costs += (f" | swap ~€{t['swap_eur_day']:+.2f}/notte (stima da tassi, "
                  f"verifica su MT5)")
    lines.append(costs)
    if t.get("company"):
        lines.insert(1, f"     {t['company']}")
    if t.get("next_event"):
        lines.append(f"     ⚠️ {t['next_event']}")
    if t.get("season_note"):
        lines.append(f"     📊 {t['season_note']} — volatilità earnings sugli indici USA")
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
