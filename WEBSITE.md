# Scarcity & Abundance — What the Site Is

This project is a **static dashboard** for **AI, finance, and tech** themes. It turns podcasts and newsletters into a single place to scan **who matters**, **what they argued**, **which names are getting attention**, and **which ideas are moving from fringe to mainstream** (the Overton window).

The live experience is **HTML + CSS + JavaScript** in `site/`. There is no server-side page rendering in production. The browser loads pages and a generated **`data.js`** file that holds almost everything the UI needs.

---

## What the Website Does

In plain terms, the site:

1. **Ranks tickers** using weighted mentions from podcasts and newsletters (podcasts carry more weight than newsletters in the scoring model).
2. **Surfaces “Latest Insights”** — short summaries of important takeaways, with optional **Deep Dive** long reads stored in the database and shown in modals.
3. **Tracks the Overton Window** — terms and concepts that are emerging or contested in investing and tech discourse, including auto-curated **Emerging Terms** that can graduate into definitions.
4. **Profiles podcast pundits** — guests with structured bios, “latest thesis” from the most recent analyzed episode, and transcript-grounded **proof lines** (citation + excerpt) when available.
5. **Shows charts and archive views** — price visuals and searchable historical content that ages and archives according to pipeline rules.
6. **Hosts supporting pages** — for example pipeline health, weekly debate audio, and contact flows where those are wired up.

Everything the main page shows is **derived from one SQLite database** (`pipeline/dashboard.db`) and exported into JSON/JS under `site/data/`.

---

## How It Functions (End-to-End)

### 1. Ingestion

- **Podcasts:** Active RSS feeds in `podcast_feeds.txt` → download → audio is transcribed (often via a **queue + worker** so long episodes do not crash the main pipeline). Paused feeds live in `podcast_feeds_on_hold.txt`.
- **Newsletters:** Email ingestion (e.g. Gmail IMAP) writes structured content into the pipeline inbox for analysis.

### 2. Analysis and storage

- Transcripts and articles are analyzed by Python scripts (LLM-assisted where configured). Outputs are stored in **`dashboard.db`**: episodes, ticker mentions, insights, suggested terms, definitions, Overton terms, entities/appearances for pundits, deep dives, daily scores, etc.
- **Schema and migrations** live with the codebase (`pipeline/schema.sql`, `db_manager.py`), so the database stays aligned with what the site expects.

### 3. Export (the bridge to the browser)

- **`export_data.py`** (and the export step inside **`auto_pipeline.py`**) calls **`export_for_website()`** on the database manager. That writes JSON files such as `ticker_scores.json`, `pundits.json`, and related artifacts into **`site/data/`**.
- The same flow builds **`data.js`**, which defines a single global object **`dashboardData`** (tickers, insights, Overton terms, deep dives, suggested terms, guests, pundits, archive payloads, chart version metadata, etc.).
- **`index.html`** and other pages load **`data.js`** and render cards, lists, and modals from that object.

### 4. Publishing

- The site is **static files**. Typical deployment is **GitHub Pages** (or any static host): push `site/` after export, and the world sees the new data.

### 5. Automation on your machine (optional but normal)

- **Cron, launchd, or another scheduler** runs `auto_pipeline.py` or `export_data.py` on a cadence so the DB and `site/data/` stay fresh without manual steps.
- **Live state:** See **[docs/AUTOMATION.md](docs/AUTOMATION.md)** for the current schedule, loaded LaunchAgents, and ops RACI.

---

## Why It Consistently Works

**Single source of truth.**  
All “live” content paths through **one database**. The UI does not maintain its own parallel state; it renders what was last exported. That removes an entire class of drift bugs (no “forgot to sync” between API and DB).

**Deterministic pipeline.**  
Ingest → analyze → export is a **repeatable script**. Re-running the pipeline on the same inputs reproduces the same stored structure (modulo intentional timestamps and LLM variance in analysis text).

**Static front end.**  
No runtime database connection from the browser. Pages are fast, cacheable, and resilient: if `data.js` is present and valid JSON/JS, the dashboard works.

**Separation of heavy work.**  
Transcription is isolated in a **worker + queue** pattern so the main pipeline does not depend on finishing huge audio jobs in one process. That keeps scheduled runs reliable.

**Explicit export contract.**  
`dashboardData` in `data.js` is the **contract** between Python and the HTML. Adding a field means updating export and the few pages that read it — changes are localized and reviewable.

**Operational guardrails.**  
State files, logs, and health pages (`pipeline-health.html`, tracker JSON) make it obvious when a stage failed (fetch, transcribe, analyze, export) without silently showing stale data forever — especially when you compare export timestamps to cron logs.

---

## Quick reference

| Piece | Role |
|--------|------|
| `pipeline/dashboard.db` | Canonical store for insights, tickers, terms, pundits, episodes |
| `pipeline/auto_pipeline.py` | Main orchestration: fetch / analyze / enrich / export (flags vary) |
| `pipeline/export_data.py` | Standalone export + `data.js` generation |
| `pipeline/publish_site.py` | **Gated publish:** export → validate bundle → commit/push **`site/` only** (fails closed; see script docstring) |
| `site/data/data.js` | Browser-facing bundle (`dashboardData`), including **`priceSnapshot`** (from `price_data.json`) so the main page does not depend on a separate price fetch in production |
| `auto_pipeline.py` git step | Pushes **`site/`** only (same as `publish_site`), so unrelated workspace files are not committed with the dashboard |
| `site/index.html` | Primary dashboard UI |

This document describes **behavior and architecture**, not secret configuration. API keys, tokens, and hostnames belong in **`.env`** (never committed).
