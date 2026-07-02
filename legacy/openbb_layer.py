#!/usr/bin/env python3
"""
OpenBB Layer — Dati strutturati ad alta qualità gratuiti
=========================================================
Integra due fonti che OpenBB espone gratis (SEC provider):

  1. fetch_openbb_insiders()
     Form 4 strutturato via SEC: nome insider, ruolo, shares, prezzo,
     valore stimato. Filtra solo acquisti open market (esclude grant/award).
     Molto più informativo del solo titolo RSS.

  2. fetch_openbb_options_chains()
     Options chain multi-scadenza via yfinance provider.
     Analizza P/C ratio, concentrazione OI su strike OTM, IV term structure
     su TUTTE le scadenze disponibili — più robusto dell'analisi single-expiry.

Fallback silenzioso: se OpenBB non è importabile, entrambe le funzioni
restituiscono lista vuota senza rompere il resto del sistema.
"""

import time
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
#  WATCHLIST (stessa del monitor principale)
# ─────────────────────────────────────────────
from signal_monitor import WATCHLIST, WATCHLIST_NAMES

# ─────────────────────────────────────────────
#  LAZY INIT OpenBB (evita import time pesante se non serve)
# ─────────────────────────────────────────────
_obb = None

def _get_obb():
    global _obb
    if _obb is None:
        from openbb import obb
        _obb = obb
    return _obb


# ─────────────────────────────────────────────
#  FONTE 1: Form 4 strutturato (SEC provider)
# ─────────────────────────────────────────────

