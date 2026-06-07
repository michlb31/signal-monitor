#!/usr/bin/env python3
"""
Economic Calendar — Eventi macro ad alto impatto su XAU/forex
==============================================================
Gli eventi macro USA muovono l'oro del 2-3% in pochi minuti. Sapere
QUANDO arrivano è il più grande edge operativo del forex:
non si tiene una posizione aperta a leva attraverso NFP/FOMC/CPI
senza saperlo.

Approccio ROBUSTO senza API key: i grandi eventi ricorrenti USA hanno
schedule prevedibile e si calcolano algoritmicamente:
  - NFP (Non-Farm Payrolls): primo venerdì del mese, 8:30 ET
  - CPI: ~metà mese (lista mantenuta), 8:30 ET
  - FOMC: 8 riunioni/anno (date ufficiali Fed, lista mantenuta)
  - PPI, Retail Sales, PCE: schedule mensile tipico

Con FRED_API_KEY (opzionale) si possono arricchire con le release dates
ufficiali via l'API FRED releases.

⚠️ Le date FOMC/CPI vanno verificate contro il calendario ufficiale Fed/BLS
   a inizio anno — sono mantenute nelle costanti sotto.
"""

import calendar as _cal
from datetime import datetime, date, timedelta, timezone

# ─────────────────────────────────────────────
#  DATE MANTENUTE (verificare a inizio anno!)
# ─────────────────────────────────────────────
# FOMC 2026 — date del SECONDO giorno (decisione tassi, 14:00 ET).
# Fonte: federalreserve.gov — VERIFICARE all'inizio dell'anno.
FOMC_2026 = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
]

# CPI release 2026 (8:30 ET) — tipicamente metà mese. VERIFICARE su bls.gov.
CPI_2026 = [
    date(2026, 1, 13), date(2026, 2, 11), date(2026, 3, 11), date(2026, 4, 10),
    date(2026, 5, 12), date(2026, 6, 10), date(2026, 7, 14), date(2026, 8, 12),
    date(2026, 9, 11), date(2026, 10, 13), date(2026, 11, 12), date(2026, 12, 10),
]

# Impatto sull'oro/forex: HIGH = può muovere 1-3% in minuti
EVENT_IMPACT = {
    "FOMC": "HIGH",
    "NFP": "HIGH",
    "CPI": "HIGH",
    "PCE": "MEDIUM",
    "PPI": "MEDIUM",
    "Retail Sales": "MEDIUM",
}


def _nfp_dates(year: int) -> list:
    """NFP = primo venerdì di ogni mese."""
    out = []
    for month in range(1, 13):
        c = _cal.monthcalendar(year, month)
        # primo venerdì: settimana 0 se ha venerdì, altrimenti settimana 1
        first_fri = c[0][_cal.FRIDAY] or c[1][_cal.FRIDAY]
        out.append(date(year, month, first_fri))
    return out


def _pce_dates(year: int) -> list:
    """PCE ~ ultimo venerdì del mese (approssimazione)."""
    out = []
    for month in range(1, 13):
        c = _cal.monthcalendar(year, month)
        fridays = [w[_cal.FRIDAY] for w in c if w[_cal.FRIDAY]]
        out.append(date(year, month, fridays[-1]))
    return out


def _all_events(year: int) -> list:
    """Costruisce la lista completa di eventi ad alto/medio impatto."""
    events = []
    for d in _nfp_dates(year):
        events.append({"date": d, "event": "NFP", "impact": "HIGH",
                       "desc": "Non-Farm Payrolls (occupazione USA)"})
    for d in (FOMC_2026 if year == 2026 else []):
        events.append({"date": d, "event": "FOMC", "impact": "HIGH",
                       "desc": "Decisione tassi Federal Reserve"})
    for d in (CPI_2026 if year == 2026 else []):
        events.append({"date": d, "event": "CPI", "impact": "HIGH",
                       "desc": "Inflazione al consumo USA"})
    for d in _pce_dates(year):
        events.append({"date": d, "event": "PCE", "impact": "MEDIUM",
                       "desc": "PCE (inflazione preferita dalla Fed)"})
    return sorted(events, key=lambda e: e["date"])


def upcoming_events(days_ahead: int = 14, min_impact: str = "MEDIUM") -> list:
    """Eventi nei prossimi N giorni, filtrati per impatto minimo."""
    today = datetime.now(timezone.utc).date()
    impact_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    floor = impact_rank.get(min_impact, 1)

    events = _all_events(today.year)
    if today.month >= 11:  # includi inizio anno successivo
        events += _all_events(today.year + 1)

    out = []
    for e in events:
        delta = (e["date"] - today).days
        if 0 <= delta <= days_ahead and impact_rank.get(e["impact"], 0) >= floor:
            out.append({**e, "days_until": delta})
    return sorted(out, key=lambda e: e["days_until"])


def next_high_impact() -> dict:
    """Il prossimo evento HIGH impact (NFP/FOMC/CPI)."""
    ev = upcoming_events(days_ahead=60, min_impact="HIGH")
    return ev[0] if ev else {}


def event_risk_flag() -> dict:
    """
    Flag di rischio per posizioni aperte: c'è un evento HIGH imminente?
    Ritorna dict con warning level e messaggio operativo.
    """
    nxt = next_high_impact()
    if not nxt:
        return {"level": "none", "message": "Nessun evento HIGH nei prossimi 60gg"}

    d = nxt["days_until"]
    if d == 0:
        lvl, msg = "critical", f"🔴 OGGI {nxt['event']} ({nxt['desc']}) — volatilità estrema attesa"
    elif d <= 1:
        lvl, msg = "critical", f"🔴 DOMANI {nxt['event']} — valuta di chiudere/ridurre prima del rilascio"
    elif d <= 3:
        lvl, msg = "high", f"🟠 {nxt['event']} tra {d}gg — stringere stop o ridurre size prima dell'evento"
    elif d <= 7:
        lvl, msg = "medium", f"🟡 {nxt['event']} tra {d}gg — tienilo a mente per la gestione"
    else:
        lvl, msg = "low", f"🟢 Prossimo HIGH: {nxt['event']} tra {d}gg ({nxt['date']})"
    return {"level": lvl, "message": msg, "event": nxt}


def format_calendar(days_ahead: int = 14) -> str:
    """Output leggibile del calendario."""
    ev = upcoming_events(days_ahead=days_ahead, min_impact="MEDIUM")
    flag = event_risk_flag()
    lines = [f"📅 CALENDARIO EVENTI (prossimi {days_ahead}gg)", flag["message"], ""]
    if not ev:
        lines.append("   Nessun evento rilevante in finestra")
    for e in ev:
        icon = "🔴" if e["impact"] == "HIGH" else "🟡"
        when = "OGGI" if e["days_until"] == 0 else (
               "domani" if e["days_until"] == 1 else f"tra {e['days_until']}gg")
        lines.append(f"   {icon} {e['date']} ({when:>8}) {e['event']:5s} — {e['desc']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  TEST STANDALONE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nEconomic Calendar — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n" + "═" * 60)
    print(format_calendar(days_ahead=21))
    print("\n" + "─" * 60)
    flag = event_risk_flag()
    print(f"Risk flag posizioni: [{flag['level'].upper()}] {flag['message']}")
