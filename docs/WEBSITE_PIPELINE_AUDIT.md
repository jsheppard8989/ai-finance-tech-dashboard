# Website & pipeline audit (2026-04-15)

This document records **inconsistencies**, **scheduling risks**, and **push/data-path** gaps found in-repo. Use it to prioritize fixes; it is not a substitute for checking what is actually **loaded** on your Mac (`launchctl list`, OpenClaw cron UI, and `crontab -l`).

---

## 1. Scheduling: three different “sources of truth”

| Source | What it claims |
|--------|----------------|
| **`docs/AUTOMATION.md` + `docs/launchd/*.plist`** | **22:00** and **05:00** `StartCalendarInterval`; optional **LaunchDaemon** every **5 min** → `run_if_scheduled.sh` (windows **22:00–22:20** and **05:00–05:20**); optional catch-up on login. |
| **`MEMORY.md` § Scheduled Jobs** | **OpenClaw cron** table: midnight analyze-only, 4am curate+fetch, **7am** morning publish, **12pm** midday, **10pm** evening — **not** defined in repo plists. |
| **`pipeline/run_midday_refresh.sh`** | **No git push** — comments say export only; safe for launchd. |

**Inconsistency:** Jobs listed only in **MEMORY / OpenClaw** cannot be verified from this repository. The **repo** only ships **evening/morning calendar plists** and daemon/catch-up helpers.

**Risk:** Believing MEMORY’s table matches **launchd** can leave you thinking 7am/12pm runs exist when only **OpenClaw** runs them—or the opposite.

**Recommendation:** Maintain **one** schedule table (e.g. in `docs/AUTOMATION.md`) that distinguishes **(A)** launchd plist jobs, **(B)** OpenClaw cron jobs, **(C)** manual. Update MEMORY to link to that table instead of duplicating times.

---

## 2. Double scheduling: daemon vs calendar plist

`docs/AUTOMATION.md` says: if you use the **LaunchDaemon**, **unload** the user **schedule** plist so the pipeline does not run twice.

**Risk:** If **both** `com.openclaw.pipeline.schedule` (22:00 / 05:00) **and** `com.openclaw.pipeline.daemon` are loaded, you can get **overlapping** full `auto_pipeline.py` runs. The daemon’s **90-minute** gate and marker file reduce duplicates but do not eliminate races if two triggers fire close together.

**Recommendation:** Document **current** install state in one line in `MEMORY.md` or `docs/AUTOMATION.md`: *“Active: daemon only”* or *“schedule plist only”*.

---

## 3. Midday refresh vs live site

**`pipeline/run_midday_refresh.sh`** runs `fetch_prices.py` → `generate_charts.py` → **`export_data.py`**. It does **not** push to GitHub.

**`MEMORY.md`** says **12:00pm** job includes **“git push only”** — that **does not match** `run_midday_refresh.sh` in this repo.

**Effect:** Local `site/data/` and charts can be **newer** than **GitHub Pages** until the next **`auto_pipeline.py`** push (or manual `publish_site.py` / `git push`).

**Recommendation:** Either (a) append **`publish_site.py`** (or scoped `git push`) to midday, or (b) fix MEMORY to say midday is **local-only** and expect the evening pipeline to publish.

---

## 4. Git push behavior: broad vs scoped

| Mechanism | `git add` behavior |
|-----------|---------------------|
| **`auto_pipeline.py` → `git_push()`** | **`git add -A`** (entire workspace unless `pathspecs` passed). |
| **`publish_site.py`** | **`git_push(..., pathspecs=["site"])`** — only **`site/`**. |

**Risk:** Full pipeline runs can commit **unrelated** workspace changes (experiments, docs, state) in the same commit as the site export.

**Recommendation:** Prefer **`pathspecs=["site"]`** (and optionally `pipeline/state` if you want run reports versioned) for routine pipeline pushes, or keep a **clean working tree** before scheduled runs.

---

## 5. `export_data.py` vs `auto_pipeline` export

