#!/usr/bin/env python3
"""
Twelve Data — feed SPOT per XAU/USD e forex (matcha TradingView/broker)
=======================================================================
Risolve il disallineamento future-vs-spot: yfinance dà solo il future
COMEX (GC=F), che quota a premio sullo spot e con ritardo nel weekend.
Twelve Data fornisce lo SPOT XAU/USD reale, identico a TradingView.

Free tier: 800 richieste/giorno, 8/min — imposta TWELVEDATA_API_KEY.

API:
  td_price(symbol)        → prezzo spot real-time (float)
  td_quote(symbol)        → OHLC + variazione del giorno
  td_time_series(...)     → storico daily (DataFrame) per MA/RSI/ATR
  available()             → True se la key è impostata
"""

import os
import requests
import pandas as pd

BASE = "https://api.twelvedata.com"


def _key() -> str:
    return os.environ.get("TWELVEDATA_API_KEY", "").strip()


def available() -> bool:
    return bool(_key())


def td_price(symbol: str = "XAU/USD") -> float:
    """Prezzo spot real-time. Ritorna None se key assente o errore."""
    if not _key():
        return None
    try:
        r = requests.get(f"{BASE}/price",
                         params={"symbol": symbol, "apikey": _key()}, timeout=12)
        data = r.json()
        if "price" in data:
            return float(data["price"])
    except Exception:
        pass
    return None


def td_quote(symbol: str = "XAU/USD") -> dict:
    """Quote completo: prezzo, OHLC, variazione %, timestamp."""
    if not _key():
        return {}
    try:
        r = requests.get(f"{BASE}/quote",
                         params={"symbol": symbol, "apikey": _key()}, timeout=12)
        d = r.json()
        if "close" in d:
            return {
                "price": float(d["close"]),
                "open": float(d.get("open", 0) or 0),
                "high": float(d.get("high", 0) or 0),
                "low": float(d.get("low", 0) or 0),
                "prev_close": float(d.get("previous_close", 0) or 0),
                "change_pct": float(d.get("percent_change", 0) or 0),
                "timestamp": d.get("timestamp"),
                "symbol": d.get("symbol", symbol),
            }
    except Exception:
        pass
    return {}


def td_time_series(symbol: str = "XAU/USD", interval: str = "1day",
                   outputsize: int = 365) -> pd.DataFrame:
    """
    Storico OHLC come DataFrame (index = datetime, colonne Open/High/Low/Close).
    Compatibile con gli helper TA (enricher) che usano queste colonne.
    Ritorna DataFrame vuoto se key assente o errore.
    """
    if not _key():
        return pd.DataFrame()
    try:
        r = requests.get(f"{BASE}/time_series", params={
            "symbol": symbol, "interval": interval,
            "outputsize": outputsize, "apikey": _key(),
        }, timeout=20)
        d = r.json()
        vals = d.get("values")
        if not vals:
            return pd.DataFrame()
        df = pd.DataFrame(vals)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime").sort_index()
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c].astype(float)
        # Rinomina per compatibilità con enricher (_rsi, _atr, ecc.)
        df = df.rename(columns={"open": "Open", "high": "High",
                                "low": "Low", "close": "Close"})
        if "volume" in df.columns:
            df["Volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        else:
            df["Volume"] = 0
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception:
        return pd.DataFrame()


# ─────────────────────────────────────────────
#  PREZZO ORO UNIFICATO (spot se disponibile, altrimenti future)
# ─────────────────────────────────────────────

def get_gold_price() -> dict:
    """
    Ritorna il prezzo dell'oro preferendo lo SPOT (Twelve Data) se la key c'è,
    altrimenti il future (yfinance GC=F) come fallback.
    Ritorna {price, source, is_spot}.
    """
    if available():
        q = td_quote("XAU/USD")
        if q:
            return {"price": q["price"], "source": "Twelve Data (spot XAU/USD)",
                    "is_spot": True, "quote": q}
        p = td_price("XAU/USD")
        if p:
            return {"price": p, "source": "Twelve Data (spot)", "is_spot": True}
    # Fallback future
    try:
        import yfinance as yf
        p = float(yf.Ticker("GC=F").fast_info.last_price)
        return {"price": p, "source": "yfinance GC=F (future, ~ritardo)", "is_spot": False}
    except Exception:
        return {"price": None, "source": "nessuna fonte", "is_spot": False}


# ─────────────────────────────────────────────
#  TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\nTwelve Data — test feed spot\n" + "─" * 50)
    if not available():
        print("⚠️  TWELVEDATA_API_KEY non impostata.")
        print("   Registrati su twelvedata.com e:")
        print("   export TWELVEDATA_API_KEY='la_tua_key'")
    else:
        print("✓ Key trovata, test in corso...")
        q = td_quote("XAU/USD")
        if q:
            print(f"  Spot XAU/USD: ${q['price']:.2f} ({q['change_pct']:+.2f}%)")
            print(f"  OHLC oggi: O{q['open']:.0f} H{q['high']:.0f} L{q['low']:.0f}")
            print(f"  Timestamp: {q['timestamp']}")
        else:
            print("  ⚠️ quote fallito — verifica la key")
        ts = td_time_series("XAU/USD", outputsize=5)
        if not ts.empty:
            print(f"  Storico OK: {len(ts)} barre, ultimo close ${ts['Close'].iloc[-1]:.2f}")

    # Confronto con future
    g = get_gold_price()
    print(f"\n  get_gold_price() → ${g['price']:.2f}  [{g['source']}]")
