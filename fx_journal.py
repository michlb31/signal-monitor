#!/usr/bin/env python3
"""
FX Journal — Registro trade e outcome reali (il feedback loop)
===============================================================
Chiude il cerchio del metodo: ogni ticket emesso viene registrato,
seguito sui prezzi reali (TP1/SL/tempo) e trasformato in statistiche:
win rate, expectancy (R medio), profit factor — per simbolo e direzione.

Storage: fx_journal.json (committato dal workflow come fx_state.json —
volume minimo, diff leggibili, nessun binario).

Regole di chiusura simulate sui daily H/L (conservative):
  - Se nello stesso giorno la barra tocca sia SL che TP1 → conta SL
  - Dopo MAX_HOLD_DAYS barre senza TP/SL → chiusura a mercato (TIME)
  - R multiple = (exit − entry) / (entry − stop), col segno della direzione

NB: il target tracciato è TP1 = 1R (primo gradino della ladder a 5 TP).
Le statistiche misurano quindi la qualità del segnale al primo obiettivo:
WIN = +1R, LOSS = −1R. Le uscite scalate sui TP successivi sono gestione
manuale dell'utente e non alterano la metrica del journal.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

from instruments import INSTRUMENTS

JOURNAL_FILE = Path(__file__).parent / "fx_journal.json"
MAX_HOLD_DAYS = 12   # barre daily massime prima della chiusura TIME


def _load() -> list:
    try:
        return json.loads(JOURNAL_FILE.read_text())
    except Exception:
        return []


def _save(trades: list):
    JOURNAL_FILE.write_text(json.dumps(trades, indent=1, default=str))


# ─────────────────────────────────────────────
#  REGISTRAZIONE TICKET
# ─────────────────────────────────────────────

def record_tickets(tickets: list) -> int:
    """Registra come OPEN i ticket nuovi. Dedupe: un solo OPEN per simbolo."""
    trades = _load()
    open_syms = {t["symbol"] for t in trades if t["status"] == "OPEN"}
    added = 0
    for tk in tickets:
        if not tk.get("accepted") or tk["symbol"] in open_syms:
            continue
        trades.append({
            "id": f"{tk['symbol']}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            "symbol": tk["symbol"], "direction": tk["direction"],
            "yf": tk.get("yf"),                     # per outcome tracking (azioni)
            "entry": tk["entry"], "stop": tk["stop"],
            "tp1": tk["tp1"], "tp2": tk.get("tp2"),
            "lots": tk["lots"], "risk_eur": tk["risk_eur"],
            "confidence": tk["confidence"],
            "reasons": tk.get("reasons", []),
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "status": "OPEN",
        })
        open_syms.add(tk["symbol"])
        added += 1
    if added:
        _save(trades)
    return added


# ─────────────────────────────────────────────
#  OUTCOME TRACKING (daily H/L, conservativo)
# ─────────────────────────────────────────────

def update_outcomes() -> list:
    """Segue i trade OPEN sui prezzi daily. Ritorna i trade chiusi in questo run."""
    trades = _load()
    closed_now = []

    for t in trades:
        if t["status"] != "OPEN":
            continue
        meta = INSTRUMENTS.get(t["symbol"])
        yf_sym = (meta or {}).get("yf") or t.get("yf")   # azioni: yf salvato nel trade
        if not yf_sym:
            continue
        opened = datetime.fromisoformat(t["opened_at"]).date()
        try:
            h = yf.Ticker(yf_sym).history(period="3mo", auto_adjust=True)
            h.index = [d.date() for d in h.index]
            bars = h[h.index > opened]
        except Exception:
            continue
        if bars.empty:
            continue

        entry, stop, tp1 = t["entry"], t["stop"], t["tp1"]
        sign = 1 if t["direction"] == "LONG" else -1
        risk = abs(entry - stop)
        exit_price = exit_reason = None

        for day, bar in bars.iterrows():
            hi, lo = float(bar["High"]), float(bar["Low"])
            hit_sl = lo <= stop if sign > 0 else hi >= stop
            hit_tp = hi >= tp1 if sign > 0 else lo <= tp1
            if hit_sl:                      # conservativo: SL prima del TP
                exit_price, exit_reason = stop, "SL"
                break
            if hit_tp:
                exit_price, exit_reason = tp1, "TP1"
                break
        else:
            if len(bars) >= MAX_HOLD_DAYS:
                exit_price = float(bars["Close"].iloc[-1])
                exit_reason = "TIME"

        if exit_price is None:
            continue

        r_mult = round(sign * (exit_price - entry) / risk, 2) if risk > 0 else 0.0
        t.update({
            "status": "CLOSED", "exit_price": exit_price,
            "exit_reason": exit_reason, "r_multiple": r_mult,
            "pnl_eur_est": round(r_mult * t["risk_eur"], 2),
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "bars_held": len(bars.loc[:day]) if exit_reason != "TIME" else len(bars),
        })
        closed_now.append(t)

    if closed_now:
        _save(trades)
    return closed_now


# ─────────────────────────────────────────────
#  REPORT / EXPECTANCY
# ─────────────────────────────────────────────

def report() -> dict:
    trades = _load()
    closed = [t for t in trades if t["status"] == "CLOSED"]
    open_t = [t for t in trades if t["status"] == "OPEN"]
    out = {"n_total": len(trades), "n_open": len(open_t), "n_closed": len(closed),
           "open_symbols": [f"{t['symbol']} {t['direction']}" for t in open_t]}
    if closed:
        rs = [t["r_multiple"] for t in closed]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        out.update({
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "expectancy_r": round(sum(rs) / len(rs), 2),
            "avg_win_r": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss_r": round(sum(losses) / len(losses), 2) if losses else 0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None,
            "total_r": round(sum(rs), 2),
            "pnl_eur_est": round(sum(t.get("pnl_eur_est", 0) for t in closed), 2),
        })
    return out


def format_report() -> str:
    r = report()
    lines = [f"📓 JOURNAL: {r['n_closed']} chiusi, {r['n_open']} aperti"
             + (f" ({', '.join(r['open_symbols'])})" if r["open_symbols"] else "")]
    if r["n_closed"]:
        lines.append(
            f"   Win rate {r['win_rate']}% | Expectancy {r['expectancy_r']:+.2f}R | "
            f"PF {r['profit_factor']} | Totale {r['total_r']:+.1f}R (~€{r['pnl_eur_est']:+.0f})")
    else:
        lines.append("   Nessun trade chiuso ancora — expectancy in costruzione")
    return "\n".join(lines)


if __name__ == "__main__":
    print("\nFX Journal\n" + "─" * 50)
    closed = update_outcomes()
    for t in closed:
        print(f"  chiuso: {t['symbol']} {t['direction']} → {t['exit_reason']} ({t['r_multiple']:+.2f}R)")
    print(format_report())
