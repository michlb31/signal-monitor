#!/usr/bin/env python3
"""
Layer 2 — Signal Enricher
==========================
Aggiunge contesto prezzo e dati earnings a ogni segnale rilevato dal monitor.

Per ogni ticker in alert:
  - Prezzo attuale e variazione % su 5d/30d
  - Volume ratio (oggi vs media 20gg) — proxy di interesse istituzionale
  - Giorni mancanti agli earnings
  - Storico beat rate (quante volte ha battuto le stime)
  - Decisione ENTRA / ASPETTA / TARDI / PULLBACK
  - Entry range, stop loss suggerito, target analisti

Dipendenze: pip install yfinance
"""

import yfinance as yf
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
import time

# ─────────────────────────────────────────────
#  DATA STRUCTURE
# ─────────────────────────────────────────────

@dataclass
class PriceContext:
    ticker: str
    current_price: float
    change_5d_pct: float
    change_30d_pct: float
    volume_ratio: float          # volume oggi / media 20gg
    avg_volume_20d: int
    week_high_52: float
    week_low_52: float
    pct_from_52w_high: float     # quanto e' sotto il massimo annuale
    days_to_earnings: Optional[int]
    beat_rate_pct: Optional[float]  # % di volte che ha battuto le stime EPS
    analyst_target: Optional[float]
    upside_to_target: Optional[float]  # % upside al target analisti
    timing: str                  # ENTRA / ASPETTA / TARDI / PULLBACK
    entry_low: Optional[float]
    entry_high: Optional[float]
    stop_loss: Optional[float]
    score_boost: int             # boost aggiunto al final_score del segnale
    notes: list = field(default_factory=list)


# ─────────────────────────────────────────────
#  CORE ENRICHER
# ─────────────────────────────────────────────

_cache: dict = {}  # cache per evitare chiamate duplicate nella stessa run
_cache_time: dict = {}
CACHE_TTL_MINUTES = 15

