<div align="center">

# 🔗 LinkBypassor

### Skip the 4-step wait. Get your real link.

Paste a LinkShortX short link — we click through the verification steps,
countdowns and interstitial for you, then hand you the gateway + Telegram link.

[![Deploy to Render](https://img.shields.io/badge/Deploy-Render-1a56db?style=for-the-badge&logo=render)](https://render.com)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com)
[![Playwright](https://img.shields.io/badge/Playwright-1.55-2EAD33?style=for-the-badge&logo=playwright)](https://playwright.dev)
[![SQLite](https://img.shields.io/badge/SQLite-No_external_DB-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)

**🌐 Live demo:** *deploy on Render & paste your URL here*

</div>

---

## ✨ Features

| Feature | Details |
|---|---|
| 🖱️ **Full auto-bypass** | Real headless Chromium walks all 4 advertiser steps + the LinkShortX interstitial |
| 📦 **Batch mode** | Up to **5 links at once**, processed in parallel |
| ⏳ **5-min countdown UI** | Start a job, close the tab, come back — result is waiting |
| 💾 **Per-device history** | SQLite storage, no external DB, no login — history survives reopen |
| 📋 **Copy / Open** | One-tap copy button + open-link action on every result |
| 💙 **Blue landing UI** | Hero → how-it-works → bypass form → history, all in one page |

## 🔄 How it works

```
Short link (linkshortx.in/XXXXXX)
        │
        ▼  307 redirect
Hindisink verifier ──► Step 1 ──► Step 2 ──► Step 3 ──► Step 4
  (Verify → Continue → Go to step N, ~30s timers each)
        │
        ▼  #final click loops back
LinkShortX interstitial (/links/arm → 5s countdown → Get Link → /links/go)
        │
        ▼  /links/gw/<token> (fresh, ~15 min validity)
Telegram bot deep-link  ✅  ← your result
```

> Each run takes **~4–5 minutes** (four countdowns + timers). That's why the UI
> tells you to come back in 5 minutes — the job keeps running server-side.

## 🗂️ Project structure

```
linkbypassor/
├── backend/
│   ├── app.py              # Flask API + serves the UI (job queue, history)
│   ├── worker.py           # Playwright bypass engine (4 steps → gateway → telegram)
│   ├── db.py               # SQLite storage — no external DB
│   └── static/
│       ├── index.html      # Blue landing + bypass form + history UI
│       ├── styles.css
│       └── app.js          # Device-id, countdowns, batch, polling, history
├── link_bypassor/
│   ├── bypass.py           # Standalone CLI version (python bypass.py <url>)
│   └── sniff.py            # Lightweight gateway/telegram sniffer
├── requirements.txt
├── render.yaml             # One-click Render deploy
└── README.md
```

## 🔌 API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check → `{ok: true}` |
| `POST` | `/api/jobs` | Start one job `{short_url}` → `{device_id, job}` |
| `POST` | `/api/jobs/batch` | Start up to 5 `{urls[]}` in parallel → `{device_id, jobs[]}` |
| `GET` | `/api/jobs/<id>` | Poll status/progress/result |
| `GET` | `/api/history` | This device's job history (via `X-Device-Id` header) |

Job lifecycle: `queued → running → done / failed`, with live `progress` messages
(`"Step 2 of 4: verifying..."`) and `gateway` / `telegram` / `final_url` on completion.

## 💾 Storage — no external DB

- Each browser mints a stable `device_id` in `localStorage` (no login) sent as `X-Device-Id`.
- Server keeps a single SQLite file (`data/jobs.db`) with `devices` + `jobs` tables.
- History is **per-device** and survives tab close, refresh, and reopen.
- ⚠️ On Render free tier the disk is ephemeral across **redeploys** — attach a
  [Render Disk](https://render.com/docs/disks) mounted at the `data/` path to keep
  history permanently. Still zero external database.

## 🚀 Run locally

```bash
git clone https://github.com/Alex-Leo-Reeves/linkbypassor.git
cd linkbypassor
pip install -r requirements.txt
python -m playwright install chromium
python -m backend.app        # → http://localhost:5000
```

CLI version (no server, prints gateway + telegram to terminal, ~4 min):

```bash
cd link_bypassor && python bypass.py https://linkshortx.in/XXXXXX
```

## ☁️ Deploy on Render

1. Push to GitHub (already configured — just `git push origin main`).
2. Render Dashboard → **New +** → **Web Service** → connect this repo.
3. Render auto-reads `render.yaml`:
   - **Build:** `pip install -r requirements.txt && python -m playwright install chromium`
   - **Start:** `gunicorn backend.app:app --workers 1 --threads 8 --timeout 600`
   - Pins `PYTHON_VERSION=3.12.7` (3.14 breaks old greenlet wheels).

> 💡 Free tier + 3 parallel Chromium jobs × ~5 min each is heavy. If you see
> timeouts, upgrade to Starter or set `MAX_WORKERS=2`.

<div align="center">

---

**Runs the boring clicks so you don't have to 💙**

Made with Flask + Playwright · History in SQLite · UI in vanilla HTML/CSS/JS

</div>


