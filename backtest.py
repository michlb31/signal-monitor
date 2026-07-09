#!/usr/bin/env python3
"""
Backtest Engine — Validazione storica della logica di setup
============================================================
Scopo: misurare se i setup tecnici generati da enricher.py (direzione,
entry, stop, target) avrebbero davvero funzionato sui dati storici.
Serve a ISTRUIRE il modello: quali setup/parametri hanno edge reale.

Due modalità:
  1. TECHNICAL REPLAY (default)
     Riproduce la logica enricher giorno per giorno sui prezzi storici,
     SENZA lookahead bias (usa solo dati fino al giorno i, valuta su i+1..i+N).
     Simula ogni trade: TP o SL colpito per primo? Aggrega win-rate, R medio,
     profit factor per direzione e setup_type.

  2. SIGNAL OUTCOMES (--db)
     Legge i segnali reali salvati in signals.db e i loro outcome
     (via db.update_outcomes), per validare il sistema live nel tempo.

Niente dipendenze nuove: usa yfinance + pandas + math (già presenti).

Uso:
  python backtest.py                    # replay su tutta la watchlist, 1y
  python backtest.py --tickers CEG,SMR  # ticker specifici
  python backtest.py --period 2y --horizon 20
  python backtest.py --db               # report sugli outcome reali dal DB
"""

import argparse
import math
import statistics
from datetime import datetime
from collections import defaultdict

import yfinance as yf
import pandas as pd

try:
    from signal_monitor import WATCHLIST
    DEFAULT_TICKERS = list(WATCHLIST.values())
except Exception:
    DEFAULT_TICKERS = ["CEG", "SMR", "VST", "OKLO", "NVDA", "AVGO", "PLTR", "RKLB"]


# ═══════════════════════════════════════════════════════════
#  INDICATORI (vettoriali, no-lookahead per costruzione)
# ═══════════════════════════════════════════════════════════

def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def _atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _macd_hist(close: pd.Series) -> pd.Series:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi"]   = _rsi_series(df["Close"])
    df["atr"]   = _atr_series(df)
    df["ma50"]  = df["Close"].rolling(50).mean()
    df["ma200"] = df["Close"].rolling(200).mean()
    df["macd_h"] = _macd_hist(df["Close"])
    df["vol_avg"] = df["Volume"].rolling(20).mean()
    df["chg5"]  = df["Close"].pct_change(5) * 100
    df["chg30"] = df["Close"].pct_change(30) * 100
    # Supporto/resistenza rolling (max/min ultimi 60gg, escluso oggi → no lookahead)
    df["resist"] = df["High"].rolling(60).max().shift(1)
    df["support"] = df["Low"].rolling(60).min().shift(1)
    return df


# ═══════════════════════════════════════════════════════════
#  LOGICA SETUP (mirror di enricher, no-lookahead)
# ═══════════════════════════════════════════════════════════

# Soglie per classe di asset: le azioni momentum si muovono 5-10x il forex.
# Il profilo "fx" scala i trigger sulla volatilità valutaria (e include
# MEAN_REVERT in entrambe le direzioni: sul forex il range trading è simmetrico).
PROFILES = {
    "stock": {"short_rsi": 72, "short_chg30": 35, "dip_chg5": -7, "trend_chg30": 20},
    "fx":    {"short_rsi": 70, "short_chg30": 6,  "dip_chg5": -2, "trend_chg30": 5},
}


