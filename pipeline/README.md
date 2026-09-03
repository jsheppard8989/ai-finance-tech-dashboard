# Newsletter Analysis Pipeline

This directory contains the data pipeline for ingesting newsletters and extracting stock insights.

## Directory Structure

```
pipeline/
├── state/          # Logs and state (curation_log.json, pipeline_status.json, fetch_log.json, etc.)
├── transcripts/    # All transcript .txt and .meta.json files
├── processed/      # Per-transcript .processed markers
├── inbox/          # New emails (processed JSON format)
├── analysis/       # Analysis results and stock picks
├── dashboard.db    # SQLite database
├── ingest.py       # Email ingestion script (Gmail IMAP)
├── analyze_transcript.py, fetch_latest.py, auto_pipeline.py, ...
└── README.md       # This file
```

See also `WORKSPACE_LAYOUT.md` in the workspace root.

## Setup

1. **Forward newsletters** to jsheppard8989@gmail.com
2. **Enable IMAP** in Gmail settings (Settings → Forwarding and POP/IMAP → IMAP Access)
3. **Allow less secure apps** OR use App Password if 2FA enabled

## Usage

### Fetch New Emails
```bash
cd "$WORKSPACE_ROOT/pipeline"
python3 ingest.py
```

### Analyze and Get Top 5 Picks
```bash
python3 analyze.py
```

### View Results
```bash
cat analysis/top_picks.json
```

## Automation

Set up a cron job to run ingestion daily:
```bash
# Edit crontab
crontab -e

# Add line for daily run at 8am:
0 8 * * * cd "$WORKSPACE_ROOT/pipeline" && python3 ingest.py && python3 analyze.py
```

Schedule runs however you prefer (cron, launchd, or a scheduler UI). To push without interactive auth, set **GITHUB_PUSH_TOKEN** in `.env`.

## Scheduled data sources

The pipeline fetches market data as part of each `auto_pipeline.py` run:

| Script | Data | Source | Failure behavior |
|--------|------|--------|-----------------|
| `fetch_prices.py` | Ticker prices & 2-week changes | Yahoo Finance | Uses cached prices on failure |
| `fetch_gpu_index.py` | GPU rental pricing (H100 1Y contract) | SemiAnalysis GPU Index | Marks data stale, preserves last-known-good |

**GPU Index notes:**
- Source: `https://gpu-index.semianalysis.com/` (server-rendered HTML scrape, no auth)
- Free public data **lags several months** behind current date; the widget shows the as-of period
- Trend shows dual horizons: short-term (vs prior period) and long-term (~6 periods back)
- On fetch failure (network, timeout, page restructure): existing data preserved, marked `_stale: true`
- Tests: `python3 test_gpu_index_trend.py`

## Robust podcast transcription (queue + worker) — recommended

The approach that worked for the All-In episode: **transcription runs in a separate process** (queue + worker), so the main pipeline doesn’t hit OOM, timeouts, or SIGABRT.

1. **Run the worker** (outside restrictive sandboxes so Whisper can finish) so it’s always available:
   - Worker script: **`$WORKSPACE_ROOT/whisper_worker.sh`**
   - It watches **`$WORKSPACE_ROOT/whisper_queue/`**, runs Whisper (e.g. `$HOME/anaconda3/bin/whisper`), writes `.txt` + `.meta.json` to **`$WORKSPACE_ROOT/whisper_done/`**.
   - Run it as a **LaunchAgent** or in a dedicated terminal so it keeps processing the queue.
   - Ensure `whisper` is on your PATH (e.g. Anaconda: `conda install -c conda-forge openai-whisper`).

2. **Pipeline uses the queue by default.**  
   When you run `fetch_latest.py` (or the full pipeline), it:
   - Sweeps any completed files from `whisper_done/` into `pipeline/transcripts/`.
   - After a successful **site push** (`auto_pipeline` / `publish_site.py`), deletes episode **downloads only** (`workspace/audio/`, `pipeline/audio/`, `whisper_queue/`) when the episode is on the site (`added_to_site=1`), fully processed (`is_processed=1`), and the transcript file still exists — **`.txt` transcripts are kept.** Set `DISABLE_AUDIO_CLEANUP=1` to skip. Manual: `python3 fetch_latest.py --cleanup-published-audio`.
   - Downloads new episodes and **enqueues** them (copies audio + meta into `whisper_queue/`).
   - Either **waits** for the worker to finish (default), or **exits after enqueue** if you use enqueue-only (see below).

3. **Do not set `USE_FASTER_WHISPER=1`** unless you intentionally want in-process transcription (can OOM or timeout on long episodes).

### Enqueue-only (no wait)

To avoid the pipeline blocking on transcription (e.g. in cron or when the worker is slow):

```bash
USE_QUEUE_ONLY=1 python3 fetch_latest.py
```

or:

```bash
python3 fetch_latest.py --queue-only
```

This only downloads and enqueues; it does not wait for the worker. On the **next** pipeline run, `sweep_completed_transcripts()` will move any finished transcripts from `whisper_done/` into the pipeline, and they’ll be analyzed and published then.

### In-process fallback (can OOM/timeout)

Use only when the worker isn’t available. **openai-whisper** (PyTorch) is stable on macOS; faster-whisper can crash (SIGABRT).

- **Install:** `pip install openai-whisper`
- **Standalone:** `python3 transcribe_local.py` or `python3 transcribe_local.py /path/to/episode.mp3`
- **From fetch_latest:** `USE_FASTER_WHISPER=1 python3 fetch_latest.py`

First run downloads the model to `~/.cache/whisper/`. Use `--model small` or `--model medium` for better quality.

**Note:** `transcribe_faster_whisper.py` may crash on some Macs; use `transcribe_local.py` if you see SIGABRT.

## Publishing transcripts from whisper_done

When the LaunchAgent (or another process) writes transcripts to **`$WORKSPACE_ROOT/whisper_done/`**, sweep them into the pipeline and refresh the site:

```bash
cd "$WORKSPACE_ROOT/pipeline"
python3 sweep_whisper_done_and_publish.py
```

This copies any new `.txt` and `.meta.json` from `whisper_done/` to `pipeline/transcripts/`, then runs analyze → promote → scores → prices → charts → export (same as `auto_pipeline.py --analyze-only`). The site’s `site/data/data.js` will include the new episode and insights.

**Manual steps** (if you prefer):

1. Copy (or move) files:  
   `cp $WORKSPACE_ROOT/whisper_done/ALLIN-E262_Ch_1.txt $WORKSPACE_ROOT/whisper_done/ALLIN-E262_Ch_1.meta.json pipeline/transcripts/`
2. Analyze:  
   `python3 analyze_transcript.py`
3. Export site:  
   `python3 auto_pipeline.py --analyze-only`  
   (or run only the export step from `run_pipeline.py` / `auto_pipeline.py` as needed.)
