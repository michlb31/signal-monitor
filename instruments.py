#!/usr/bin/env python3
"""
Instruments — Universo tradabile IC Markets (Forex + CFD)
==========================================================
Catalogo degli strumenti con i metadati necessari a:
  - mapping news → strumenti (valute base/quote, tag evento)
  - analisi tecnica (simboli dati: Twelve Data spot / yfinance daily)
  - risk management (valore del punto per 0.01 lot, leva)

⚠️ I valori punto/margine sono STIME per il ticket: la verità operativa
   sono le "Specifiche contratto" sul tuo MT5 (tasto dx sul simbolo).
   Se un valore differisce, correggilo qui — il resto si adatta.

Convenzioni:
  point               = unità di misura dello stop (pip per FX, $ per metalli/indici)
  usd_per_point_001   = P/L in USD per 1 point di movimento con 0.01 lot
  leverage            = leva effettiva del conto utente (1:30)
"""

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]

# Codici COT CFTC per il posizionamento istituzionale (futures correlati)
COT_CODES = {
    "EUR": "099741", "GBP": "096742", "JPY": "097741", "CHF": "092741",
    "CAD": "090741", "AUD": "232741", "NZD": "112741",
    "XAUUSD": "088691", "XAGUSD": "084691", "XTIUSD": "067651",
}

INSTRUMENTS = {
    # ── FX MAJOR ────────────────────────────────────────────────────────
    # point = 1 pip (0.0001; 0.01 per JPY). 0.01 lot = 1.000 unità → ~$0.10/pip
    "EURUSD": {"cls": "fx", "leverage": 30, "base": "EUR", "quote": "USD", "td": "EUR/USD", "yf": "EURUSD=X",
               "point": 0.0001, "usd_per_point_001": 0.10, "tags": ["FED", "ECB", "CPI_US", "JOBS_US", "RISK"]},
    "GBPUSD": {"cls": "fx", "leverage": 30, "base": "GBP", "quote": "USD", "td": "GBP/USD", "yf": "GBPUSD=X",
               "point": 0.0001, "usd_per_point_001": 0.10, "tags": ["FED", "BOE", "CPI_US", "JOBS_US"]},
    "USDJPY": {"cls": "fx", "leverage": 30, "base": "USD", "quote": "JPY", "td": "USD/JPY", "yf": "USDJPY=X",
               "point": 0.01, "usd_per_point_001": 0.065, "tags": ["FED", "BOJ", "CPI_US", "RISK"]},
    "USDCHF": {"cls": "fx", "leverage": 30, "base": "USD", "quote": "CHF", "td": "USD/CHF", "yf": "USDCHF=X",
               "point": 0.0001, "usd_per_point_001": 0.11, "tags": ["FED", "SNB", "RISK", "GEO"]},
    "USDCAD": {"cls": "fx", "leverage": 30, "base": "USD", "quote": "CAD", "td": "USD/CAD", "yf": "USDCAD=X",
               "point": 0.0001, "usd_per_point_001": 0.073, "tags": ["FED", "BOC", "OIL"]},
    "AUDUSD": {"cls": "fx", "leverage": 20, "base": "AUD", "quote": "USD", "td": "AUD/USD", "yf": "AUDUSD=X",
               "point": 0.0001, "usd_per_point_001": 0.10, "tags": ["FED", "RBA", "CHINA", "RISK"]},
    "NZDUSD": {"cls": "fx", "leverage": 20, "base": "NZD", "quote": "USD", "td": "NZD/USD", "yf": "NZDUSD=X",
               "point": 0.0001, "usd_per_point_001": 0.10, "tags": ["FED", "CHINA"]},
    # ── FX MINOR / CROSS ────────────────────────────────────────────────
    "EURGBP": {"cls": "fx", "leverage": 30, "base": "EUR", "quote": "GBP", "td": "EUR/GBP", "yf": "EURGBP=X",
               "point": 0.0001, "usd_per_point_001": 0.127, "tags": ["ECB", "BOE"]},
    "EURJPY": {"cls": "fx", "leverage": 30, "base": "EUR", "quote": "JPY", "td": "EUR/JPY", "yf": "EURJPY=X",
               "point": 0.01, "usd_per_point_001": 0.065, "tags": ["ECB", "BOJ", "RISK"]},
    "GBPJPY": {"cls": "fx", "leverage": 30, "base": "GBP", "quote": "JPY", "td": "GBP/JPY", "yf": "GBPJPY=X",
               "point": 0.01, "usd_per_point_001": 0.065, "tags": ["BOE", "BOJ", "RISK"]},
    "AUDJPY": {"cls": "fx", "leverage": 20, "base": "AUD", "quote": "JPY", "td": "AUD/JPY", "yf": "AUDJPY=X",
               "point": 0.01, "usd_per_point_001": 0.065, "tags": ["RBA", "BOJ", "CHINA", "RISK"]},
    # ── METALLI ─────────────────────────────────────────────────────────
    # XAU: 0.01 lot = 1 oz → $1 per $1 di movimento (verificato live sul conto utente)
    "XAUUSD": {"cls": "metal", "leverage": 20, "base": "XAU", "quote": "USD", "td": "XAU/USD", "yf": "GC=F",
               "point": 1.0, "usd_per_point_001": 1.0, "tags": ["FED", "CPI_US", "JOBS_US", "GEO", "RISK", "REAL_YIELDS"]},
    # XAG: 0.01 lot = 50 oz → $0.50 per $0.01 → $50 per $1. ATR alto: quasi mai sizable con capitale piccolo
    "XAGUSD": {"cls": "metal", "leverage": 10, "base": "XAG", "quote": "USD", "td": "XAG/USD", "yf": "SI=F",
               "point": 0.01, "usd_per_point_001": 0.50, "tags": ["FED", "CPI_US", "GEO", "RISK"]},
    # ── ENERGIA ─────────────────────────────────────────────────────────
    # WTI/Brent: 0.01 lot = 1 barile → $0.01 per $0.01 ⇒ $1 per $1
    "XTIUSD": {"cls": "energy", "leverage": 10, "base": None, "quote": "USD", "td": None, "yf": "CL=F",
               "point": 0.01, "usd_per_point_001": 0.01, "tags": ["OPEC", "GEO", "CHINA", "OIL"]},
    "XBRUSD": {"cls": "energy", "leverage": 10, "base": None, "quote": "USD", "td": None, "yf": "BZ=F",
               "point": 0.01, "usd_per_point_001": 0.01, "tags": ["OPEC", "GEO", "OIL"]},
    "XNGUSD": {"cls": "energy", "leverage": 10, "base": None, "quote": "USD", "td": None, "yf": "NG=F",
               "point": 0.001, "usd_per_point_001": 0.01, "tags": ["GAS"]},
    # ── INDICI ──────────────────────────────────────────────────────────
    # 0.01 lot ≈ $0.01/punto su IC Markets (contratto 1 × indice). VERIFICARE su MT5.
    "US500":  {"cls": "index", "leverage": 20, "base": None, "quote": "USD", "td": None, "yf": "^GSPC",
               "point": 1.0, "usd_per_point_001": 0.01, "tags": ["FED", "CPI_US", "JOBS_US", "RISK"]},
    "USTEC":  {"cls": "index", "leverage": 20, "base": None, "quote": "USD", "td": None, "yf": "^NDX",
               "point": 1.0, "usd_per_point_001": 0.01, "tags": ["FED", "CPI_US", "RISK", "TECH"]},
    "US30":   {"cls": "index", "leverage": 20, "base": None, "quote": "USD", "td": None, "yf": "^DJI",
               "point": 1.0, "usd_per_point_001": 0.01, "tags": ["FED", "CPI_US", "JOBS_US", "RISK"]},
    "GER40":  {"cls": "index", "leverage": 20, "base": None, "quote": "EUR", "td": None, "yf": "^GDAXI",
               "point": 1.0, "usd_per_point_001": 0.011, "tags": ["ECB", "RISK"]},
    "UK100":  {"cls": "index", "leverage": 20, "base": None, "quote": "GBP", "td": None, "yf": "^FTSE",
               "point": 1.0, "usd_per_point_001": 0.013, "tags": ["BOE", "RISK"]},
    "JP225":  {"cls": "index", "leverage": 20, "base": None, "quote": "JPY", "td": None, "yf": "^N225",
               "point": 1.0, "usd_per_point_001": 0.0065, "tags": ["BOJ", "RISK"]},
    "AUS200": {"cls": "index", "leverage": 20, "base": None, "quote": "AUD", "td": None, "yf": "^AXJO",
               "point": 1.0, "usd_per_point_001": 0.0066, "tags": ["RBA", "CHINA", "RISK"]},
}