def fetch_openbb_insiders(days_back: int = 7) -> list:
    """
    Recupera Form 4 via OpenBB SEC provider — dati strutturati completi.
    Filtra: solo acquisti open market (esclude grant, award, Rule 16b-3).
    Score basato su: valore transazione, ruolo insider, tipo acquisto.
    Integra (non sostituisce) il feed RSS Form 4 già presente.
    """
    signals = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    try:
        obb = _get_obb()
    except Exception:
        return signals  # OpenBB non disponibile

    for company, ticker in WATCHLIST.items():
        try:
            df = obb.equity.ownership.insider_trading(ticker, limit=20).to_dataframe()
            if df.empty:
                continue

            # Filtra: solo acquisizioni open market — esclude compensation/award
            buys = df[
                (df['acquisition_or_disposition'] == 'Acquisition') &
                (~df['transaction_type'].str.contains(
                    r'Rule 16b-3|award|grant|automatic|dividend|exercise',
                    case=False, na=False, regex=True
                ))
            ]

            for _, row in buys.iterrows():
                # Parse data filing
                filing_date = row.get('filing_date')
                try:
                    if hasattr(filing_date, 'to_pydatetime'):
                        pub_dt = filing_date.to_pydatetime()
                    else:
                        pub_dt = datetime.fromisoformat(str(filing_date))
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pub_dt = datetime.now(timezone.utc)

                if pub_dt < cutoff:
                    continue

                owner    = str(row.get('owner_name', 'Unknown')).strip()
                is_off   = bool(row.get('officer', False))
                is_dir   = bool(row.get('director', False))
                role     = 'Officer' if is_off else ('Director' if is_dir else 'Insider')
                shares   = float(row.get('securities_transacted', 0) or 0)
                price    = float(row.get('transaction_price', 0) or 0)
                value    = shares * price
                trans    = str(row.get('transaction_type', '')).strip()
                url      = str(row.get('filing_url', '')) or \
                           f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&company={ticker}"

                # Score basato su valore stimato
                if value >= 1_000_000:
                    raw_score = 82
                elif value >= 500_000:
                    raw_score = 74
                elif value >= 100_000:
                    raw_score = 65
                elif shares > 0 and price > 0:
                    raw_score = 55
                else:
                    raw_score = 48  # quantità non disponibile

                # Boost ruolo
                if role == 'Officer':
                    raw_score = min(raw_score + 5, 95)

                age_h = max((datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600, 0)

                # Formatta valore leggibile
                if value >= 1_000_000:
                    val_str = f"${value / 1_000_000:.2f}M"
                elif value >= 1_000:
                    val_str = f"${value / 1_000:.0f}K"
                elif value > 0:
                    val_str = f"${value:.0f}"
                else:
                    val_str = "importo n/d"

                price_str = f" @ ${price:.2f}" if price > 0 else ""
                shares_str = f"{shares:,.0f}" if shares > 0 else "n/d"

                signals.append({
                    "title": f"[Form4 OBB] {owner} ({role}) COMPRA {ticker} — {shares_str} shares{price_str} = {val_str}",
                    "source": "OpenBB Insider (SEC)",
                    "source_type": "insider",
                    "url": url,
                    "published": str(filing_date),
                    "published_dt": pub_dt.isoformat(),
                    "summary": (
                        f"{owner} ({role}) ha acquistato {shares_str} shares di {company.title()} "
                        f"({ticker}){price_str} per un valore di {val_str}. "
                        f"Tipo transazione: {trans}"
                    ),
                    "raw_score": raw_score,
                    "final_score": raw_score,
                    "tags": ["insider", "openbb"],
                    "alert": raw_score >= 60,
                    "pattern": "insider",
                    "matched_rules": [
                        f"Open market buy {val_str}",
                        f"Role: {role}",
                        *(["Valore >$500K"] if value >= 500_000 else []),
                        *(["Valore >$1M"] if value >= 1_000_000 else []),
                    ],
                    "tickers_mentioned": [company],
                    "ticker_symbols": [ticker],
                    "age_hours": round(age_h, 1),
                    "convergence_boost": 0,
                })
            time.sleep(0.3)

        except Exception:
            pass  # Fallback silenzioso per ogni ticker

    return signals


# ─────────────────────────────────────────────
#  FONTE 2: Options chain multi-scadenza
# ─────────────────────────────────────────────

# Ticker esclusi: large cap liquid dove il P/C ratio è meno informativo
_LARGE_CAP_EXCLUDE = {'nvidia', 'amd', 'intel', 'oracle', 'broadcom', 'dell', 'palantir'}


def fetch_openbb_options_chains(tickers_subset: list = None) -> list:
    """
    Analisi options chain multi-scadenza via OpenBB (yfinance provider).
    Upgrade rispetto a fetch_putcall_anomalies() in options_scanner.py:
      - Analizza TUTTE le scadenze disponibili (non solo la nearest)
      - Rileva concentrazione OI su strike OTM specifici
      - Analizza IV term structure (near-term cheap = pre-catalyst signal)
      - Calcola convergenza di segnali (score 50 + 8 per ogni segnale extra)

    Anomalie rilevate:
      1. P/C ratio volume globale < 0.35  (bullish)
      2. P/C ratio OI globale < 0.50      (bullish accumulation)
      3. OTM call OI > 25% del totale     (posizionamento direzionale)
      4. Volume spike su OTM call         (flusso istituzionale)
      5. IV inversion near < long         (near-term unusually cheap)
      6. P/C ratio > 2.5                  (bearish hedge)
    """
    signals = []

    try:
        obb = _get_obb()
    except Exception:
        return signals

    if tickers_subset is None:
        tickers_subset = [
            t for n, t in WATCHLIST.items()
            if n not in _LARGE_CAP_EXCLUDE
        ][:15]  # limite per non sovraccaricare le API

    for ticker in tickers_subset:
        try:
            df = obb.derivatives.options.chains(ticker, provider='yfinance').to_dataframe()
            if df.empty:
                continue

            underlying_price = float(df['underlying_price'].iloc[0])
            if underlying_price <= 0:
                continue

            calls = df[df['option_type'] == 'call']
            puts  = df[df['option_type'] == 'put']

            # ── Metriche globali (tutte le scadenze) ──────────────────────
            total_call_vol = calls['volume'].fillna(0).sum()
            total_put_vol  = puts['volume'].fillna(0).sum()
            total_call_oi  = calls['open_interest'].fillna(0).sum()
            total_put_oi   = puts['open_interest'].fillna(0).sum()

            # Volume troppo basso = rumore
            if total_call_vol + total_put_vol < 100:
                continue

            pc_ratio_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 99
            pc_ratio_oi  = total_put_oi / total_call_oi   if total_call_oi  > 0 else 99

            # ── OTM call accumulation (+10% / +40% strike range) ──────────
            otm_calls = calls[
                (calls['strike'] >= underlying_price * 1.10) &
                (calls['strike'] <= underlying_price * 1.40)
            ]
            otm_call_oi  = otm_calls['open_interest'].fillna(0).sum()
            otm_call_vol = otm_calls['volume'].fillna(0).sum()

            # Strike dominante per concentrazione OI
            max_oi_strike = max_oi_val = max_oi_exp = 0
            if not otm_calls.empty and otm_call_oi > 0:
                idx = otm_calls['open_interest'].fillna(0).idxmax()
                max_oi_strike = float(otm_calls.loc[idx, 'strike'])
                max_oi_val    = float(otm_calls.loc[idx, 'open_interest'])
                max_oi_exp    = str(otm_calls.loc[idx, 'expiration'])

            # ── IV term structure ──────────────────────────────────────────
            df_calls = calls.copy()
            short_iv = df_calls[df_calls['dte'] <= 30]['implied_volatility'].mean()
            long_iv  = df_calls[(df_calls['dte'] > 60) & (df_calls['dte'] <= 90)]['implied_volatility'].mean()
            iv_inversion = (
                short_iv > 0 and long_iv > 0 and
                float(short_iv) < float(long_iv) * 0.85
            )

            # ── Classificazione anomalie ──────────────────────────────────
            is_bullish_pc_vol  = pc_ratio_vol < 0.35
            is_bullish_pc_oi   = pc_ratio_oi  < 0.50
            is_otm_accum       = (total_call_oi > 0 and
                                  otm_call_oi > total_call_oi * 0.25 and
                                  otm_call_oi > 500)
            is_vol_spike       = (otm_call_vol > 500 and
                                  total_call_vol > 0 and
                                  otm_call_vol > total_call_vol * 0.20)
            is_iv_inv          = iv_inversion
            is_bearish         = pc_ratio_vol > 2.5

            bullish_signals = sum([
                is_bullish_pc_vol,
                is_bullish_pc_oi,
                is_otm_accum,
                is_vol_spike,
                is_iv_inv,
            ])

            if bullish_signals == 0 and not is_bearish:
                continue

            # ── Score ──────────────────────────────────────────────────────
            if is_bearish:
                direction = "BEARISH"
                raw_score = 48
            else:
                direction = "BULLISH"
                # Base 54, +8 per ogni segnale aggiuntivo (max 94 con 5 su 5)
                raw_score = min(54 + (bullish_signals - 1) * 8, 94)

            # ── Etichette anomalie per summary ────────────────────────────
            anomaly_labels = []
            if is_bullish_pc_vol: anomaly_labels.append(f"P/C vol {pc_ratio_vol:.2f}")
            if is_bullish_pc_oi:  anomaly_labels.append(f"P/C OI {pc_ratio_oi:.2f}")
            if is_otm_accum:
                pct = otm_call_oi / total_call_oi * 100 if total_call_oi > 0 else 0
                anomaly_labels.append(f"OTM OI {int(otm_call_oi):,} ({pct:.0f}% totale)")
            if is_vol_spike:      anomaly_labels.append(f"OTM vol spike {int(otm_call_vol):,}")
            if is_iv_inv:         anomaly_labels.append(f"IV inversion near={short_iv:.1%} long={long_iv:.1%}")
            if is_bearish:        anomaly_labels.append(f"P/C BEARISH {pc_ratio_vol:.2f}")

            # Strike con max concentrazione OI
            strike_note = ""
            if max_oi_strike > 0 and max_oi_val > 100:
                upside_pct = (max_oi_strike - underlying_price) / underlying_price * 100
                strike_note = (
                    f"Max OI: strike ${max_oi_strike:.0f} (+{upside_pct:.0f}%) "
                    f"exp {max_oi_exp} — {int(max_oi_val):,} contratti"
                )

            name = next((n for n, s in WATCHLIST.items() if s == ticker), ticker.lower())

            signals.append({
                "title": (
                    f"[Options OBB] {ticker} — {direction} "
                    f"({bullish_signals} segnali{'/ bearish hedge' if is_bearish else ''})"
                ),
                "source": "OpenBB Options Chain",
                "source_type": "options",
                "url": f"https://finance.yahoo.com/quote/{ticker}/options",
                "published": datetime.now(timezone.utc).isoformat(),
                "published_dt": datetime.now(timezone.utc).isoformat(),
                "summary": " | ".join(anomaly_labels) + (f" | {strike_note}" if strike_note else ""),
                "raw_score": raw_score,
                "final_score": raw_score,
                "tags": ["options", direction.lower(), "openbb"],
                "alert": raw_score >= 62,
                "pattern": "options",
                "matched_rules": anomaly_labels[:4],
                "tickers_mentioned": [name],
                "ticker_symbols": [ticker],
                "age_hours": 0.0,
                "convergence_boost": 0,
            })
            time.sleep(0.5)

        except Exception:
            pass  # Fallback silenzioso

    return signals


# ─────────────────────────────────────────────
#  ENTRY POINT (test diretto)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🔬 OpenBB Layer — test diretto\n" + "─" * 50)

    print("\n[1/2] Insider trading strutturato (7gg)...")
    ins = fetch_openbb_insiders(days_back=7)
    print(f"  → {len(ins)} segnali insider open market")
    for s in ins[:5]:
        print(f"  🏦 [{s['raw_score']}] {s['title'][:90]}")
        print(f"      {s['summary'][:120]}")

    print("\n[2/2] Options chain multi-scadenza...")
    opts = fetch_openbb_options_chains()
    print(f"  → {len(opts)} anomalie rilevate")
    for s in opts[:5]:
        print(f"  📈 [{s['raw_score']}] {s['title'][:90]}")
        print(f"      {s['summary'][:120]}")
