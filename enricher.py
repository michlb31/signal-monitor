#!/usr/bin/env python3
"""
Layer 2 — Signal Enricher v2
==============================
Analisi tecnica completa + raccomandazione operativa LONG / SHORT.

Novità v2:
  - RSI, MACD, MA50/MA200, ATR, Bollinger Bands
  - Supporti e resistenze via pivot points (swing high/low)
  - Direzione: LONG / SHORT (con criteri tecnici precisi)
  - Setup type: BREAKOUT / DIP_BUY / TREND_FOLLOW / MEAN_REVERT_SHORT / EARNINGS_PLAY
  - Stop loss calibrato sull'ATR (non fisso -8%)
  - IV assessment e strategia options concreta
  - Risk/Reward ratio
  - Entry range basato sulla struttura tecnica (non solo ±3%)
"""

import yfinance as yf
import math
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
import time

# ═══════════════════════════════════════════════════════════
#  CALCOLI TECNICI — no dipendenze esterne, solo math puro
# ═══════════════════════════════════════════════════════════

def _rsi(closes: list, period: int = 14) -> float:
    """RSI classico di Wilder."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0.0 for d in deltas[-period * 3:]]
    losses = [-d if d < 0 else 0.0 for d in deltas[-period * 3:]]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + ag / al), 1)


def _ema(values: list, period: int) -> list:
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1.0 - k))
    return result


def _macd(closes: list) -> tuple:
    """Ritorna (macd_val, signal_val, histogram, is_bullish_crossover)."""
    if len(closes) < 35:
        return 0.0, 0.0, 0.0, False
    ema12  = _ema(closes, 12)
    ema26  = _ema(closes, 26)
    macd_l = [a - b for a, b in zip(ema12, ema26)]
    sig_l  = _ema(macd_l, 9)
    hist_l = [m - s for m, s in zip(macd_l, sig_l)]
    bullish = (
        macd_l[-1] > sig_l[-1] and
        len(hist_l) >= 2 and hist_l[-1] > hist_l[-2]
    )
    return round(macd_l[-1], 4), round(sig_l[-1], 4), round(hist_l[-1], 4), bullish


def _atr(hist, period: int = 14) -> float:
    """Average True Range — misura la volatilità giornaliera reale."""
    if len(hist) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(hist)):
        h = float(hist['High'].iloc[i])
        l = float(hist['Low'].iloc[i])
        pc = float(hist['Close'].iloc[i - 1])
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    return round(sum(tr_list[-period:]) / period, 4)


def _bollinger(closes: list, period: int = 20) -> tuple:
    """Ritorna (upper, mid, lower, position: UPPER/MIDDLE/LOWER)."""
    if len(closes) < period:
        return None, None, None, "MIDDLE"
    window = closes[-period:]
    mid = sum(window) / period
    std = math.sqrt(sum((c - mid) ** 2 for c in window) / period)
    upper = round(mid + 2 * std, 2)
    lower = round(mid - 2 * std, 2)
    mid   = round(mid, 2)
    cur   = closes[-1]
    if cur >= upper * 0.97:
        pos = "UPPER"
    elif cur <= lower * 1.03:
        pos = "LOWER"
    else:
        pos = "MIDDLE"
    return upper, mid, lower, pos


def _support_resistance(hist, lookback: int = 60) -> tuple:
    """
    Supporti e resistenze via pivot points (swing high/low locali, finestra ±3 candele).
    Ritorna (support, resistance) come float.
    """
    if len(hist) < 10:
        c = float(hist['Close'].iloc[-1])
        return round(c * 0.92, 2), round(c * 1.10, 2)

    h   = hist.tail(lookback)
    cur = float(hist['Close'].iloc[-1])
    highs = h['High'].values.astype(float)
    lows  = h['Low'].values.astype(float)

    win = 3
    p_highs, p_lows = [], []
    for i in range(win, len(h) - win):
        if highs[i] == max(highs[i - win:i + win + 1]):
            p_highs.append(highs[i])
        if lows[i] == min(lows[i - win:i + win + 1]):
            p_lows.append(lows[i])

    s_cands = sorted([l for l in p_lows  if l < cur * 0.995], reverse=True)
    r_cands = sorted([h for h in p_highs if h > cur * 1.005])

    support    = round(s_cands[0], 2) if s_cands else round(float(h['Low'].min()), 2)
    resistance = round(r_cands[0], 2) if r_cands else round(float(h['High'].max()), 2)
    return support, resistance


def _iv_context(t: yf.Ticker, current_price: float) -> tuple:
    """
    Ritorna (atm_iv, iv_regime) dove regime è LOW (<30%) / MEDIUM (30-60%) / HIGH (>60%).
    """
    try:
        exps = t.options
        if not exps:
            return 0.35, "MEDIUM"
        chain = t.option_chain(exps[0])
        calls = chain.calls
        atm   = calls[abs(calls['strike'] - current_price) / current_price < 0.05]
        if atm.empty:
            atm = calls.head(5)
        iv = float(atm['impliedVolatility'].mean())
        if math.isnan(iv) or iv <= 0:
            return 0.35, "MEDIUM"
        regime = "LOW" if iv < 0.30 else ("HIGH" if iv > 0.60 else "MEDIUM")
        return round(iv, 3), regime
    except Exception:
        return 0.35, "MEDIUM"


def _options_strategy(
    direction: str,
    iv_regime: str,
    current_price: float,
    days_to_catalyst: Optional[int],
) -> str:
    """
    Suggerisce la strategia options ottimale in base a:
      direzione (LONG/SHORT) × IV (LOW/MEDIUM/HIGH) × prossimità al catalyst.

    Logica generale:
      IV bassa  + LONG  → BUY CALL (premi economici, tieni tutta la gamma)
      IV media  + LONG  → BULL CALL SPREAD (riduce costo, max gain +10%)
                          ma BUY CALL se catalyst < 21gg (tieni esposizione piena)
      IV alta   + LONG  → SELL PUT OTM -10% (incassa il premio)
      IV bassa  + SHORT → BUY PUT
      IV media  + SHORT → BEAR PUT SPREAD
      IV alta   + SHORT → SELL CALL OTM +10%
    """
    near = days_to_catalyst is not None and days_to_catalyst <= 21

    def strike(mult: float, step: int = 5) -> float:
        return round(current_price * mult / step) * step

    if direction == "LONG":
        if iv_regime == "LOW":
            s = strike(1.05)
            return (
                f"BUY CALL — strike ~${s:.0f} (+5% OTM), scadenza 30-45gg\n"
                f"     IV bassa: premi economici, mantieni tutta la direzionalità"
            )
        elif iv_regime == "MEDIUM":
            if near:
                s = strike(1.05)
                return (
                    f"BUY CALL — strike ~${s:.0f}, scadenza oltre il catalyst\n"
                    f"     Pre-catalyst: evita spread, tieni l'exposure direzionale piena"
                )
            sl, sh = strike(1.00), strike(1.10)
            return (
                f"BULL CALL SPREAD — compra ${sl:.0f} call / vendi ${sh:.0f} call, scadenza 30-45gg\n"
                f"     IV media: spread riduce il costo, profitto massimo a +10%"
            )
        else:  # HIGH
            s = strike(0.90)
            return (
                f"SELL PUT — strike ~${s:.0f} (-10% OTM), scadenza 45-60gg\n"
                f"     IV alta: incassa il premio, hai -10% di buffer\n"
                f"     ⚠️ Evita se catalyst imminente (IV potrebbe salire ancora)"
            )
    elif direction == "SHORT":
        if iv_regime == "LOW":
            s = strike(0.95)
            return (
                f"BUY PUT — strike ~${s:.0f} (-5% OTM), scadenza 30-45gg\n"
                f"     IV bassa: momento ottimale per comprare protezione"
            )
        elif iv_regime == "MEDIUM":
            sh, sl = strike(1.00), strike(0.90)
            return (
                f"BEAR PUT SPREAD — compra ${sh:.0f} put / vendi ${sl:.0f} put, scadenza 30-45gg\n"
                f"     IV media: spread abbassa il costo, target a -10% sufficiente"
            )
        else:  # HIGH
            s = strike(1.10)
            return (
                f"SELL CALL — strike ~${s:.0f} (+10% OTM), scadenza 45-60gg\n"
                f"     IV alta: vendi theta su titolo overbought difficilmente supera +10%"
            )
    return ""


# ═══════════════════════════════════════════════════════════
#  DATA STRUCTURE
# ═══════════════════════════════════════════════════════════

@dataclass
class PriceContext:
    # ── Base (invariati) ─────────────────────────────────────
    ticker: str
    current_price: float
    change_5d_pct: float
    change_30d_pct: float
    volume_ratio: float
    avg_volume_20d: int
    week_high_52: float
    week_low_52: float
    pct_from_52w_high: float
    days_to_earnings: Optional[int]
    beat_rate_pct: Optional[float]
    analyst_target: Optional[float]
    upside_to_target: Optional[float]
    timing: str
    entry_low: Optional[float]
    entry_high: Optional[float]
    stop_loss: Optional[float]
    score_boost: int
    notes: list = field(default_factory=list)

    # ── Analisi tecnica ──────────────────────────────────────
    rsi: float = 50.0
    macd_bullish: bool = False
    macd_histogram: float = 0.0
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    above_ma50: bool = False
    above_ma200: bool = False
    golden_cross: bool = False       # MA50 ha appena superato MA200 (ultimi 5gg)
    death_cross: bool = False        # MA50 ha appena incrociato sotto MA200
    atr: float = 0.0
    atr_pct: float = 0.0            # ATR come % del prezzo
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_position: str = "MIDDLE"     # UPPER / MIDDLE / LOWER
    support: Optional[float] = None
    resistance: Optional[float] = None

    # ── Direzione e setup ────────────────────────────────────
    direction: str = "LONG"         # LONG / SHORT
    setup_type: str = ""            # BREAKOUT / DIP_BUY / TREND_FOLLOW /
                                    # MEAN_REVERT_SHORT / EARNINGS_PLAY / BASE_BUILD

    # ── Options ──────────────────────────────────────────────
    iv_atm: Optional[float] = None
    iv_regime: str = "MEDIUM"       # LOW / MEDIUM / HIGH
    options_strategy: str = ""

    # ── Rischio / Rendimento ─────────────────────────────────
    rr_ratio: float = 0.0
    risk_pct: float = 0.0           # % rischio dallo stop
    reward_pct: float = 0.0         # % guadagno potenziale al target
    target_price: Optional[float] = None


# ═══════════════════════════════════════════════════════════
#  CORE ENRICHER
# ═══════════════════════════════════════════════════════════

_cache: dict = {}
_cache_time: dict = {}
CACHE_TTL_MINUTES = 20


def get_price_context(ticker_str: str) -> Optional[PriceContext]:
    """
    Costruisce il PriceContext completo per un ticker.
    Usa 1 anno di storia per supportare MA200, supporti/resistenze e ATR.
    """
    now_dt = datetime.now()

    if ticker_str in _cache:
        age_min = (now_dt - _cache_time[ticker_str]).total_seconds() / 60
        if age_min < CACHE_TTL_MINUTES:
            return _cache[ticker_str]

    try:
        t    = yf.Ticker(ticker_str)
        hist = t.history(period="1y", auto_adjust=True)
        if hist.empty or len(hist) < 30:
            return None

        hist = hist.dropna(subset=['Close', 'High', 'Low', 'Volume'])
        closes = list(hist['Close'].values.astype(float))
        cur    = closes[-1]

        # ── Variazioni prezzo ────────────────────────────────
        p5d  = closes[-6]  if len(closes) >= 6  else closes[0]
        p30d = closes[-31] if len(closes) >= 31 else closes[0]
        chg5  = (cur - p5d)  / p5d  * 100 if p5d  > 0 else 0.0
        chg30 = (cur - p30d) / p30d * 100 if p30d > 0 else 0.0

        # ── Volume ───────────────────────────────────────────
        vol_today = float(hist['Volume'].iloc[-1])
        vol_avg   = float(hist['Volume'].iloc[-21:-1].mean())
        vol_ratio = vol_today / vol_avg if vol_avg > 0 else 1.0

        # ── 52w high/low ─────────────────────────────────────
        try:
            fi       = t.fast_info
            high52w  = float(getattr(fi, 'year_high', max(closes[-252:])))
            low52w   = float(getattr(fi, 'year_low',  min(closes[-252:])))
        except Exception:
            high52w = max(closes) if closes else cur * 1.5
            low52w  = min(closes) if closes else cur * 0.5
        pct_high = (cur - high52w) / high52w * 100

        # ── Target analisti ──────────────────────────────────
        analyst_target = upside = None
        try:
            analyst_target = float(t.info.get('targetMeanPrice', 0)) or None
            if analyst_target and cur > 0:
                upside = (analyst_target - cur) / cur * 100
        except Exception:
            pass

        # ── Earnings ─────────────────────────────────────────
        days_to_earn = None
        try:
            cal = t.calendar
            if cal is not None:
                ed = cal.get('Earnings Date')
                if ed is not None:
                    if hasattr(ed, '__iter__') and not isinstance(ed, str):
                        ed = list(ed)[0]
                    if hasattr(ed, 'date'):
                        ed = ed.date()
                    days_to_earn = (ed - datetime.now().date()).days
        except Exception:
            pass

        # ── Beat rate ────────────────────────────────────────
        beat_rate = None
        try:
            eh = t.earnings_history
            if eh is not None and not eh.empty:
                valid = eh.dropna(subset=['epsActual', 'epsEstimate'])
                if len(valid) >= 2:
                    beat_rate = float((valid['epsActual'] > valid['epsEstimate']).sum()) / len(valid) * 100
        except Exception:
            pass

        # ── ANALISI TECNICA ──────────────────────────────────

        rsi_val = _rsi(closes)
        _, _, macd_hist, macd_bull = _macd(closes)
        atr_val  = _atr(hist)
        atr_pct  = atr_val / cur * 100 if cur > 0 else 0.0
        bb_up, bb_mid, bb_lo, bb_pos = _bollinger(closes)
        support, resistance = _support_resistance(hist)

        # Moving Averages via pandas rolling (più preciso)
        ma50 = ma200 = None
        above_ma50 = above_ma200 = golden_cross = death_cross = False
        ma50_series  = hist['Close'].rolling(50).mean()
        ma200_series = hist['Close'].rolling(200).mean()

        if not ma50_series.iloc[-1:].isna().all():
            ma50 = round(float(ma50_series.iloc[-1]), 2)
            above_ma50 = cur > ma50

        if not ma200_series.iloc[-1:].isna().all():
            ma200 = round(float(ma200_series.iloc[-1]), 2)
            above_ma200 = cur > ma200

        # Golden / death cross: crossover negli ultimi 5 giorni
        if ma50 and ma200 and len(hist) >= 210:
            ma50_5d  = float(ma50_series.iloc[-6])
            ma200_5d = float(ma200_series.iloc[-6])
            if not (math.isnan(ma50_5d) or math.isnan(ma200_5d)):
                golden_cross = (ma50_5d < ma200_5d) and (ma50 > ma200)
                death_cross  = (ma50_5d > ma200_5d) and (ma50 < ma200)

        # IV dal primo ciclo di scadenza
        iv_atm, iv_regime = _iv_context(t, cur)

        # ── SCORE BOOST ──────────────────────────────────────
        boost = 0
        notes = []

        if vol_ratio >= 3.0:
            boost += 20
            notes.append(f"Volume {vol_ratio:.1f}x media — accumulo significativo")
        elif vol_ratio >= 2.0:
            boost += 12
            notes.append(f"Volume {vol_ratio:.1f}x media — interesse crescente")
        elif vol_ratio >= 1.5:
            boost += 6
            notes.append(f"Volume {vol_ratio:.1f}x media")

        if days_to_earn is not None and 0 <= days_to_earn <= 7:
            boost += 40
            notes.append(f"⚠️ Earnings tra {days_to_earn}gg — finestra critica")
        elif days_to_earn is not None and days_to_earn <= 14:
            boost += 25
            notes.append(f"Earnings tra {days_to_earn}gg — pre-earnings window")
        elif days_to_earn is not None and days_to_earn <= 30:
            boost += 15
            notes.append(f"Earnings tra {days_to_earn}gg — accumulo precoce possibile")

        if beat_rate and beat_rate >= 80:
            boost += 10
            notes.append(f"Beat rate {beat_rate:.0f}% — storicamente batte le stime")

        if golden_cross:
            boost += 15
            notes.append("🌟 Golden Cross — MA50 ha superato MA200")
        if rsi_val < 35 and above_ma50:
            boost += 8
            notes.append(f"RSI {rsi_val:.0f} oversold su trend rialzista — dip da comprare")
        if macd_bull and above_ma50:
            boost += 5
            notes.append("MACD bullish crossover sopra MA50")

        # ── DIREZIONE: LONG vs SHORT ──────────────────────────
        # SHORT: titolo molto esteso (RSI > 72, +35% in 30gg, vicino o sopra resistenza)
        # e nessun golden cross recente che invaliderebbe la short
        is_short = (
            rsi_val > 72 and
            chg30 > 35 and
            (bb_pos == "UPPER" or pct_high > -4) and
            not golden_cross
        )
        direction = "SHORT" if is_short else "LONG"

        # ── SETUP TYPE ───────────────────────────────────────
        if days_to_earn is not None and 0 <= days_to_earn <= 14:
            setup_type = "EARNINGS_PLAY"
        elif direction == "SHORT":
            setup_type = "MEAN_REVERT_SHORT"
        elif chg5 < -7 and above_ma50 and rsi_val < 45:
            setup_type = "DIP_BUY"
        elif resistance and cur >= resistance * 0.97 and vol_ratio > 1.5:
            setup_type = "BREAKOUT"
        elif above_ma50 and above_ma200 and macd_bull:
            setup_type = "TREND_FOLLOW"
        else:
            setup_type = "BASE_BUILD"

        # ── TIMING ───────────────────────────────────────────
        if direction == "SHORT":
            timing = "SHORT-ENTRA" if rsi_val > 78 else "SHORT-ASPETTA"
        elif chg30 > 60:
            timing = "TARDI"
            notes.append("Titolo già mosso >60% in 30gg — rischio elevato")
        elif chg30 > 35 and pct_high > -4 and not golden_cross:
            timing = "TARDI"
            notes.append("Vicino al massimo dopo forte rally — aspetta ritracciamento")
        elif setup_type == "DIP_BUY":
            timing = "PULLBACK"
            notes.append("Ritracciamento su trend rialzista — opportunità di entry sul dip")
        elif setup_type == "BREAKOUT":
            timing = "ENTRA"
            notes.append("Breakout imminente su resistenza con volume — momentum positivo")
        elif chg30 <= 20 and (days_to_earn is None or days_to_earn > 5):
            timing = "ENTRA"
            notes.append("Ancora a base — finestra di accumulo aperta")
        elif chg30 <= 35:
            timing = "ASPETTA"
            notes.append("In movimento ma non esagerato — monitora per conferma")
        else:
            timing = "ASPETTA"

        # ── ENTRY / STOP / TARGET ────────────────────────────
        atr_stop = max(atr_val * 1.5, cur * 0.02)  # almeno 2% di distanza

        if direction == "LONG":
            # Stop: sotto supporto o -1.5 ATR (il più conservativo)
            stop_raw = cur - atr_stop
            if support:
                stop_raw = max(stop_raw, support * 0.983)
            stop_loss = round(stop_raw, 2)

            # Entry basato sul setup
            if setup_type == "DIP_BUY" and support:
                entry_low  = round(support * 0.995, 2)
                entry_high = round(support * 1.03, 2)
            elif setup_type == "BREAKOUT" and resistance:
                entry_low  = round(resistance * 0.985, 2)
                entry_high = round(resistance * 1.015, 2)
            else:
                entry_low  = round(cur * 0.98, 2)
                entry_high = round(cur * 1.02, 2)

            # Target: analyst target > resistenza > +25%
            if analyst_target and analyst_target > cur * 1.05:
                target_price = round(analyst_target, 2)
            elif resistance and resistance > cur * 1.05:
                target_price = round(resistance, 2)
            else:
                target_price = round(cur * 1.25, 2)

        else:  # SHORT
            # Stop: sopra resistenza o +1.5 ATR
            stop_raw = cur + atr_stop
            if resistance:
                stop_raw = min(stop_raw, resistance * 1.02)
            stop_loss = round(stop_raw, 2)

            entry_low  = round(cur * 0.99, 2)
            entry_high = round(cur * 1.01, 2)

            # Target short: supporto > MA50 > -15%
            if support and support < cur * 0.95:
                target_price = round(support, 2)
            elif ma50 and ma50 < cur * 0.95:
                target_price = round(ma50, 2)
            else:
                target_price = round(cur * 0.85, 2)

        # ── RISK / REWARD ─────────────────────────────────────
        entry_mid  = (entry_low + entry_high) / 2
        risk_amt   = abs(entry_mid - stop_loss)
        reward_amt = abs(target_price - entry_mid)
        rr_ratio   = round(reward_amt / risk_amt, 1) if risk_amt > 0 else 0.0
        risk_pct   = round(risk_amt   / entry_mid * 100, 1) if entry_mid > 0 else 0.0
        reward_pct = round(reward_amt / entry_mid * 100, 1) if entry_mid > 0 else 0.0

        # ── OPTIONS STRATEGY ──────────────────────────────────
        options_strat = _options_strategy(direction, iv_regime, cur, days_to_earn)

        ctx = PriceContext(
            ticker=ticker_str,
            current_price=round(cur, 2),
            change_5d_pct=round(chg5, 1),
            change_30d_pct=round(chg30, 1),
            volume_ratio=round(vol_ratio, 1),
            avg_volume_20d=int(vol_avg),
            week_high_52=round(high52w, 2),
            week_low_52=round(low52w, 2),
            pct_from_52w_high=round(pct_high, 1),
            days_to_earnings=days_to_earn,
            beat_rate_pct=round(beat_rate, 0) if beat_rate else None,
            analyst_target=round(analyst_target, 2) if analyst_target else None,
            upside_to_target=round(upside, 1) if upside else None,
            timing=timing,
            entry_low=entry_low,
            entry_high=entry_high,
            stop_loss=stop_loss,
            score_boost=min(boost, 50),
            notes=notes,
            # TA
            rsi=rsi_val,
            macd_bullish=macd_bull,
            macd_histogram=macd_hist,
            ma50=ma50,
            ma200=ma200,
            above_ma50=above_ma50,
            above_ma200=above_ma200,
            golden_cross=golden_cross,
            death_cross=death_cross,
            atr=round(atr_val, 2),
            atr_pct=round(atr_pct, 1),
            bb_upper=bb_up,
            bb_lower=bb_lo,
            bb_position=bb_pos,
            support=support,
            resistance=resistance,
            direction=direction,
            setup_type=setup_type,
            iv_atm=iv_atm,
            iv_regime=iv_regime,
            options_strategy=options_strat,
            rr_ratio=rr_ratio,
            risk_pct=risk_pct,
            reward_pct=reward_pct,
            target_price=target_price,
        )

        _cache[ticker_str] = ctx
        _cache_time[ticker_str] = now_dt
        return ctx

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
#  ENRICH SIGNALS
# ═══════════════════════════════════════════════════════════

def enrich_signals(signals: list) -> list:
    """
    Arricchisce la lista di segnali con contesto tecnico completo.
    Processa solo segnali con ticker e score >= 45.
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

        sig['price_context'] = {
            # Base
            'current_price':     ctx.current_price,
            'change_5d_pct':     ctx.change_5d_pct,
            'change_30d_pct':    ctx.change_30d_pct,
            'volume_ratio':      ctx.volume_ratio,
            'days_to_earnings':  ctx.days_to_earnings,
            'beat_rate_pct':     ctx.beat_rate_pct,
            'analyst_target':    ctx.analyst_target,
            'upside_to_target':  ctx.upside_to_target,
            'timing':            ctx.timing,
            'entry_low':         ctx.entry_low,
            'entry_high':        ctx.entry_high,
            'stop_loss':         ctx.stop_loss,
            'week_high_52':      ctx.week_high_52,
            'pct_from_52w_high': ctx.pct_from_52w_high,
            'notes':             ctx.notes,
            # TA
            'rsi':               ctx.rsi,
            'macd_bullish':      ctx.macd_bullish,
            'macd_histogram':    ctx.macd_histogram,
            'ma50':              ctx.ma50,
            'ma200':             ctx.ma200,
            'above_ma50':        ctx.above_ma50,
            'above_ma200':       ctx.above_ma200,
            'golden_cross':      ctx.golden_cross,
            'death_cross':       ctx.death_cross,
            'atr':               ctx.atr,
            'atr_pct':           ctx.atr_pct,
            'bb_upper':          ctx.bb_upper,
            'bb_lower':          ctx.bb_lower,
            'bb_position':       ctx.bb_position,
            'support':           ctx.support,
            'resistance':        ctx.resistance,
            # Direzione
            'direction':         ctx.direction,
            'setup_type':        ctx.setup_type,
            # Options
            'iv_atm':            ctx.iv_atm,
            'iv_regime':         ctx.iv_regime,
            'options_strategy':  ctx.options_strategy,
            # R:R
            'rr_ratio':          ctx.rr_ratio,
            'risk_pct':          ctx.risk_pct,
            'reward_pct':        ctx.reward_pct,
            'target_price':      ctx.target_price,
        }

        sig['final_score'] = min(sig['final_score'] + ctx.score_boost, 100)
        if ctx.days_to_earnings is not None and ctx.days_to_earnings <= 7:
            sig['alert'] = True
            sig.setdefault('tags', [])
            if 'earnings' not in sig['tags']:
                sig['tags'].append('earnings')
        # Propaga la direzione al segnale padre
        sig['direction'] = ctx.direction
        enriched += 1
        time.sleep(0.3)

    print(f"  ✓ {enriched} segnali arricchiti con dati prezzo/TA")
    return signals


