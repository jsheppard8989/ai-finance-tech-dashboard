# Workspace Layout

How the OpenClaw workspace is organized and where to find things.

## Root

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Agent instructions (read first every session) |
| `SOUL.md`, `USER.md`, `IDENTITY.md` | Who you are, who you're helping |
| `MEMORY.md` | Long-term curated memory (main session only) |
| `HEARTBEAT.md`, `TOOLS.md` | Heartbeat checklist, tool notes |
| `memory/` | Daily notes `YYYY-MM-DD.md` |
| `.env` | Local env vars (secrets, API keys) |
| `audio/` | Downloaded podcast audio (used by pipeline + whisper worker) |
| `whisper_queue/` | Audio files waiting for transcription (worker consumes) |
| `whisper_done/` | Completed transcripts from worker (swept into pipeline) |
| `whisper_worker.sh` | LaunchAgent script: watches queue, runs Whisper, writes to whisper_done |
| `podcast_feeds.txt` | RSS feed URLs (one per line) for fetch_latest |
| `pipeline/` | Data pipeline: fetch → transcribe → analyze → export |
| `site/` | Static site (data, charts, index) |
| `scripts/` | One-off and helper scripts (Twitter RSS, etc.) |
| `contacts.py`, `contact_api.py`, `contact_search.py` | Contact form backend and APIs |
| `pushover.sh`, `send_imessage.sh` | Notifications (used by pipeline) |
| `pending_contacts.json` | Pending contact form submissions |

## pipeline/

| Path | Purpose |
|------|---------|
| `transcripts/` | **All** transcript `.txt` and `.meta.json` files (single place) |
| `state/` | Logs and state: `curation_log.json`, `pipeline_status.json`, `fetch_log.json`, `pending_approval.json`, `votes.json`, `pipeline_report.txt` |
| `processed/` | Per-transcript `.processed` markers (analyze_transcript) |
| `inbox/` | Newsletter JSON from ingest |
| `analysis/` | Analysis outputs (e.g. top_picks, research) |
| `dashboard.db` | SQLite DB (episodes, tickers, insights, scores) |
| `*.py` | Pipeline scripts (see pipeline/README.md) |
| `requirements.txt`, `schema.sql` | Dependencies and DB schema |

**Entry points**

- **Full pipeline:** `python3 auto_pipeline.py` (fetch → analyze → export; fetch uses queue-only)
- **Analyze + export only:** `python3 auto_pipeline.py --analyze-only`
- **Sweep whisper_done and publish:** `python3 sweep_whisper_done_and_publish.py`
- **Fetch latest (enqueue):** `python3 fetch_latest.py` or `python3 fetch_latest.py --queue-only`

## site/

| Path | Purpose |
|------|---------|
| `data/` | Generated: `data.js`, `archive.json`, `podcast_summaries.json`, etc. |
| `charts/` | Generated price charts (PNG) |
| `index.html`, `archive.html` | Front-end pages |
| `feeds/` | Twitter RSS feeds (generated) |

## Don’t commit

- `.env`, `*.db`, `__pycache__/`
- Large binaries in `audio/`, `whisper_queue/`, `whisper_done/`
- Sensitive files (e.g. `bip39.txt` if present)
