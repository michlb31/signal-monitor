#!/usr/bin/env python3
"""
Economic Calendar v2 — Eventi macro multi-valuta, verificati + live
====================================================================
Due sorgenti complementari:

  1. STATICHE (banche centrali, verificate dalle fonti ufficiali il 2026-07-09):
     - FOMC 2026   ✓ federalreserve.gov
     - BCE  2026   ✓ ecb.europa.eu (meeting residui dell'anno)
     - BoJ  2026   ✓ boj.or.jp
     - BoE  2026   ⚠ NON verificata (sito blocca i bot) — pattern tipico,
                     coperta comunque dal feed live
     + NFP (algoritmico), CPI USA (date BLS), PCE (algoritmico)

  2. LIVE (ForexFactory weekly JSON, gratuito, TUTTE le valute):
     questa settimana + la prossima, con impact High/Medium/Low.
     Copre ciò che le statiche non hanno: PMI/ISM, GDP, Retail Sales,
     JOLTS, RBNZ/RBA/BoC, aste, discorsi — con orario preciso.

API principali:
  upcoming_events(days, min_impact, currencies) — merge statiche+live
  event_guard_for(currencies, days)             — guard multi-valuta
  next_high_impact(currencies)                  — prossimo evento HIGH
  event_risk_flag()                             — compat (USD-centrico)
"""

import calendar as _cal
from datetime import datetime, date, timedelta, timezone

import requests

# ─────────────────────────────────────────────
#  DATE BANCHE CENTRALI 2026 (giorno dell'ANNUNCIO)
# ─────────────────────────────────────────────

CB_MEETINGS_2026 = {
    # ✓ VERIFICATO su federalreserve.gov (2026-07-09)
    "USD": {"name": "FOMC", "desc": "Decisione tassi Federal Reserve", "dates": [
        date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
        date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]},
    # ✓ VERIFICATO su ecb.europa.eu (2026-07-09) — meeting residui 2026
    "EUR": {"name": "ECB", "desc": "Decisione tassi BCE", "dates": [
        date(2026, 7, 23), date(2026, 9, 10), date(2026, 10, 29), date(2026, 12, 17)]},
    # ✓ VERIFICATO su boj.or.jp (2026-07-09)
    "JPY": {"name": "BOJ", "desc": "Decisione tassi Bank of Japan", "dates": [
        date(2026, 1, 23), date(2026, 3, 19), date(2026, 4, 28), date(2026, 6, 16),
        date(2026, 7, 31), date(2026, 9, 18), date(2026, 10, 30), date(2026, 12, 18)]},
    # ⚠ NON VERIFICATO (bankofengland.co.uk blocca i bot) — pattern tipico H2.
    #   Il feed live ForexFactory copre comunque gli annunci BoE reali.
    "GBP": {"name": "BOE", "desc": "Decisione tassi Bank of England", "dates": [
        date(2026, 8, 6), date(2026, 9, 17), date(2026, 11, 5), date(2026, 12, 17)]},
}

# CPI USA (8:30 ET) — calendario BLS. Verificare a inizio anno.
CPI_2026 = [
    date(2026, 1, 13), date(2026, 2, 11), date(2026, 3, 11), date(2026, 4, 10),
    date(2026, 5, 12), date(2026, 6, 10), date(2026, 7, 14), date(2026, 8, 12),
    date(2026, 9, 11), date(2026, 10, 13), date(2026, 11, 12), date(2026, 12, 10),
]

EVENT_IMPACT = {"FOMC": "HIGH", "ECB": "HIGH", "BOE": "HIGH", "BOJ": "HIGH",
                "NFP": "HIGH", "CPI": "HIGH", "PCE": "MEDIUM"}


def _nfp_dates(year: int) -> list:
    """NFP = primo venerdì del mese."""
    out = []
    for month in range(1, 13):
        c = _cal.monthcalendar(year, month)
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


def _static_events(year: int) -> list:
    events = []
    for ccy, cb in CB_MEETINGS_2026.items():
        if year != 2026:
            continue
        for d in cb["dates"]:
            events.append({"date": d, "event": cb["name"], "impact": "HIGH",
                           "ccy": ccy, "desc": cb["desc"], "source": "static"})
    for d in _nfp_dates(year):
        events.append({"date": d, "event": "NFP", "impact": "HIGH", "ccy": "USD",
                       "desc": "Non-Farm Payrolls (occupazione USA)", "source": "static"})
    for d in (CPI_2026 if year == 2026 else []):
        events.append({"date": d, "event": "CPI", "impact": "HIGH", "ccy": "USD",
                       "desc": "Inflazione al consumo USA", "source": "static"})
    for d in _pce_dates(year):
        events.append({"date": d, "event": "PCE", "impact": "MEDIUM", "ccy": "USD",
                       "desc": "PCE (inflazione preferita dalla Fed)", "source": "static"})
    return events


# ─────────────────────────────────────────────
#  FEED LIVE — ForexFactory weekly JSON (gratuito)
# ─────────────────────────────────────────────

_FF_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
_ff_cache: list = None


def fetch_live_calendar() -> list:
    """Eventi live (questa settimana + prossima), tutte le valute, con impact.
    Ritorna [] se il feed non risponde — le statiche restano il fallback."""
    global _ff_cache
    if _ff_cache is not None:
        return _ff_cache
    out = []
    for url in _FF_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
            for e in r.json():
                try:
                    d = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).date()
                except Exception:
                    continue
                impact = str(e.get("impact", "")).upper()
                if impact not in ("HIGH", "MEDIUM"):
                    continue
                out.append({"date": d, "event": e.get("title", "")[:60],
                            "impact": impact, "ccy": e.get("country", ""),
                            "desc": e.get("title", ""), "source": "ff",
                            "forecast": e.get("forecast", ""),
                            "previous": e.get("previous", "")})
        except Exception:
            pass
    _ff_cache = out
    return out


