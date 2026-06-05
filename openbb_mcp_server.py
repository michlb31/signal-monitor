#!/usr/bin/env python3
"""
OpenBB MCP Server — espone le funzioni finanziarie più utili come tool MCP.

Tool disponibili:
  - get_options_chain      : catena options completa (IV, OI, volume per strike)
  - get_insider_trading    : Form 4 strutturato (nome, ruolo, shares, prezzo)
  - get_price_quote        : prezzo real-time e metriche base
  - get_earnings_calendar  : prossimi earnings del ticker
  - get_analyst_targets    : price target dei broker
  - get_news               : ultime news per ticker

Avvio:  python openbb_mcp_server.py
Config: aggiunto in ~/.claude/settings.json (fatto automaticamente)
"""

import json
import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("openbb")

# ─────────────────────────────────────────────
#  LAZY INIT OpenBB (primo import lento, poi cached)
# ─────────────────────────────────────────────
_obb = None

def obb():
    global _obb
    if _obb is None:
        from openbb import obb as _o
        _obb = _o
    return _obb


# ═══════════════════════════════════════════════════════════
#  TOOL 1: Options chain
# ═══════════════════════════════════════════════════════════

@mcp.tool()
def get_options_chain(ticker: str, provider: str = "yfinance") -> str:
    """
    Recupera la catena options completa per un ticker.
    Ritorna: strike, scadenza, tipo (call/put), OI, volume, IV, bid/ask.
    Utile per analizzare posizionamento istituzionale e put/call ratio.

    Args:
        ticker: simbolo azionario (es. CEG, NVDA, RKLB)
        provider: yfinance (default, gratuito)
    """
    try:
        df = obb().derivatives.options.chains(ticker, provider=provider).to_dataframe()
        if df.empty:
            return f"Nessun dato options per {ticker}"

        price = float(df['underlying_price'].iloc[0])
        calls = df[df['option_type'] == 'call']
        puts  = df[df['option_type'] == 'put']

        total_call_vol = int(calls['volume'].fillna(0).sum())
        total_put_vol  = int(puts['volume'].fillna(0).sum())
        total_call_oi  = int(calls['open_interest'].fillna(0).sum())
        total_put_oi   = int(puts['open_interest'].fillna(0).sum())

        pc_vol = round(total_put_vol / total_call_vol, 3) if total_call_vol > 0 else 0
        pc_oi  = round(total_put_oi  / total_call_oi,  3) if total_call_oi  > 0 else 0

        # Top 5 strike per OI (call OTM > prezzo)
        otm_calls = calls[calls['strike'] > price * 1.05].nlargest(5, 'open_interest')
        top_strikes = []
        for _, row in otm_calls.iterrows():
            top_strikes.append(
                f"  strike ${row['strike']:.0f} (+{(row['strike']-price)/price*100:.0f}%) "
                f"exp {row['expiration']} | OI {int(row['open_interest'] or 0):,} "
                f"| vol {int(row['volume'] or 0):,} | IV {row['implied_volatility']:.0%}"
            )

        result = {
            "ticker": ticker,
            "current_price": price,
            "total_contracts": len(df),
            "put_call_ratio_volume": pc_vol,
            "put_call_ratio_oi": pc_oi,
            "total_call_volume": total_call_vol,
            "total_put_volume": total_put_vol,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "signal": "BULLISH" if pc_vol < 0.4 else ("BEARISH" if pc_vol > 2.0 else "NEUTRO"),
            "top_otm_call_strikes": top_strikes,
        }
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Errore options chain {ticker}: {e}"


# ═══════════════════════════════════════════════════════════
#  TOOL 2: Insider trading (Form 4)
# ═══════════════════════════════════════════════════════════

@mcp.tool()
def get_insider_trading(ticker: str, limit: int = 15) -> str:
    """
    Recupera i filing Form 4 (insider trading) via SEC.
    Filtra solo acquisti open market (esclude grant/award/Rule 16b-3).
    Ritorna: nome insider, ruolo, shares acquistate, prezzo, valore.

    Args:
        ticker: simbolo azionario (es. CEG, RKLB, OKLO)
        limit: numero di filing da analizzare (default 15)
    """
    try:
        df = obb().equity.ownership.insider_trading(ticker, limit=limit).to_dataframe()
        if df.empty:
            return f"Nessun Form 4 trovato per {ticker}"

        # Filtra acquisti open market
        buys = df[
            (df['acquisition_or_disposition'] == 'Acquisition') &
            (~df['transaction_type'].str.contains(
                r'Rule 16b-3|award|grant|automatic|dividend|exercise',
                case=False, na=False, regex=True
            ))
        ]

        if buys.empty:
            return f"{ticker}: nessun acquisto open market negli ultimi filing (solo grant/award trovati)"

        results = []
        for _, row in buys.iterrows():
            shares = float(row.get('securities_transacted', 0) or 0)
            price  = float(row.get('transaction_price', 0) or 0)
            value  = shares * price
            val_str = f"${value/1_000_000:.2f}M" if value >= 1_000_000 else (f"${value/1_000:.0f}K" if value >= 1_000 else "n/d")
            role = 'Officer' if row.get('officer') else ('Director' if row.get('director') else 'Insider')
            results.append({
                "date": str(row.get('filing_date', '')),
                "owner": str(row.get('owner_name', '')),
                "role": role,
                "shares": int(shares),
                "price": round(price, 2) if price > 0 else None,
                "value": val_str,
                "type": str(row.get('transaction_type', '')),
                "url": str(row.get('filing_url', '')),
            })

        return json.dumps({
            "ticker": ticker,
            "open_market_buys": len(results),
            "transactions": results
        }, indent=2, default=str)
    except Exception as e:
        return f"Errore insider trading {ticker}: {e}"


