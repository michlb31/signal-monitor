# Early Signal Monitor — Setup

## Installazione (30 secondi)

```bash
pip install feedparser requests
```

## Uso

```bash
# Run singolo — stampa segnali + salva signals.json
python signal_monitor.py

# Watch mode — refresh automatico ogni 30 minuti
python signal_monitor.py --watch

# Intervallo personalizzato (es. ogni 15 minuti)
python signal_monitor.py --watch --interval 15
```

Poi apri `dashboard.html` nel browser — si aggiorna automaticamente ogni 5 minuti leggendo `signals.json`.

## Cosa monitora

| Fonte | Pattern | Perché è importante |
|---|---|---|
| SEC EDGAR 8-K RSS | Tutti | Filing obbligatori in real-time, prima dei media |
| SEC EDGAR keyword search | PPA, Nuclear, AI | Cerca testo specifico negli 8-K recenti |
| Utility Dive RSS | PPA, Nuclear | Prima fonte per deal energetici AI |
| Data Center Frontier RSS | PPA | Deal data center prima dei generalisti |
| Seeking Alpha RSS | Analyst | Early tesi rialziste |
| Benzinga Analyst Upgrades | Analyst | Upgrade in real-time |
| NucNet RSS | Nuclear | Deal nucleare ante-media |
| PR Newswire Energy | Tutti | Press release aziendali diretti |

## Scoring (0-100)

- **≥ 70** 🚨 Alert — agisci entro ore
- **45-69** 📌 Watch — monitora sviluppi
- **< 45** 📋 Info — contesto generale

## Pattern e score bonus

| Trigger | Score |
|---|---|
| Trump acquisto azioni (disclosure) | +50 |
| Trump su Truth Social | +40 |
| Big Tech + energia deal | +40 |
| Power Purchase Agreement | +35 |
| Contratto Pentagon/DoD | +30 |
| Casa minore upgrade (D.A.Davidson, Daiwa...) | +30 |
| Riavvio nucleare | +35 |
| Quantum + governo | +35 |
| Ogni ticker watchlist trovato | +10 |

## Aggiungere fonti o ticker

Modifica `signal_monitor.py`:
- **FEEDS**: aggiungi URL RSS di nuove fonti
- **WATCHLIST_TICKERS**: aggiungi nomi azienda da monitorare
- **SIGNAL_RULES**: aggiungi nuove keyword con score e tag

## Automazione (macOS)

Per eseguire automaticamente ogni mattina alle 7:00:
```bash
crontab -e
# Aggiungi questa riga:
0 7 * * * cd /path/to/cartella && python signal_monitor.py >> signal_log.txt 2>&1
```
