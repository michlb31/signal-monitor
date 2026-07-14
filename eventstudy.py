#!/usr/bin/env python3
"""
Event Study — Comportamenti ricorrenti pre/post pubblicazione dati
===================================================================
Misura come ogni strumento si è mosso storicamente ATTORNO agli eventi
macro (FOMC, CPI, NFP) e alle trimestrali (per le azioni), nelle finestre:

    pre5  = da -5 a -2 giorni    (posizionamento anticipato)
    pre1  = da -1 a 0            (drift immediato pre-annuncio,
                                  es. il celebre "pre-FOMC drift")
    day   = da 0 a +1            (reazione all'evento)
    post3 = da +1 a +3           (continuazione post-evento)

Output: media %, hit-rate direzionale e numerosità per (strumento, evento,
finestra). Un pattern è AZIONABILE solo se n>=10 e hit-rate >=65%.

Integrazione: pre_event_bias() è il 5° layer del decision engine — quando
un evento rilevante è a 1-7 giorni, il bias storico della finestra attiva
entra nel composite. Per le azioni: earnings_drift() abilita l'ingresso
anticipato 3-7gg prima della trimestrale se il drift storico è favorevole
(il blackout <=2gg resta invariato).

Date eventi: FOMC 2024-2026 VERIFICATE (federalreserve.gov, 2026-07-13);
NFP algoritmiche (primo venerdì); CPI 2026 verificate, 2024-25 da
conoscenza consolidata (BLS blocca i bot — confidenza alta ma non fonte).
"""

from datetime import date, datetime, timezone
from functools import lru_cache

# ─────────────────────────────────────────────
#  DATE EVENTI STORICHE
# ─────────────────────────────────────────────

FOMC_DATES = [
    # VERIFICATE su federalreserve.gov (2026-07-13) — giorno dell'annuncio
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1),  date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),  date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
]

CPI_DATES = [
    # 2024: date di rilascio note (8:30 ET)
    date(2024, 1, 11), date(2024, 2, 13), date(2024, 3, 12), date(2024, 4, 10),
    date(2024, 5, 15), date(2024, 6, 12), date(2024, 7, 11), date(2024, 8, 14),
    date(2024, 9, 11), date(2024, 10, 10), date(2024, 11, 13), date(2024, 12, 11),
    # 2025: da conoscenza consolidata (±1 giorno possibile su alcune)
    date(2025, 1, 15), date(2025, 2, 12), date(2025, 3, 12), date(2025, 4, 10),
    date(2025, 5, 13), date(2025, 6, 11), date(2025, 7, 15), date(2025, 8, 12),
    date(2025, 9, 11), date(2025, 10, 15), date(2025, 11, 13), date(2025, 12, 10),
    # 2026: verificate (BLS via econ_calendar)
    date(2026, 1, 13), date(2026, 2, 11), date(2026, 3, 11), date(2026, 4, 10),
    date(2026, 5, 12), date(2026, 6, 10),
]


def _nfp_hist() -> list:
    from econ_calendar import _nfp_dates
    today = datetime.now(timezone.utc).date()
    out = []
    for y in (2024, 2025, 2026):
        out += [d for d in _nfp_dates(y) if d < today]
    return out


def event_dates(event: str) -> list:
    today = datetime.now(timezone.utc).date()
    if event == "FOMC":
        return [d for d in FOMC_DATES if d < today]
    if event == "CPI":
        return [d for d in CPI_DATES if d < today]
    if event == "NFP":
        return _nfp_hist()
    return []


WINDOWS = {"pre5": (-5, -2), "pre1": (-1, 0), "day": (0, 1), "post3": (1, 3)}

# Soglie di azionabilità
MIN_N = 10
MIN_HIT = 0.65


# ─────────────────────────────────────────────
#  CORE: statistiche per (strumento, evento, finestra)
# ─────────────────────────────────────────────

def _daily_closes(yf_symbol: str):
    """Storico daily condiviso col decision engine (stessa cache di run)."""
    try:
        from decision_engine import _hist
        h = _hist(yf_symbol, period="3y")
    except Exception:
        import yfinance as yf
        h = yf.Ticker(yf_symbol).history(period="3y", auto_adjust=True)
        h.index = [d.date() for d in h.index]
    return h


@lru_cache(maxsize=512)
def study(yf_symbol: str, event: str, window: str) -> dict:
    """Rendimento medio e hit-rate nella finestra attorno all'evento."""
    h = _daily_closes(yf_symbol)
    if h is None or len(h) < 100:
        return {}
    idx = list(h.index)
    closes = h["Close"].values.astype(float)
    a, b = WINDOWS[window]

    rets = []
    for ev in event_dates(event):
        pos = None
        for i, d in enumerate(idx):
            if d >= ev:
                pos = i
                break
        if pos is None:
            continue
        i0, i1 = pos + a, pos + b
        if i0 < 0 or i1 >= len(closes) or i0 >= i1:
            continue
        rets.append((closes[i1] / closes[i0] - 1) * 100)

    if len(rets) < 5:
        return {}
    n = len(rets)
    mean = sum(rets) / n
    pos_rate = sum(1 for r in rets if r > 0) / n
    hit = max(pos_rate, 1 - pos_rate)          # coerenza direzionale
    direction = "UP" if pos_rate >= 0.5 else "DOWN"
    return {"n": n, "mean_pct": round(mean, 3), "hit": round(hit, 2),
            "direction": direction,
            "actionable": n >= MIN_N and hit >= MIN_HIT and abs(mean) >= 0.15}