# ═══════════════════════════════════════════════════════════
#  TOOL 3: Price quote real-time
# ═══════════════════════════════════════════════════════════

@mcp.tool()
def get_price_quote(ticker: str) -> str:
    """
    Recupera prezzo attuale, variazioni e metriche base per un ticker.
    Ritorna: prezzo, variazione giornaliera, volume, 52w high/low, market cap.

    Args:
        ticker: simbolo azionario (es. CEG, NVDA, COIN)
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", auto_adjust=True)
        if hist.empty:
            return f"Nessun dato per {ticker}"

        cur  = float(hist['Close'].iloc[-1])
        prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else cur
        chg  = (cur - prev) / prev * 100

        fi = t.fast_info
        result = {
            "ticker": ticker,
            "price": round(cur, 2),
            "change_1d_pct": round(chg, 2),
            "volume_today": int(hist['Volume'].iloc[-1]),
            "52w_high": round(float(getattr(fi, 'year_high', 0)), 2),
            "52w_low":  round(float(getattr(fi, 'year_low', 0)), 2),
            "market_cap": getattr(fi, 'market_cap', None),
        }
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Errore quote {ticker}: {e}"


# ═══════════════════════════════════════════════════════════
#  TOOL 4: Earnings calendar
# ═══════════════════════════════════════════════════════════

@mcp.tool()
def get_earnings_calendar(ticker: str) -> str:
    """
    Recupera le prossime date di earnings e lo storico EPS per un ticker.
    Ritorna: data prossimi earnings, beat rate storico, EPS actual vs estimate.

    Args:
        ticker: simbolo azionario
    """
    try:
        result = obb().equity.calendar.earnings(ticker, provider="yfinance").to_dataframe()
        if result.empty:
            return f"Nessun earnings calendar per {ticker}"

        rows = []
        for _, row in result.head(8).iterrows():
            rows.append({k: str(v) for k, v in row.items()})

        return json.dumps({"ticker": ticker, "earnings": rows}, indent=2, default=str)
    except Exception as e:
        return f"Errore earnings {ticker}: {e}"


# ═══════════════════════════════════════════════════════════
#  TOOL 5: Analyst price targets
# ═══════════════════════════════════════════════════════════

@mcp.tool()
def get_analyst_targets(ticker: str) -> str:
    """
    Recupera i price target degli analisti e il consensus per un ticker.
    Ritorna: target medio, range min/max, numero di analisti, rating.

    Args:
        ticker: simbolo azionario
    """
    try:
        df = obb().equity.estimates.price_target(ticker, provider="yfinance").to_dataframe()
        if df.empty:
            return f"Nessun price target per {ticker}"

        import yfinance as yf
        info = yf.Ticker(ticker).info
        result = {
            "ticker": ticker,
            "target_mean":   info.get("targetMeanPrice"),
            "target_median": info.get("targetMedianPrice"),
            "target_high":   info.get("targetHighPrice"),
            "target_low":    info.get("targetLowPrice"),
            "analyst_count": info.get("numberOfAnalystOpinions"),
            "recommendation": info.get("recommendationKey"),
            "recent_targets": []
        }
        for _, row in df.head(5).iterrows():
            result["recent_targets"].append({k: str(v) for k, v in row.items()})

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Errore analyst targets {ticker}: {e}"


# ═══════════════════════════════════════════════════════════
#  TOOL 6: News recenti
# ═══════════════════════════════════════════════════════════

@mcp.tool()
def get_ticker_news(ticker: str, limit: int = 10) -> str:
    """
    Recupera le ultime news per un ticker.
    Utile per capire il contesto dietro un segnale di velocity anomala.

    Args:
        ticker: simbolo azionario
        limit: numero di articoli (default 10)
    """
    try:
        df = obb().news.company(ticker, limit=limit, provider="yfinance").to_dataframe()
        if df.empty:
            return f"Nessuna news per {ticker}"

        articles = []
        for _, row in df.iterrows():
            articles.append({
                "title":     str(row.get('title', '')),
                "published": str(row.get('date', row.get('published', ''))),
                "source":    str(row.get('source', '')),
                "url":       str(row.get('url', row.get('link', ''))),
            })

        return json.dumps({"ticker": ticker, "articles": articles[:limit]}, indent=2, default=str)
    except Exception as e:
        return f"Errore news {ticker}: {e}"


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="stdio")
