#!/usr/bin/env python3
"""
TA — Analisi tecnica condivisa (asset-agnostica)
=================================================
Helper estratti da enricher.py: funzionano su qualsiasi serie OHLC
(azioni, forex, metalli, indici) purché il DataFrame abbia colonne
Open/High/Low/Close — formato garantito sia da yfinance sia da
twelvedata.td_time_series().

Nessuna dipendenza oltre pandas/math. Nessun lookahead.
"""

import math

# ─────────────────────────────────────────────
#  INDICATORI
# ─────────────────────────────────────────────

def rsi(closes: list, period: int = 14) -> float:
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


def ema(values: list, period: int) -> list:
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1.0 - k))
    return result


def macd(closes: list) -> tuple:
    """Ritorna (macd_val, signal_val, histogram, is_bullish)."""
    if len(closes) < 35:
        return 0.0, 0.0, 0.0, False
    ema12  = ema(closes, 12)
    ema26  = ema(closes, 26)
    macd_l = [a - b for a, b in zip(ema12, ema26)]
    sig_l  = ema(macd_l, 9)
    hist_l = [m - s for m, s in zip(macd_l, sig_l)]
    bullish = (
        macd_l[-1] > sig_l[-1] and
        len(hist_l) >= 2 and hist_l[-1] > hist_l[-2]
    )
    return round(macd_l[-1], 5), round(sig_l[-1], 5), round(hist_l[-1], 5), bullish


def atr(hist, period: int = 14) -> float:
    """Average True Range su DataFrame OHLC."""
    if len(hist) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(hist)):
        h = float(hist['High'].iloc[i])
        l = float(hist['Low'].iloc[i])
        pc = float(hist['Close'].iloc[i - 1])
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    return round(sum(tr_list[-period:]) / period, 6)


def bollinger(closes: list, period: int = 20) -> tuple:
    """Ritorna (upper, mid, lower, position: UPPER/MIDDLE/LOWER)."""
    if len(closes) < period:
        return None, None, None, "MIDDLE"
    window = closes[-period:]
    mid = sum(window) / period
    std = math.sqrt(sum((c - mid) ** 2 for c in window) / period)
    upper = mid + 2 * std
    lower = mid - 2 * std
    cur = closes[-1]
    if cur >= upper * 0.999:
        pos = "UPPER"
    elif cur <= lower * 1.001:
        pos = "LOWER"
    else:
        pos = "MIDDLE"
    return round(upper, 5), round(mid, 5), round(lower, 5), pos


def support_resistance(hist, lookback: int = 60) -> tuple:
    """
    Supporti e resistenze via pivot points (swing high/low, finestra ±3).
    Ritorna (support, resistance) rispetto all'ultimo close.
    """
    if len(hist) < 10:
        c = float(hist['Close'].iloc[-1])
        return round(c * 0.97, 5), round(c * 1.03, 5)

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

    s_cands = sorted([l for l in p_lows  if l < cur * 0.9995], reverse=True)
    r_cands = sorted([x for x in p_highs if x > cur * 1.0005])

    support    = round(s_cands[0], 5) if s_cands else round(float(h['Low'].min()), 5)
    resistance = round(r_cands[0], 5) if r_cands else round(float(h['High'].max()), 5)
    return support, resistance


def ma(closes_series, period: int):
    """Media mobile semplice sull'ultima barra (pandas Series)."""
    if len(closes_series) < period:
        return None
    return float(closes_series.rolling(period).mean().iloc[-1])