Both use the same **`export_website_data` + `generate_website_js`** pattern. **`auto_pipeline.export_website()`** also **bumps `data.js?v=`** in **`site/index.html`** only — not **`archive.html`** / **`debait.html`**, which use **fixed or separate** query strings (e.g. `archive.html` uses `data.js?v=3`).

**Risk:** Browsers may cache **stale `data.js`** on secondary pages after deploy.

**Recommendation:** Single helper to bump **all** HTML references to `data.js`, or one shared `version.txt` read by tiny inline script (optional).

---

## 6. Front-end: multiple data paths (consistency / truth)

**`site/index.html`:**

- Primary: **`dashboardData`** from **`data.js`**.
- **Pundits:** `fetch('./data/pundits.json')` if pundits missing/empty.
- **Tickers:** `dashboardData.tickerScores` first, else **`fetch('./data/ticker_scores.json')`**.
- **Prices:** **`fetch('./price_data.json')`** (separate from `data.js`).
- **Status / freshness:** **`fetch('./data/status.json')`** and `dashboardData.generatedAt`.

**Effect:** The UI can **blend** sources; GitHub Pages cache + partial fetches can show **inconsistent** combinations (e.g. new `data.js` from one cache layer and old JSON from another).

**Recommendation:** Production path: **one bundle** (`data.js`) + **`publish_site` validation`**; reserve JSON fallbacks for **local dev** only (or behind `DEBUG_SITE`).

---

## 7. Hardcoded “embedded” content on the main page

**`site/index.html`** defines **`embeddedInsights`** (five newsletter-style items with **Jan/Feb** dates) and **`initPodcastSummaries()`** seeds **`podcastSummaries`** from that array.

This violates the **“no hardcoded insights”** rule in **`MEMORY.md`** audit checklist: modals can show **embedded** copy when Deep Dive lookup misses, so users may still see **static** narratives alongside DB-driven content.

**Recommendation:** Remove or gate **`embeddedInsights`** behind `DEBUG_SITE`, or replace with a single empty state pointing at **`dashboardData`** only.

---

## 8. HEARTBEAT vs MEMORY (pipeline auto-run)

- **`HEARTBEAT.md`:** Do **not** run **`auto_pipeline.py`** from heartbeat; only notify if stale.
- **`MEMORY.md`:** Implies heartbeat/Clawbot may run **`auto_pipeline`** when stale beyond threshold.

**These conflict.** The live policy should be **one sentence** in both files (recommend: **HEARTBEAT wins** unless Jared explicitly asks to auto-run).

---

## 9. Pipeline product rules drifting in MEMORY

**`MEMORY.md`** still describes Emerging Terms promotion as **score > 50**; **`auto_curate_terms.py`** uses **`PRIORITY_SCORE_PROMOTE_THRESHOLD = 66.7`**.

**Recommendation:** Update MEMORY or point to the constant in code so ops notes stay accurate.

---

## 10. Optional / ancillary jobs not scheduled in-repo

- **`process_term_promotion_replies.py`** — documented as **cron/launchd**; **no plist** in `docs/launchd/`.
- **`debate_weekly.py`** — triggered **Fridays** from **`auto_pipeline`** after export (OK if evening run exists).

---

## 11. Known technical debt (from MEMORY)

**`MEMORY.md`** still lists **`analyze_transcript.py`** cursor / ticker mention issues as **known bugs** (as of 2026-02-19). Re-verify and either fix or remove from MEMORY if resolved—stale bug notes cause false audits.

---

## Priority actions (suggested order)

1. **Reconcile schedules:** One doc for launchd vs OpenClaw; fix midday **push** story vs **`run_midday_refresh.sh`**.
2. **Narrow default `git_push`** for pipeline to **`site/`** (or document “clean tree before run”).
3. **Remove or debug-gate `embeddedInsights`** on **`index.html`**.
4. **Align cache-busting** across all pages loading **`data.js`**.
5. **Resolve HEARTBEAT vs MEMORY** on auto-running the pipeline.
6. **Update MEMORY** (Overton threshold; schedule table; heartbeat policy).

---

*Generated from repository inspection; actual loaded LaunchAgents/OpenClaw jobs may differ on disk.*
