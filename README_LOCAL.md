## Start Here (Local Workspace)

This is the “clean desk” view for working with 6AIndolf in Cursor.

### What matters day-to-day

- **Dashboards & docs**
  - `site/index.html` – main website/dashboard layout.
  - `site/pipeline-health.html` – Pipeline Health & Clawbot todo view.
  - `MEMORY.md` – long-term notes & decisions.
  - `HEARTBEAT.md` – what Clawbot should do each heartbeat.
  - `MODELS.md` – which LLMs are used where (and cost guardrails).

- **Pipeline core**
  - `pipeline/auto_pipeline.py` – main orchestrator (full pipeline).
  - `pipeline/analyze_transcript.py` – AI analysis of transcripts.
  - `pipeline/curate.py` – discover + approve + auto-download episodes.
  - `pipeline/export_data.py` – export JSON/JS for the site.
  - `pipeline/db_manager.py` – DB access + exports for the site.

### What you can mostly ignore in the explorer

These are operational folders; they’re ignored in git so Cursor can hide them:

- `pipeline/state/` – pipeline_status, curation logs, analysis failures, last run reports.
- `pipeline/logs/` – long pipeline log output.
- `pipeline/audio/`, `pipeline/transcripts/`, `pipeline/whisper_queue/`, `pipeline/whisper_done/` – raw/derived audio + text.
- `site/data/` – generated JSON/JS that the site reads (`status.json`, `episode_status.json`, `data.js`, etc.).

You almost never need to open these by hand; the pipeline and Clawbot manage them.

### How to run things (from a terminal in this repo)

- **Full pipeline + deploy**
  ```bash
  cd pipeline
  python3 auto_pipeline.py
  ```

- **Analyze-only (use when transcripts exist but episodes show “needs_analysis”)**
  ```bash
  cd pipeline
  python3 auto_pipeline.py --analyze-only
  ```

- **Re-export site data only**
  ```bash
  cd pipeline
  python3 export_data.py
  ```

### Mental model

- Use **this README_LOCAL.md** + `MEMORY.md` as your map.
- Let **Clawbot + cron jobs** keep the noisy state folders up to date.
- Stay mostly in:
  - `site/` for UI,
  - `pipeline/*.py` for logic,
  - `MEMORY.md`, `HEARTBEAT.md`, `MODELS.md` for behavior and configuration.