# ─────────────────────────────────────────────
#  LAYER 5 per il decision engine
# ─────────────────────────────────────────────

def pre_event_bias(symbol: str) -> dict:
    """
    Se un evento USD (FOMC/CPI/NFP) è a 1-7 giorni e lo strumento ha un
    pattern storico azionabile nella finestra corrispondente, ritorna il
    bias. Score in [-1, +1], 0 se nessun pattern.
    """
    from instruments import INSTRUMENTS, currency_exposure
    m = INSTRUMENTS.get(symbol)
    if not m:
        return {"score": 0.0}
    us_exposed = ("USD" in currency_exposure(symbol)
                  or any(t in m["tags"] for t in ("FED", "CPI_US", "JOBS_US")))
    if not us_exposed:
        return {"score": 0.0}

    try:
        from econ_calendar import upcoming_events
        evs = upcoming_events(days_ahead=7, min_impact="HIGH", currencies=["USD"])
    except Exception:
        return {"score": 0.0}

    for e in evs:
        name = e["event"].upper()
        etype = ("FOMC" if "FOMC" in name or "FEDERAL FUNDS" in name else
                 "CPI" if "CPI" in name else
                 "NFP" if "NON-FARM" in name or "NFP" in name else None)
        if not etype:
            continue
        d = e["days_until"]
        window = "pre1" if d <= 1 else ("pre5" if 2 <= d <= 5 else None)
        if not window:
            continue
        s = study(m["yf"], etype, window)
        if not s or not s["actionable"]:
            continue
        sign = 1 if s["direction"] == "UP" else -1
        strength = min(abs(s["mean_pct"]) / 0.5, 1.0) * (s["hit"] - 0.5) * 2
        return {"score": round(sign * strength, 3),
                "note": (f"{etype} tra {d}gg: storicamente {s['direction']} "
                         f"{s['mean_pct']:+.2f}% in {window} "
                         f"(hit {int(s['hit']*100)}%, n={s['n']})"),
                "event": etype, "window": window}
    return {"score": 0.0}


# ─────────────────────────────────────────────
#  DRIFT PRE-EARNINGS (per stock_engine)
# ─────────────────────────────────────────────

def earnings_drift(yf_symbol: str, max_events: int = 10) -> dict:
    """Drift medio nei 5 giorni prima delle ultime trimestrali del titolo."""
    try:
        import yfinance as yf
        t = yf.Ticker(yf_symbol)
        ed = t.earnings_dates
        if ed is None or ed.empty:
            return {}
        today = datetime.now(timezone.utc).date()
        past = sorted({d.date() for d in ed.index if d.date() < today},
                      reverse=True)[:max_events]
        if len(past) < 4:
            return {}
        h = t.history(period="3y", auto_adjust=True)
        h.index = [d.date() for d in h.index]
        idx, closes = list(h.index), h["Close"].values.astype(float)
        rets = []
        for ev in past:
            pos = next((i for i, d in enumerate(idx) if d >= ev), None)
            if pos is None or pos - 5 < 0 or pos - 1 >= len(closes):
                continue
            rets.append((closes[pos - 1] / closes[pos - 5] - 1) * 100)
        if len(rets) < 4:
            return {}
        n = len(rets)
        mean = sum(rets) / n
        pos_rate = sum(1 for r in rets if r > 0) / n
        return {"n": n, "mean_pct": round(mean, 2),
                "pos_rate": round(pos_rate, 2),
                "favorable_long": mean >= 0.5 and pos_rate >= 0.6,
                "favorable_short": mean <= -0.5 and pos_rate <= 0.4}
    except Exception:
        return {}


# ─────────────────────────────────────────────
#  REPORT STANDALONE
# ─────────────────────────────────────────────

def report(symbols: list = None):
    from instruments import INSTRUMENTS
    symbols = symbols or ["XAUUSD", "EURUSD", "USDJPY", "US500", "USTEC", "US30"]
    events = ["FOMC", "CPI", "NFP"]
    print(f"\n{'═'*74}")
    print("  EVENT STUDY — comportamento storico attorno agli eventi (2024→oggi)")
    print("  Finestre: pre5=[-5,-2] pre1=[-1,0] day=[0,+1] post3=[+1,+3] giorni")
    print(f"  OK = azionabile (n>={MIN_N}, hit>={int(MIN_HIT*100)}%, |media|>=0.15%)")
    print(f"{'═'*74}")
    for sym in symbols:
        m = INSTRUMENTS.get(sym)
        if not m:
            continue
        print(f"\n── {sym}")
        for ev in events:
            row = []
            for w in WINDOWS:
                s = study(m["yf"], ev, w)
                if s:
                    flag = "OK" if s["actionable"] else "  "
                    row.append(f"{w}:{flag}{s['mean_pct']:+.2f}%({int(s['hit']*100)}%,n{s['n']})")
                else:
                    row.append(f"{w}: n/d")
            print(f"   {ev:5s} " + "  ".join(row))


if __name__ == "__main__":
    report()