def _is_dup(live_ev: dict, static_ev: dict) -> bool:
    """Un evento live è duplicato di uno statico (stessa banca centrale/dato)."""
    if live_ev["date"] != static_ev["date"] or live_ev["ccy"] != static_ev["ccy"]:
        return False
    key = static_ev["event"].lower()
    title = live_ev["event"].lower()
    aliases = {"fomc": ["fomc", "federal funds"], "ecb": ["main refinancing", "ecb"],
               "boe": ["official bank rate", "mpc"], "boj": ["boj", "policy rate"],
               "nfp": ["non-farm", "nonfarm"], "cpi": ["cpi"], "pce": ["pce", "core pce"]}
    return any(a in title for a in aliases.get(key, [key]))


# ─────────────────────────────────────────────
#  API UNIFICATA
# ─────────────────────────────────────────────

def upcoming_events(days_ahead: int = 14, min_impact: str = "MEDIUM",
                    currencies: list = None) -> list:
    """Eventi futuri (statiche + live, dedup), filtrati per impatto e valute."""
    today = datetime.now(timezone.utc).date()
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    floor = rank.get(min_impact, 1)

    statics = _static_events(today.year)
    if today.month >= 11:
        statics += _static_events(today.year + 1)
    live = fetch_live_calendar()
    # dedup: se il live ha lo stesso evento statico, tieni il live (ha l'orario)
    statics = [s for s in statics if not any(_is_dup(l, s) for l in live)]

    out = []
    for e in statics + live:
        delta = (e["date"] - today).days
        if not (0 <= delta <= days_ahead):
            continue
        if rank.get(e["impact"], 0) < floor:
            continue
        if currencies and e["ccy"] not in currencies:
            continue
        out.append({**e, "days_until": delta})
    return sorted(out, key=lambda x: (x["days_until"], -rank.get(x["impact"], 0)))


def next_high_impact(currencies: list = None) -> dict:
    ev = upcoming_events(days_ahead=60, min_impact="HIGH", currencies=currencies)
    return ev[0] if ev else {}


def event_guard_for(currencies: list, guard_days: int = 1) -> dict:
    """Guard multi-valuta per il decision engine: blocca se un evento HIGH
    che tocca una delle valute dello strumento è entro guard_days."""
    ev = upcoming_events(days_ahead=max(guard_days, 14), min_impact="HIGH",
                         currencies=currencies)
    if not ev:
        return {"blocked": False, "next_event": ""}
    nxt = ev[0]
    label = f"{nxt['event']} ({nxt['ccy']}) tra {nxt['days_until']}gg"
    if nxt["days_until"] <= guard_days:
        return {"blocked": True, "reason": f"{label} — event guard attivo", "event": nxt}
    return {"blocked": False, "next_event": label, "event": nxt}


# ── Compat con forex_monitor (USD-centrico, firma invariata) ──────

def event_risk_flag() -> dict:
    nxt = next_high_impact(currencies=["USD"])
    if not nxt:
        return {"level": "none", "message": "Nessun evento HIGH USD nei prossimi 60gg"}
    d = nxt["days_until"]
    name = nxt["event"]
    if d == 0:
        lvl, msg = "critical", f"🔴 OGGI {name} ({nxt['desc'][:40]}) — volatilità estrema attesa"
    elif d <= 1:
        lvl, msg = "critical", f"🔴 DOMANI {name} — valuta di chiudere/ridurre prima del rilascio"
    elif d <= 3:
        lvl, msg = "high", f"🟠 {name} tra {d}gg — stringere stop o ridurre size prima dell'evento"
    elif d <= 7:
        lvl, msg = "medium", f"🟡 {name} tra {d}gg — tienilo a mente per la gestione"
    else:
        lvl, msg = "low", f"🟢 Prossimo HIGH USD: {name} tra {d}gg ({nxt['date']})"
    return {"level": lvl, "message": msg, "event": nxt}


def format_calendar(days_ahead: int = 14, currencies: list = None) -> str:
    ev = upcoming_events(days_ahead=days_ahead, min_impact="MEDIUM",
                         currencies=currencies)
    live_n = sum(1 for e in ev if e["source"] == "ff")
    lines = [f"📅 CALENDARIO EVENTI (prossimi {days_ahead}gg — "
             f"{len(ev)} eventi, {live_n} dal feed live)"]
    if not ev:
        lines.append("   Nessun evento rilevante in finestra")
    for e in ev[:20]:
        icon = "🔴" if e["impact"] == "HIGH" else "🟡"
        when = "OGGI" if e["days_until"] == 0 else (
               "domani" if e["days_until"] == 1 else f"tra {e['days_until']}gg")
        src = "•" if e["source"] == "ff" else "◦"
        lines.append(f"   {icon} {e['date']} ({when:>8}) [{e['ccy']:3s}] "
                     f"{e['event'][:44]} {src}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"\nEconomic Calendar v2 — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n" + "═" * 64)
    print(format_calendar(days_ahead=14))
    print()
    for ccys, label in [(["USD"], "USD"), (["EUR", "JPY"], "EURJPY"), (["GBP"], "GBP")]:
        g = event_guard_for(ccys, guard_days=1)
        state = "🔒 BLOCCATO: " + g.get("reason", "") if g["blocked"] else "🟢 libero — " + g.get("next_event", "")
        print(f"  Guard {label:7s}: {state}")
