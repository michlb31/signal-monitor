#!/usr/bin/env python3
"""
FX Monitor — Orchestratore Forex/CFD IC Markets
================================================
Pipeline completa (sostituisce signal_monitor.py per il forex):

  news_engine (eventi macro → strumenti)
       ↓
  decision_engine (4 layer: news+macro+tech+COT, gates)
       ↓
  risk_manager (sizing €/leva, SL/TP, vincoli portafoglio)
       ↓
  trade ticket → terminale + Slack (solo su NUOVI segnali, anti-spam)

Uso:
  python fx_monitor.py                  # analisi completa + ticket
  python fx_monitor.py --alert --quiet  # per GitHub Actions (stato + Slack)

Il prezzo di entry usa lo spot Twelve Data (= broker) per FX/metalli
se TWELVEDATA_API_KEY è impostata; altrimenti l'ultimo daily yfinance.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from instruments import INSTRUMENTS
from risk_manager import build_ticket, select_portfolio, format_ticket, ACCOUNT

STATE_FILE = Path(__file__).parent / "fx_state.json"


# ─────────────────────────────────────────────
#  PREZZO ENTRY (spot broker-aligned se possibile)
# ─────────────────────────────────────────────

def _entry_price(symbol: str, fallback: float) -> tuple:
    """Ritorna (prezzo, fonte). Spot Twelve Data solo per i candidati (quota API)."""
    m = INSTRUMENTS[symbol]
    if m.get("td"):
        try:
            from twelvedata import available, td_price
            if available():
                p = td_price(m["td"])
                if p:
                    return p, "spot"
        except Exception:
            pass
    return fallback, "daily"


# ─────────────────────────────────────────────
#  RUN PRINCIPALE
# ─────────────────────────────────────────────

def run(verbose: bool = True) -> dict:
    from news_engine import analyze_news
    from decision_engine import evaluate_universe

    if verbose:
        print("📰 News macro (11 temi)...")
    news = analyze_news()
    if verbose:
        print(f"  ✓ {news['n_titles']} titoli, {len(news['events'])} eventi rilevati")
        for ev in news["events"][:5]:
            print(f"    [{ev['strength']:.2f}] {ev['rule']} ({ev['n_matches']})")
        print("\n⚙️  Valutazione universo (23 strumenti, 4 layer)...")

    results = evaluate_universe(news["by_instrument"])
    passed = [r for r in results if r["gate"]]

    # Ticket per i candidati che passano i gate
    tickets = []
    for r in passed:
        t = r["tech"]
        entry, src = _entry_price(r["symbol"], t.get("price", 0))
        reasons = []
        if r["news_events"]:
            reasons.append(f"news: {', '.join(r['news_events'][:2])}")
        L = r["layers"]
        reasons.append(f"macro {L['macro']:+.2f} / tech {L['tech']:+.2f} concordi")
        if abs(L["cot"]) >= 0.15:
            reasons.append(f"COT {L['cot']:+.2f}")
        tk = build_ticket(
            r["symbol"], r["direction"], entry,
            atr_val=t.get("atr", 0),
            support=t.get("support"), resistance=t.get("resistance"),
            confidence=r["confidence"], reasons=reasons,
            next_event=r.get("next_event", ""),
        )
        tk["entry_source"] = src
        tickets.append(tk)

    portfolio = select_portfolio(tickets)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_titles": news["n_titles"],
        "events": news["events"],
        "results": results,
        "tickets": tickets,
        "portfolio": portfolio,
    }


# ─────────────────────────────────────────────
#  OUTPUT TERMINALE
# ─────────────────────────────────────────────

def print_report(out: dict):
    print(f"\n{'═'*70}")
    print(f"  FX MONITOR — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
          f"  |  equity €{ACCOUNT['equity_eur']:.0f} @ 1:{ACCOUNT['leverage']}")
    print(f"{'═'*70}\n")

    print(f"{'':2}{'Simbolo':<9}{'Dir':<7}{'Conf':>5}   {'news':>6}{'macro':>7}{'tech':>6}{'cot':>6}   Esito")
    print(f"{'─'*70}")
    for r in out["results"]:
        ok = "✅" if r["gate"] else "  "
        L = r["layers"]
        note = "PASS → ticket" if r["gate"] else (r["gate_reasons"][0] if r["gate_reasons"] else "")
        print(f"{ok:2}{r['symbol']:<9}{r['direction']:<7}{r['confidence']:>5.2f}   "
              f"{L['news']:>6.2f}{L['macro']:>7.2f}{L['tech']:>6.2f}{L['cot']:>6.2f}   {note[:32]}")

    print(f"\n{'─'*70}")
    if out["portfolio"]:
        print(f"🎫 TRADE TICKET SELEZIONATI ({len(out['portfolio'])}/{ACCOUNT['max_positions']} slot):\n")
        for t in out["portfolio"]:
            print(format_ticket(t))
            print()
    else:
        print("🎫 Nessun ticket oggi — nessun setup supera i gate di qualità.")
    rejected = [t for t in out["tickets"] if not t.get("accepted")]
    if rejected:
        print("\n   Candidati passati ai gate ma rifiutati dal risk manager:")
        for t in rejected[:3]:
            print(format_ticket(t))
    skipped = [t for t in out["tickets"]
               if t.get("accepted") and t.get("skipped_reason")]
    for t in skipped:
        print(f"  ⏭  {t['symbol']} {t['direction']} saltato — {t['skipped_reason']}")
    print(f"\n{'═'*70}")
    print(f"  ⚠️ Regole manuali: max -4% di perdita/giorno → stop. "
          f"Chiudi/riduci prima del weekend.")
    print(f"{'═'*70}")


# ─────────────────────────────────────────────
#  ALERT MODE (anti-spam, stato persistito)
# ─────────────────────────────────────────────

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(s: dict):
    try:
        STATE_FILE.write_text(json.dumps(s, indent=2))
    except Exception:
        pass


def detect_new_tickets(out: dict, state: dict) -> list:
    """Alert solo per ticket NUOVI o con direzione cambiata (no ripetizioni)."""
    alerts = []
    known = state.get("active", {})
    now_active = {}
    for t in out["portfolio"]:
        sym, d = t["symbol"], t["direction"]
        now_active[sym] = {"direction": d, "since": t["timestamp"]}
        prev = known.get(sym)
        if prev is None:
            alerts.append({"type": "NEW", "ticket": t,
                           "msg": f"Nuovo segnale {sym} {d}"})
        elif prev["direction"] != d:
            alerts.append({"type": "FLIP", "ticket": t,
                           "msg": f"{sym}: direzione cambiata {prev['direction']} → {d}"})
    # Segnali decaduti (erano attivi, non passano più i gate)
    for sym, prev in known.items():
        if sym not in now_active:
            alerts.append({"type": "EXPIRED", "ticket": None,
                           "msg": f"{sym} {prev['direction']}: segnale decaduto "
                                  f"(gate non più soddisfatti) — se in posizione, rivaluta"})
    state["active"] = now_active
    state["updated_at"] = out["timestamp"]
    return alerts


def send_slack(out: dict, alerts: list, webhook: str):
    import requests
    if not webhook or not alerts:
        return
    blocks = [{"type": "header",
               "text": {"type": "plain_text",
                        "text": f"FX Monitor — {len(alerts)} aggiornamenti"}}]
    for a in alerts:
        if a["ticket"]:
            t = a["ticket"]
            icon = "🟢" if t["direction"] == "LONG" else "🔴"
            txt = (f"{icon} *{a['msg']}* (conf {int(t['confidence']*100)}%)\n"
                   f"Entry `{t['entry']}` | SL `{t['stop']}` | TP1 `{t['tp1']}`"
                   + (f" | TP2 `{t['tp2']}`" if t.get("tp2") else "") + "\n"
                   f"Size *{t['lots']} lot* | Rischio €{t['risk_eur']} ({t['risk_pct']}%)\n"
                   f"_{'; '.join(t['reasons'][:2])}_"
                   + (f"\n⚠️ {t['next_event']}" if t.get("next_event") else ""))
        else:
            txt = f"🟡 {a['msg']}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": txt}})
        blocks.append({"type": "divider"})
    try:
        r = requests.post(webhook, json={"text": f"FX Monitor — {len(alerts)} alert",
                                         "blocks": blocks}, timeout=10)
        print(f"  {'✅' if r.status_code == 200 else '⚠️'} Slack: {len(alerts)} alert (HTTP {r.status_code})")
    except Exception as e:
        print(f"  ⚠️ Slack: {e}")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="FX Monitor — IC Markets")
    p.add_argument("--alert", action="store_true", help="modalità alert (stato + Slack)")
    p.add_argument("--quiet", action="store_true", help="output ridotto")
    p.add_argument("--slack-webhook", type=str, default="")
    args = p.parse_args()

    out = run(verbose=not args.quiet)
    if not args.quiet:
        print_report(out)

    if args.alert:
        state = _load_state()
        alerts = detect_new_tickets(out, state)
        _save_state(state)
        if alerts:
            print(f"\n🔔 {len(alerts)} cambiamenti:")
            for a in alerts:
                print(f"  • {a['msg']}")
            webhook = args.slack_webhook or os.environ.get("SLACK_WEBHOOK_URL", "")
            send_slack(out, alerts, webhook)
        else:
            print("\n✓ Nessun nuovo segnale — nessun alert (anti-spam).")