def get_price_context(ticker_str: str) -> Optional[PriceContext]:
    """
    Recupera contesto prezzo completo per un ticker via yfinance.
    Usa cache locale per evitare chiamate duplicate.
    """
    now = datetime.now()

    # Cache hit
    if ticker_str in _cache:
        age = (now - _cache_time[ticker_str]).total_seconds() / 60
        if age < CACHE_TTL_MINUTES:
            return _cache[ticker_str]

    try:
        t = yf.Ticker(ticker_str)

        # Storia 30gg per prezzo e volume
        hist = t.history(period="35d", auto_adjust=True)
        if hist.empty or len(hist) < 5:
            return None

        current = float(hist['Close'].iloc[-1])
        price_5d  = float(hist['Close'].iloc[-6]) if len(hist) >= 6 else float(hist['Close'].iloc[0])
        price_30d = float(hist['Close'].iloc[0])
        vol_today = float(hist['Volume'].iloc[-1])
        vol_avg   = float(hist['Volume'].iloc[:-1].mean())

        change_5d  = (current - price_5d)  / price_5d  * 100 if price_5d  > 0 else 0
        change_30d = (current - price_30d) / price_30d * 100 if price_30d > 0 else 0
        vol_ratio  = vol_today / vol_avg if vol_avg > 0 else 1.0

        # 52 week high/low
        info = {}
        try:
            info = t.fast_info
            high_52w = float(getattr(info, 'year_high', current * 1.5))
            low_52w  = float(getattr(info, 'year_low',  current * 0.5))
            pct_from_high = (current - high_52w) / high_52w * 100
        except Exception:
            high_52w = current * 1.5
            low_52w  = current * 0.5
            pct_from_high = 0.0

        # Target analisti
        analyst_target = None
        upside = None
        try:
            analyst_target = float(t.info.get('targetMeanPrice', 0)) or None
            if analyst_target and current > 0:
                upside = (analyst_target - current) / current * 100
        except Exception:
            pass

        # Earnings calendar
        days_to_earnings = None
        try:
            cal = t.calendar
            if cal is not None:
                # yfinance restituisce dict con 'Earnings Date' come lista o timestamp
                ed = cal.get('Earnings Date', None)
                if ed is not None:
                    if hasattr(ed, '__iter__') and not isinstance(ed, str):
                        ed = list(ed)[0]
                    if hasattr(ed, 'date'):
                        ed = ed.date()
                    days_to_earnings = (ed - datetime.now().date()).days
        except Exception:
            pass

        # Beat rate storico
        beat_rate = None
        try:
            eh = t.earnings_history
            if eh is not None and not eh.empty and 'epsActual' in eh.columns and 'epsEstimate' in eh.columns:
                valid = eh.dropna(subset=['epsActual', 'epsEstimate'])
                if len(valid) >= 2:
                    beats = (valid['epsActual'] > valid['epsEstimate']).sum()
                    beat_rate = float(beats) / len(valid) * 100
        except Exception:
            pass

        # ── Score boost ───────────────────────────────────────
        boost = 0
        notes = []

        # Volume anomalo = accumulo istituzionale
        if vol_ratio >= 3.0:
            boost += 20
            notes.append(f"Volume {vol_ratio:.1f}x media — accumulo significativo")
        elif vol_ratio >= 2.0:
            boost += 12
            notes.append(f"Volume {vol_ratio:.1f}x media — interesse crescente")
        elif vol_ratio >= 1.5:
            boost += 6
            notes.append(f"Volume {vol_ratio:.1f}x media")

        # Pre-earnings window
        if days_to_earnings is not None and days_to_earnings >= 0:
            if days_to_earnings <= 7:
                boost += 40
                notes.append(f"⚠️ Earnings tra {days_to_earnings}gg — finestra critica")
            elif days_to_earnings <= 14:
                boost += 25
                notes.append(f"Earnings tra {days_to_earnings}gg — pre-earnings window")
            elif days_to_earnings <= 30:
                boost += 15
                notes.append(f"Earnings tra {days_to_earnings}gg — accumulo precoce possibile")

        # Beat rate alto = mercato si aspetta beat
        if beat_rate and beat_rate >= 80:
            boost += 10
            notes.append(f"Beat rate {beat_rate:.0f}% — tende a sorprendere")

        # ── Timing decision ────────────────────────────────────
        # Basato su: quanto e' gia' mosso (change_30d) e dove si trova (pct_from_high)
        if change_30d > 60:
            timing = "TARDI"
            notes.append("Titolo gia' mosso >60% in 30gg — rischio elevato di entrata")
        elif change_30d > 35 and pct_from_high > -5:
            timing = "TARDI"
            notes.append("Vicino al massimo annuale dopo forte rally — aspetta ritracciamento")
        elif change_5d < -8 and change_30d < 30:
            timing = "PULLBACK"
            notes.append("Ritracciamento su trend positivo — possibile entry su dip")
        elif change_30d <= 20 and (days_to_earnings is None or days_to_earnings > 5):
            timing = "ENTRA"
            notes.append("Ancora a base — finestra di accumulo aperta")
        elif change_30d <= 35:
            timing = "ASPETTA"
            notes.append("In movimento ma non esagerato — monitora per conferma")
        else:
            timing = "ASPETTA"

        # ── Entry range ────────────────────────────────────────
        # Entry: prezzo attuale ±3% (zona di accumulo)
        # Stop: -8% sotto entry (per rispettare la struttura)
        # Target: analyst target o +25% se non disponibile
        entry_low  = round(current * 0.97, 2)
        entry_high = round(current * 1.03, 2)
        stop_loss  = round(current * 0.92, 2)

        ctx = PriceContext(
            ticker=ticker_str,
            current_price=round(current, 2),
            change_5d_pct=round(change_5d, 1),
            change_30d_pct=round(change_30d, 1),
            volume_ratio=round(vol_ratio, 1),
            avg_volume_20d=int(vol_avg),
            week_high_52=round(high_52w, 2),
            week_low_52=round(low_52w, 2),
            pct_from_52w_high=round(pct_from_high, 1),
            days_to_earnings=days_to_earnings,
            beat_rate_pct=round(beat_rate, 0) if beat_rate else None,
            analyst_target=round(analyst_target, 2) if analyst_target else None,
            upside_to_target=round(upside, 1) if upside else None,
            timing=timing,
            entry_low=entry_low,
            entry_high=entry_high,
            stop_loss=stop_loss,
            score_boost=min(boost, 35),  # cap boost da enricher
            notes=notes,
        )

        _cache[ticker_str] = ctx
        _cache_time[ticker_str] = now
        return ctx

    except Exception as e:
        return None