def _classify(row, profile: str = "stock") -> tuple:
    """
    Ritorna (direction, setup_type) o (None, None) se nessun trigger di entry.
    Solo setup azionabili — non valuta ogni giorno, solo trigger reali.
    """
    P = PROFILES[profile]
    rsi, chg5, chg30 = row["rsi"], row["chg5"], row["chg30"]
    price = row["Close"]
    ma50, ma200 = row["ma50"], row["ma200"]
    resist, support = row["resist"], row["support"]
    vol_ratio = row["Volume"] / row["vol_avg"] if row["vol_avg"] > 0 else 1.0
    macd_bull = row["macd_h"] > 0

    if any(pd.isna(x) for x in [rsi, ma50, ma200, chg30, resist, support]):
        return None, None

    # SHORT: overbought esteso vicino ai massimi
    if rsi > P["short_rsi"] and chg30 > P["short_chg30"] and price >= resist * 0.97:
        return "SHORT", "MEAN_REVERT_SHORT"

    # FX: mean-reversion anche LONG (oversold sul supporto — il forex rangeggia)
    if profile == "fx" and rsi < 100 - P["short_rsi"] and chg30 < -P["short_chg30"] \
            and price <= support * 1.03:
        return "LONG", "MEAN_REVERT_LONG"

    # LONG DIP_BUY: storno su trend rialzista
    if chg5 < P["dip_chg5"] and price > ma50 and rsi < 45:
        return "LONG", "DIP_BUY"

    # LONG BREAKOUT: rottura resistenza con volume (senza volume nel FX)
    vol_ok = vol_ratio > 1.5 or (profile == "fx" and row["vol_avg"] == 0)
    if price >= resist * 0.99 and vol_ok and price > ma50:
        return "LONG", "BREAKOUT"

    # TREND_FOLLOW: trend sano + momentum (FX: anche short simmetrico)
    if price > ma50 > ma200 and macd_bull and 0 < chg30 <= P["trend_chg30"] and 45 < rsi < 65:
        return "LONG", "TREND_FOLLOW"
    if profile == "fx" and price < ma50 < ma200 and not macd_bull \
            and -P["trend_chg30"] <= chg30 < 0 and 35 < rsi < 55:
        return "SHORT", "TREND_FOLLOW"

    return None, None


def _simulate_trade(df, i, direction, atr, horizon, atr_stop=1.5, atr_target=3.0):
    """
    Simula il trade aperto al close del giorno i.
    Stop = 1.5 ATR, Target = 3 ATR (R:R 2:1).
    Cammina su i+1..i+horizon: TP o SL per primo?
    Ritorna dict con esito.
    """
    entry = df["Close"].iloc[i]
    if direction == "LONG":
        stop   = entry - atr_stop * atr
        target = entry + atr_target * atr
    else:
        stop   = entry + atr_stop * atr
        target = entry - atr_target * atr

    end = min(i + horizon, len(df) - 1)
    outcome = None
    exit_price = df["Close"].iloc[end]
    days_held = end - i

    for j in range(i + 1, end + 1):
        hi = df["High"].iloc[j]
        lo = df["Low"].iloc[j]
        if direction == "LONG":
            if lo <= stop:
                outcome, exit_price, days_held = "LOSS", stop, j - i
                break
            if hi >= target:
                outcome, exit_price, days_held = "WIN", target, j - i
                break
        else:
            if hi >= stop:
                outcome, exit_price, days_held = "LOSS", stop, j - i
                break
            if lo <= target:
                outcome, exit_price, days_held = "WIN", target, j - i
                break

    if outcome is None:
        # Né TP né SL: chiusura a fine orizzonte
        ret = (exit_price - entry) / entry * 100
        if direction == "SHORT":
            ret = -ret
        outcome = "WIN" if ret > 0 else "LOSS"
        r_multiple = ret / (atr_stop * atr / entry * 100)
    else:
        ret = (exit_price - entry) / entry * 100
        if direction == "SHORT":
            ret = -ret
        r_multiple = atr_target / atr_stop if outcome == "WIN" else -1.0

    return {
        "outcome": outcome,
        "return_pct": ret,
        "r_multiple": r_multiple,
        "days_held": days_held,
    }


# ═══════════════════════════════════════════════════════════
#  BACKTEST RUNNER
# ═══════════════════════════════════════════════════════════

