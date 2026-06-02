# Deploy — Early Signal Monitor

## Architettura finale

```
GitHub repo (privato)
  ├── signal_monitor.py
  ├── dashboard.html
  ├── requirements.txt
  ├── signals.json          ← aggiornato ogni 30 min dal bot
  └── .github/workflows/
        └── monitor.yml     ← GitHub Actions: esecuzione automatica

Slack workspace
  └── #signals channel      ← riceve alert quando score >= 70
```

---

## Step 1 — Crea repo GitHub privato

1. Vai su https://github.com/new
2. Nome: `signal-monitor` (privato)
3. **Non** inizializzare con README
4. Dal terminale:

```bash
cd "/Users/micheleguidi/Library/Application Support/Claude/.../outputs"
git init
git add .
git commit -m "init: early signal monitor"
git remote add origin https://github.com/TUO_USERNAME/signal-monitor.git
git push -u origin main
```

---

## Step 2 — Configura Slack Incoming Webhook

1. Vai su https://api.slack.com/apps → **Create New App** → From scratch
2. Nome app: `Signal Monitor` | scegli il tuo workspace
3. Vai su **Incoming Webhooks** → attiva → **Add New Webhook to Workspace**
4. Scegli il canale (es. `#signals` o DM a te stesso)
5. Copia la **Webhook URL** (inizia con `https://hooks.slack.com/services/...`)

---

## Step 3 — Aggiungi Webhook URL come GitHub Secret

1. Vai sul repo GitHub → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**:
   - Name: `SLACK_WEBHOOK_URL`
   - Value: incolla la webhook URL di Slack
3. Salva

---

## Step 4 — Attiva GitHub Pages per il dashboard (opzionale)

1. Repo → **Settings** → **Pages**
2. Source: **Deploy from a branch** → `main` → `/` (root)
3. Salva — dopo ~2 minuti il dashboard sarà accessibile su:
   `https://TUO_USERNAME.github.io/signal-monitor/dashboard.html`

---

## Come funziona da questo momento

- GitHub Actions esegue `signal_monitor.py` ogni **30 minuti**, 24/7, gratis
- Se trova alert con score ≥ 70, manda un messaggio Slack formattato
- `signals.json` viene committato automaticamente ad ogni run
- Apri il dashboard da qualsiasi browser: legge `signals.json` dal repo

## Test manuale Slack (opzionale)

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
python signal_monitor.py --slack-webhook $SLACK_WEBHOOK_URL --min-score 50
```

## Personalizzazioni comuni

| Cosa cambiare | Dove |
|---|---|
| Soglia alert Slack | `--min-score 65` nel workflow YAML |
| Frequenza run | `cron: '*/15 * * * *'` per ogni 15 min |
| Aggiungere ticker | `WATCHLIST` in signal_monitor.py |
| Aggiungere soglia velocity | `VELOCITY_THRESHOLDS` in signal_monitor.py |