# ═══════════════════════════════════════════════════════════
#  FORMAT OUTPUT
# ═══════════════════════════════════════════════════════════

def format_context(sig: dict) -> str:
    """Formatta il contesto tecnico completo per terminale e Slack."""
    ctx = sig.get('price_context')
    if not ctx:
        return ""

    timing    = ctx['timing']
    direction = ctx.get('direction', 'LONG')

    TIMING_EMOJI = {
        "ENTRA":         "🟢",
        "PULLBACK":      "🔵",
        "ASPETTA":       "🟡",
        "TARDI":         "🔴",
        "SHORT-ENTRA":   "🔴🩳",
        "SHORT-ASPETTA": "🟠🩳",
    }
    t_emoji = TIMING_EMOJI.get(timing, "⚪")

    lines = []

    # ── Riga 1: timing + prezzo + variazioni ────────────────
    lines.append(
        f"  {t_emoji} {timing} ({direction}) | ${ctx['current_price']} | "
        f"5d: {ctx['change_5d_pct']:+.1f}% | "
        f"30d: {ctx['change_30d_pct']:+.1f}% | "
        f"Vol: {ctx['volume_ratio']:.1f}x"
    )

    # ── Riga 2: indicatori tecnici ───────────────────────────
    rsi = ctx.get('rsi', 50.0)
    if rsi > 70:
        rsi_tag = "🔴 ipercomprato"
    elif rsi < 30:
        rsi_tag = "🟢 oversold"
    else:
        rsi_tag = "🟡 neutro"
    macd_tag = "↑ bullish" if ctx.get('macd_bullish') else "↓ bearish"

    ma_parts = []
    if ctx.get('ma50'):
        sym = "↑" if ctx.get('above_ma50') else "↓"
        ma_parts.append(f"MA50 ${ctx['ma50']:.0f}{sym}")
    if ctx.get('ma200'):
        sym = "↑" if ctx.get('above_ma200') else "↓"
        ma_parts.append(f"MA200 ${ctx['ma200']:.0f}{sym}")
    cross = ""
    if ctx.get('golden_cross'):
        cross = " 🌟 GOLDEN CROSS"
    elif ctx.get('death_cross'):
        cross = " 💀 DEATH CROSS"

    lines.append(
        f"  📊 RSI {rsi:.0f} ({rsi_tag}) | MACD {macd_tag} | "
        f"{' | '.join(ma_parts)}{cross}"
    )

    # ── Riga 3: struttura e livelli ──────────────────────────
    struct = []
    setup = ctx.get('setup_type', '')
    if setup:
        struct.append(f"Setup: {setup}")
    if ctx.get('support'):
        struct.append(f"Support ${ctx['support']:.2f}")
    if ctx.get('resistance'):
        struct.append(f"Resist ${ctx['resistance']:.2f}")
    atr_pct = ctx.get('atr_pct', 0)
    bb_pos  = ctx.get('bb_position', 'MIDDLE')
    struct.append(f"ATR {atr_pct:.1f}% | BB {bb_pos}")
    lines.append(f"  🏗  {' | '.join(struct)}")

    # ── Riga 4: earnings + IV ────────────────────────────────
    misc = []
    dte = ctx.get('days_to_earnings')
    if dte is not None and dte >= 0:
        br = f" beat {ctx['beat_rate_pct']:.0f}%" if ctx.get('beat_rate_pct') else ""
        misc.append(f"Earnings {dte}gg{br}")
    if ctx.get('iv_atm'):
        misc.append(f"IV {ctx['iv_regime']} ({ctx['iv_atm']:.0%})")
    if misc:
        lines.append(f"  📅 {' | '.join(misc)}")

    # ── Riga 5: target + entry + stop + R:R ─────────────────
    rr   = ctx.get('rr_ratio', 0.0)
    rpct = ctx.get('risk_pct', 0.0)
    tgt  = ctx.get('target_price') or ctx.get('analyst_target')
    cur_p = ctx.get('current_price', 0)
    # Calcola upside direttamente dal target_price per coerenza con R:R
    if tgt and cur_p > 0:
        upside = (tgt - cur_p) / cur_p * 100
    else:
        upside = ctx.get('reward_pct', 0)

    tgt_str = f"Target ${tgt:.2f} ({upside:+.0f}%) | " if tgt else ""
    lines.append(
        f"  🎯 {tgt_str}"
        f"Entry ${ctx['entry_low']}–${ctx['entry_high']} | "
        f"Stop ${ctx['stop_loss']} (-{rpct:.1f}%) | "
        f"R:R {rr:.1f}x"
    )

    # ── Riga 6: strategia options ────────────────────────────
    opt = ctx.get('options_strategy', '')
    if opt:
        lines.append(f"  💡 Options: {opt}")

    # ── Note extra ───────────────────────────────────────────
    for note in ctx.get('notes', [])[:2]:
        lines.append(f"  💬 {note}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  STANDALONE TEST
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["CEG", "RKLB", "QBTS", "VST", "COIN"]
    print(f"\nEnricher v2 — {len(tickers)} ticker\n{'═'*60}")
    for tk in tickers:
        ctx = get_price_context(tk)
        if not ctx:
            print(f"\n{tk}: dati non disponibili")
            continue
        mock_sig = {
            'ticker_symbols': [tk],
            'final_score': 75,
            'title': f'Test {tk}',
            'price_context': None,
        }
        # Usa format_context direttamente dal ctx
        print(f"\n{'─'*60}")
        print(f"  {tk} — {ctx.direction} | {ctx.setup_type}")
        mock_sig['price_context'] = {
            'current_price': ctx.current_price, 'change_5d_pct': ctx.change_5d_pct,
            'change_30d_pct': ctx.change_30d_pct, 'volume_ratio': ctx.volume_ratio,
            'days_to_earnings': ctx.days_to_earnings, 'beat_rate_pct': ctx.beat_rate_pct,
            'analyst_target': ctx.analyst_target, 'upside_to_target': ctx.upside_to_target,
            'timing': ctx.timing, 'entry_low': ctx.entry_low, 'entry_high': ctx.entry_high,
            'stop_loss': ctx.stop_loss, 'week_high_52': ctx.week_high_52,
            'pct_from_52w_high': ctx.pct_from_52w_high, 'notes': ctx.notes,
            'rsi': ctx.rsi, 'macd_bullish': ctx.macd_bullish, 'macd_histogram': ctx.macd_histogram,
            'ma50': ctx.ma50, 'ma200': ctx.ma200, 'above_ma50': ctx.above_ma50,
            'above_ma200': ctx.above_ma200, 'golden_cross': ctx.golden_cross,
            'death_cross': ctx.death_cross, 'atr': ctx.atr, 'atr_pct': ctx.atr_pct,
            'bb_upper': ctx.bb_upper, 'bb_lower': ctx.bb_lower, 'bb_position': ctx.bb_position,
            'support': ctx.support, 'resistance': ctx.resistance,
            'direction': ctx.direction, 'setup_type': ctx.setup_type,
            'iv_atm': ctx.iv_atm, 'iv_regime': ctx.iv_regime, 'options_strategy': ctx.options_strategy,
            'rr_ratio': ctx.rr_ratio, 'risk_pct': ctx.risk_pct, 'reward_pct': ctx.reward_pct,
            'target_price': ctx.target_price,
        }
        print(format_context(mock_sig))