def backtest_technical(tickers, period="1y", horizon=15, cooldown=10,
                       profile="stock"):
    """
    Esegue il backtest replay su una lista di ticker.
    cooldown: giorni minimi tra due entry sullo stesso ticker (evita overlap).
    profile: 'stock' o 'fx' (soglie scalate sulla volatilità dell'asset class).
    """
    all_trades = []
    print(f"\n{'='*68}")
    print(f"  BACKTEST TECNICO [{profile.upper()}] — {len(tickers)} strumenti | "
          f"period={period} | horizon={horizon}gg")
    print(f"  Stop 1.5×ATR | Target 3×ATR (R:R 2:1) | no-lookahead")
    print(f"{'='*68}\n")

    for tk in tickers:
        try:
            df = yf.Ticker(tk).history(period=period, auto_adjust=True)
            if len(df) < 220:
                continue
            df = _prepare(df)
            last_entry = -999
            n_tk = 0
            for i in range(200, len(df) - 1):
                if i - last_entry < cooldown:
                    continue
                direction, setup = _classify(df.iloc[i], profile=profile)
                if direction is None:
                    continue
                atr = df["atr"].iloc[i]
                if pd.isna(atr) or atr <= 0:
                    continue
                res = _simulate_trade(df, i, direction, atr, horizon)
                res.update({"ticker": tk, "direction": direction, "setup": setup,
                            "date": df.index[i].strftime("%Y-%m-%d")})
                all_trades.append(res)
                last_entry = i
                n_tk += 1
            if n_tk:
                print(f"  {tk:6s} → {n_tk:3d} trade simulati")
        except Exception as e:
            print(f"  {tk:6s} → errore: {str(e)[:50]}")

    return all_trades


def _stats(trades) -> dict:
    if not trades:
        return {}
    wins = [t for t in trades if t["outcome"] == "WIN"]
    rets = [t["return_pct"] for t in trades]
    gross_win = sum(t["return_pct"] for t in trades if t["return_pct"] > 0)
    gross_loss = abs(sum(t["return_pct"] for t in trades if t["return_pct"] < 0))

    # ── Metriche quant (modulo 6 del metodo) ──────────────────
    mean_r = statistics.mean(rets)
    std_r = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    downside = [r for r in rets if r < 0]
    dstd = statistics.pstdev(downside) if len(downside) > 1 else 0.0
    avg_days = statistics.mean(t["days_held"] for t in trades)
    ann = math.sqrt(252 / max(avg_days, 1))          # fattore di annualizzazione
    sharpe = (mean_r / std_r) * ann if std_r > 0 else None
    sortino = (mean_r / dstd) * ann if dstd > 0 else None

    # Max drawdown sull'equity curve (trade in ordine cronologico)
    ordered = sorted(trades, key=lambda t: t["date"])
    equity = peak = 0.0
    max_dd = 0.0
    for t in ordered:
        equity += t["return_pct"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "n": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "avg_return": mean_r,
        "median_return": statistics.median(rets),
        "avg_days": avg_days,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else float("inf"),
        "total_return": sum(rets),
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
    }