def enrich_signals(signals: list) -> list:
    """
    Arricchisce la lista di segnali con contesto prezzo.
    Processa solo i segnali con ticker e score >= 45 per non sprecare chiamate API.
    """
    enriched = 0
    for sig in signals:
        symbols = sig.get('ticker_symbols', [])
        if not symbols or sig.get('final_score', 0) < 45:
            continue
        ticker = symbols[0]
        ctx = get_price_context(ticker)
        if ctx is None:
            continue
        # Aggiungi contesto al dict del segnale
        sig['price_context'] = {
            'current_price':      ctx.current_price,
            'change_5d_pct':      ctx.change_5d_pct,
            'change_30d_pct':     ctx.change_30d_pct,
            'volume_ratio':       ctx.volume_ratio,
            'days_to_earnings':   ctx.days_to_earnings,
            'beat_rate_pct':      ctx.beat_rate_pct,
            'analyst_target':     ctx.analyst_target,
            'upside_to_target':   ctx.upside_to_target,
            'timing':             ctx.timing,
            'entry_low':          ctx.entry_low,
            'entry_high':         ctx.entry_high,
            'stop_loss':          ctx.stop_loss,
            'week_high_52':       ctx.week_high_52,
            'pct_from_52w_high':  ctx.pct_from_52w_high,
            'notes':              ctx.notes,
        }
        # Applica boost al score
        sig['final_score'] = min(sig['final_score'] + ctx.score_boost, 100)
        if ctx.days_to_earnings is not None and ctx.days_to_earnings <= 7:
            sig['alert'] = True
            if 'earnings' not in sig.get('tags', []):
                sig.setdefault('tags', []).append('earnings')
        enriched += 1
        time.sleep(0.3)  # rispetta rate limit yfinance

    print(f"  ✓ {enriched} segnali arricchiti con dati prezzo/earnings")
    return signals


def format_context(sig: dict) -> str:
    """Formatta il contesto prezzo per output terminale e Slack."""
    ctx = sig.get('price_context')
    if not ctx:
        return ""

    timing = ctx['timing']
    emoji = {"ENTRA": "🟢", "ASPETTA": "🟡", "TARDI": "🔴", "PULLBACK": "🔵"}.get(timing, "⚪")

    lines = [
        f"  {emoji} {timing} | ${ctx['current_price']} | "
        f"5d: {ctx['change_5d_pct']:+.1f}% | "
        f"30d: {ctx['change_30d_pct']:+.1f}% | "
        f"Vol: {ctx['volume_ratio']:.1f}x",
    ]
    if ctx.get('days_to_earnings') is not None and ctx['days_to_earnings'] >= 0:
        br = f" (beat rate {ctx['beat_rate_pct']:.0f}%)" if ctx.get('beat_rate_pct') else ""
        lines.append(f"  📅 Earnings: {ctx['days_to_earnings']} giorni{br}")
    if ctx.get('analyst_target'):
        lines.append(f"  🎯 Target analisti: ${ctx['analyst_target']} ({ctx.get('upside_to_target', 0):+.0f}% upside)")
    if timing == "ENTRA":
        lines.append(f"  📌 Entry: ${ctx['entry_low']}–${ctx['entry_high']} | Stop: ${ctx['stop_loss']}")
    for note in ctx.get('notes', [])[:2]:
        lines.append(f"  💬 {note}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["QBTS", "DELL", "CEG", "COIN", "RKLB"]
    print(f"\nEnricher test — {len(tickers)} ticker\n{'─'*50}")
    for t in tickers:
        ctx = get_price_context(t)
        if ctx:
            print(f"\n{t}")
            print(f"  Prezzo: ${ctx.current_price} | 5d: {ctx.change_5d_pct:+.1f}% | 30d: {ctx.change_30d_pct:+.1f}%")
            print(f"  Volume: {ctx.volume_ratio:.1f}x media | 52w high: ${ctx.week_high_52} ({ctx.pct_from_52w_high:.0f}% dal max)")
            if ctx.days_to_earnings is not None:
                print(f"  Earnings: {ctx.days_to_earnings}gg | Beat rate: {ctx.beat_rate_pct or 'n/a'}%")
            if ctx.analyst_target:
                print(f"  Target analisti: ${ctx.analyst_target} (+{ctx.upside_to_target:.0f}%)")
            print(f"  Timing: {ctx.timing} | Boost: +{ctx.score_boost}")
            for n in ctx.notes:
                print(f"  → {n}")
        else:
            print(f"\n{t}: dati non disponibili")
