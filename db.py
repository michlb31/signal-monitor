#!/usr/bin/env python3
"""
Layer 3b — Signal History Database
====================================
Traccia ogni segnale nel tempo e misura l'accuracy reale del monitor.

Per ogni segnale salvato:
  - Registra: ticker, score, pattern, fonte, timestamp
  - Dopo 7/14/30gg: recupera il prezzo e calcola il rendimento reale
  - Calcola hit rate per tipo di pattern e fonte
  - Identifica quali segnali hanno davvero predetto movimenti

Questo e' il modulo che nel tempo dice "il pattern congress_buy
ha un hit rate del 72% con rendimento medio +18% in 14gg".

Database: SQLite locale (signals.db) — nessuna dipendenza esterna.
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "signals.db"

# ─────────────────────────────────────────────
#  SCHEMA
# ─────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at     TEXT NOT NULL,
    ticker          TEXT,
    ticker_symbol   TEXT,
    pattern         TEXT,
    source          TEXT,
    score           INTEGER,
    alert           INTEGER,
    title           TEXT,
    url             TEXT,
    price_at_signal REAL,
    days_to_earnings INTEGER,
    timing          TEXT,
    tags            TEXT    -- JSON array
);

CREATE TABLE IF NOT EXISTS outcomes (
    signal_id       INTEGER REFERENCES signals(id),
    checked_at      TEXT NOT NULL,
    days_after      INTEGER,
    price_then      REAL,
    pct_change      REAL,
    hit             INTEGER  -- 1 se movimento > 5%, 0 altrimenti
);

CREATE TABLE IF NOT EXISTS accuracy_cache (
    pattern         TEXT PRIMARY KEY,
    hit_rate        REAL,
    avg_return_7d   REAL,
    avg_return_14d  REAL,
    avg_return_30d  REAL,
    sample_size     INTEGER,
    updated_at      TEXT
);
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ─────────────────────────────────────────────
#  WRITE
# ─────────────────────────────────────────────

def save_signals(signals: list):
    """
    Salva i segnali alert nel database.
    Salva solo quelli con score >= 60 e ticker per non sprecare spazio.
    """
    conn = get_conn()
    saved = 0
    now = datetime.now(timezone.utc).isoformat()

    for sig in signals:
        if sig.get('final_score', 0) < 60:
            continue
        symbols = sig.get('ticker_symbols', [])
        if not symbols:
            continue

        ctx = sig.get('price_context', {})
        ticker_symbol = symbols[0]
        tickers_mentioned = sig.get('tickers_mentioned', [])
        ticker_name = tickers_mentioned[0] if tickers_mentioned else ticker_symbol

        # Controlla se gia' salvato nelle ultime 6h per non duplicare
        existing = conn.execute(
            "SELECT id FROM signals WHERE ticker_symbol=? AND recorded_at > ? AND pattern=?",
            (ticker_symbol, (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(), sig.get('pattern', ''))
        ).fetchone()
        if existing:
            continue

        conn.execute("""
            INSERT INTO signals
            (recorded_at, ticker, ticker_symbol, pattern, source, score,
             alert, title, url, price_at_signal, days_to_earnings, timing, tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            now,
            ticker_name,
            ticker_symbol,
            sig.get('pattern', ''),
            sig.get('source', ''),
            sig.get('final_score', 0),
            int(sig.get('alert', False)),
            sig.get('title', '')[:200],
            sig.get('url', '')[:300],
            ctx.get('current_price'),
            ctx.get('days_to_earnings'),
            ctx.get('timing'),
            json.dumps(sig.get('tags', [])),
        ))
        saved += 1

    conn.commit()
    conn.close()
    if saved:
        print(f"  ✓ {saved} segnali salvati nel database")


# ─────────────────────────────────────────────
#  READ / OUTCOME TRACKING
# ─────────────────────────────────────────────