def report(trades):
    if not trades:
        print("\n⚠️  Nessun trade simulato — controlla ticker/periodo.")
        return

    print(f"\n{'─'*68}")
    print(f"📊 RISULTATI COMPLESSIVI ({len(trades)} trade)")
    print(f"{'─'*68}")
    s = _stats(trades)
    print(f"  Win rate:       {s['win_rate']:.1f}%")
    print(f"  Avg return:     {s['avg_return']:+.2f}% per trade")
    print(f"  Median return:  {s['median_return']:+.2f}%")
    print(f"  Profit factor:  {s['profit_factor']:.2f}  (>1 = profittevole)")
    print(f"  Sharpe (ann.):  {s['sharpe']:.2f}" if s.get('sharpe') else "  Sharpe:         n/d")
    print(f"  Sortino (ann.): {s['sortino']:.2f}" if s.get('sortino') else "  Sortino:        n/d")
    print(f"  Max drawdown:   -{s['max_drawdown']:.1f}% (equity curve dei trade)")
    print(f"  Hold medio:     {s['avg_days']:.1f} giorni")

    # Per direzione
    print(f"\n{'─'*68}")
    print(f"📈 PER DIREZIONE")
    print(f"{'─'*68}")
    for d in ["LONG", "SHORT"]:
        sub = [t for t in trades if t["direction"] == d]
        if sub:
            ss = _stats(sub)
            icon = "📈" if d == "LONG" else "📉"
            print(f"  {icon} {d:6s} N={ss['n']:3d} | Win {ss['win_rate']:4.1f}% | "
                  f"Avg {ss['avg_return']:+.2f}% | PF {ss['profit_factor']:.2f}")

    # Per setup type
    print(f"\n{'─'*68}")
    print(f"🏗  PER SETUP TYPE  (quali hanno edge reale)")
    print(f"{'─'*68}")
    setups = defaultdict(list)
    for t in trades:
        setups[t["setup"]].append(t)
    ranked = sorted(setups.items(), key=lambda kv: _stats(kv[1])["profit_factor"], reverse=True)
    for setup, sub in ranked:
        ss = _stats(sub)
        edge = "✅" if ss["profit_factor"] > 1.3 else ("🟡" if ss["profit_factor"] > 1.0 else "🔴")
        print(f"  {edge} {setup:18s} N={ss['n']:3d} | Win {ss['win_rate']:4.1f}% | "
              f"Avg {ss['avg_return']:+.2f}% | PF {ss['profit_factor']:.2f}")

    # Insight per il modello
    print(f"\n{'─'*68}")
    print(f"🧠 INSIGHT PER IL MODELLO")
    print(f"{'─'*68}")
    best = ranked[0] if ranked else None
    worst = ranked[-1] if ranked else None
    if best and _stats(best[1])["profit_factor"] > 1.3:
        print(f"  ✅ '{best[0]}' è il setup più affidabile (PF {_stats(best[1])['profit_factor']:.2f}) "
              f"→ aumentare il peso/score di questi segnali")
    if worst and _stats(worst[1])["profit_factor"] < 1.0:
        print(f"  🔴 '{worst[0]}' perde nel backtest (PF {_stats(worst[1])['profit_factor']:.2f}) "
              f"→ ridurre lo score o aggiungere filtri")
    long_s = _stats([t for t in trades if t["direction"] == "LONG"])
    short_s = _stats([t for t in trades if t["direction"] == "SHORT"])
    if long_s and short_s:
        better = "LONG" if long_s["profit_factor"] > short_s["profit_factor"] else "SHORT"
        print(f"  → I setup {better} hanno performance migliore in questo periodo")


# ═══════════════════════════════════════════════════════════
#  MODALITÀ DB (outcome reali)
# ═══════════════════════════════════════════════════════════

def backtest_from_db():
    try:
        from db import update_outcomes, get_accuracy_report
        print("Aggiornamento outcome dai segnali reali salvati...")
        update_outcomes()
        print(get_accuracy_report())
    except Exception as e:
        print(f"⚠️  DB non disponibile o dati insufficienti: {e}")


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Backtest engine signal-monitor")
    p.add_argument("--tickers", type=str, default="", help="CSV ticker (default: watchlist)")
    p.add_argument("--period", type=str, default="1y", help="1y / 2y / 5y")
    p.add_argument("--horizon", type=int, default=15, help="giorni max di holding")
    p.add_argument("--db", action="store_true", help="report outcome reali dal DB")
    p.add_argument("--fx", action="store_true",
                   help="profilo FX: universo IC Markets + soglie forex")
    p.add_argument("--json", type=str, default="",
                   help="scrivi le statistiche in un file JSON (per la dashboard)")
    args = p.parse_args()

    if args.db:
        backtest_from_db()
    else:
        profile = "fx" if args.fx else "stock"
        if args.tickers:
            tickers = args.tickers.split(",")
        elif args.fx:
            from instruments import INSTRUMENTS
            tickers = [m["yf"] for m in INSTRUMENTS.values()]
        else:
            tickers = DEFAULT_TICKERS
        trades = backtest_technical(tickers, period=args.period,
                                    horizon=args.horizon, profile=profile)
        report(trades)

        if args.json and trades:
            import json as _json
            from collections import defaultdict as _dd
            from datetime import datetime as _dt, timezone as _tz
            by_setup = _dd(list)
            for t in trades:
                by_setup[t["setup"]].append(t)
            payload = {
                "generated_at": _dt.now(_tz.utc).isoformat(),
                "profile": profile, "period": args.period,
                "horizon": args.horizon, "n_instruments": len(tickers),
                "overall": _stats(trades),
                "by_direction": {d: _stats([t for t in trades if t["direction"] == d])
                                 for d in ("LONG", "SHORT")},
                "by_setup": {s: _stats(v) for s, v in by_setup.items()},
            }
            with open(args.json, "w") as f:
                _json.dump(payload, f, indent=1, default=str)
            print(f"\n✓ statistiche salvate in {args.json}")