# ─────────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────────

def fx_pairs() -> dict:
    return {k: v for k, v in INSTRUMENTS.items() if v["cls"] == "fx"}


def pairs_for_currency(ccy: str) -> list:
    """Tutte le coppie FX che contengono la valuta, con il segno di esposizione.
    Ritorna [(symbol, sign)]: sign=+1 se la valuta è base (valuta forte → pair su),
    -1 se è quote (valuta forte → pair giù)."""
    out = []
    for sym, meta in INSTRUMENTS.items():
        if meta["cls"] != "fx":
            continue
        if meta["base"] == ccy:
            out.append((sym, +1))
        elif meta["quote"] == ccy:
            out.append((sym, -1))
    return out


def instruments_with_tag(tag: str) -> list:
    return [s for s, m in INSTRUMENTS.items() if tag in m["tags"]]


def currency_exposure(symbol: str) -> list:
    """Valute coinvolte in uno strumento (per il vincolo max-1-per-valuta)."""
    m = INSTRUMENTS.get(symbol, {})
    out = []
    if m.get("base") in CURRENCIES:
        out.append(m["base"])
    if m.get("quote") in CURRENCIES:
        out.append(m["quote"])
    # Metalli/indici/energia quotati in USD espongono comunque al dollaro
    if not out and m.get("quote") == "USD":
        out.append("USD")
    return out


if __name__ == "__main__":
    print(f"Universo IC Markets: {len(INSTRUMENTS)} strumenti")
    for cls in ["fx", "metal", "energy", "index"]:
        syms = [s for s, m in INSTRUMENTS.items() if m["cls"] == cls]
        print(f"  {cls:7s}: {', '.join(syms)}")
    print(f"\nEsempio pairs_for_currency('USD'): {pairs_for_currency('USD')}")
    print(f"Esempio instruments_with_tag('GEO'): {instruments_with_tag('GEO')}")