def update_outcomes():
    """
    Aggiorna i rendimenti reali per i segnali salvati.
    Da chiamare una volta al giorno. Richiede yfinance.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  ⚠️  yfinance non installato — outcomes non aggiornati")
        return

    conn = get_conn()
    now = datetime.now(timezone.utc)
    check_points = [7, 14, 30]

    # Segnali senza outcome completo
    pending = conn.execute("""
        SELECT s.id, s.ticker_symbol, s.recorded_at, s.price_at_signal
        FROM signals s
        WHERE s.price_at_signal IS NOT NULL
        AND s.ticker_symbol IS NOT NULL
        AND s.recorded_at < ?
    """, ((now - timedelta(days=6)).isoformat(),)).fetchall()

    updated = 0
    for row in pending:
        for days in check_points:
            # Controlla se outcome gia' registrato
            exists = conn.execute(
                "SELECT id FROM outcomes WHERE signal_id=? AND days_after=?",
                (row['id'], days)
            ).fetchone()
            if exists:
                continue

            recorded = datetime.fromisoformat(row['recorded_at'])
            target_date = recorded + timedelta(days=days)
            if target_date > now:
                continue

            # Recupera prezzo alla data target
            try:
                t = yf.Ticker(row['ticker_symbol'])
                start = (target_date - timedelta(days=2)).strftime("%Y-%m-%d")
                end = (target_date + timedelta(days=2)).strftime("%Y-%m-%d")
                hist = t.history(start=start, end=end)
                if hist.empty:
                    continue
                price_then = float(hist['Close'].iloc[-1])
                price_entry = row['price_at_signal']
                pct_change = (price_then - price_entry) / price_entry * 100 if price_entry else 0
                hit = 1 if pct_change > 5 else 0

                conn.execute("""
                    INSERT OR REPLACE INTO outcomes
                    (signal_id, checked_at, days_after, price_then, pct_change, hit)
                    VALUES (?,?,?,?,?,?)
                """, (row['id'], now.isoformat(), days, price_then, round(pct_change, 2), hit))
                updated += 1
            except Exception:
                pass

    conn.commit()
    conn.close()
    if updated:
        print(f"  ✓ {updated} outcome aggiornati")


def get_accuracy_report() -> str:
    """
    Genera report di accuracy per pattern.
    Mostra hit rate e rendimento medio per ogni tipo di segnale.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            s.pattern,
            COUNT(DISTINCT s.id)                                    AS total,
            AVG(CASE WHEN o.days_after=7  THEN o.pct_change END)   AS avg_7d,
            AVG(CASE WHEN o.days_after=14 THEN o.pct_change END)    AS avg_14d,
            AVG(CASE WHEN o.days_after=30 THEN o.pct_change END)    AS avg_30d,
            AVG(CASE WHEN o.days_after=14 THEN o.hit END)*100       AS hit_rate_14d
        FROM signals s
        LEFT JOIN outcomes o ON o.signal_id = s.id
        GROUP BY s.pattern
        HAVING total >= 3
        ORDER BY hit_rate_14d DESC NULLS LAST
    """).fetchall()
    conn.close()

    if not rows:
        return "Dati insufficienti — servono almeno 3 segnali per pattern con outcome a 14gg."

    lines = ["\n📊 ACCURACY REPORT — Pattern performance\n" + "─"*55]
    for r in rows:
        hr = f"{r['hit_rate_14d']:.0f}%" if r['hit_rate_14d'] is not None else "n/a"
        a7  = f"{r['avg_7d']:+.1f}%"  if r['avg_7d']  is not None else "n/a"
        a14 = f"{r['avg_14d']:+.1f}%" if r['avg_14d'] is not None else "n/a"
        a30 = f"{r['avg_30d']:+.1f}%" if r['avg_30d'] is not None else "n/a"
        lines.append(
            f"  {r['pattern']:12s} | N={r['total']:3d} | "
            f"Hit@14d: {hr:>5} | "
            f"Avg: 7d={a7} 14d={a14} 30d={a30}"
        )
    return "\n".join(lines)


def get_recent_signals(days: int = 7, min_score: int = 60) -> list:
    """Recupera segnali recenti dal database."""
    conn = get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM signals
        WHERE recorded_at > ? AND score >= ?
        ORDER BY score DESC, recorded_at DESC
        LIMIT 50
    """, (cutoff, min_score)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
#  STANDALONE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "report":
        print(get_accuracy_report())
    elif cmd == "update":
        print("Aggiornamento outcomes...")
        update_outcomes()
        print(get_accuracy_report())
    elif cmd == "recent":
        signals = get_recent_signals(days=7)
        print(f"\nSegnali ultimi 7gg: {len(signals)}")
        for s in signals[:20]:
            print(f"  [{s['score']:3d}] [{s['pattern']:10s}] {s['ticker_symbol']:6s} {s['recorded_at'][:10]} — {s['title'][:60]}")
