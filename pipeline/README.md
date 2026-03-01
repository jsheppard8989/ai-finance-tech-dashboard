# Newsletter Analysis Pipeline

This directory contains the data pipeline for ingesting newsletters and extracting stock insights.

## Directory Structure

```
pipeline/
├── inbox/         # New emails (processed JSON format)
├── processed/     # Original .eml files (after processing)
├── extracted/     # Structured data extracted from emails
├── analysis/      # Analysis results and stock picks
├── ingest.py      # Email ingestion script (Gmail IMAP)
└── analyze.py     # Stock analysis and scoring
```

## Setup

1. **Forward newsletters** to jsheppard8989@gmail.com
2. **Enable IMAP** in Gmail settings (Settings → Forwarding and POP/IMAP → IMAP Access)
3. **Allow less secure apps** OR use App Password if 2FA enabled

## Usage

### Fetch New Emails
```bash
cd ~/.openclaw/workspace/pipeline
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
0 8 * * * cd ~/.openclaw/workspace/pipeline && python3 ingest.py && python3 analyze.py
```

Or use OpenClaw's cron system to schedule runs.

## Podcast transcription (local, stable on macOS)

**Recommended:** Use **openai-whisper** (PyTorch). It’s stable on macOS; faster-whisper can crash (SIGABRT).

1. **Install:** `pip install openai-whisper`
2. **Transcribe all audio in pipeline:**  
   `python3 transcribe_local.py`
3. **Single file:**  
   `python3 transcribe_local.py /path/to/episode.mp3`
4. **Use from fetch_latest (in-process, no LaunchAgent):**  
   `USE_FASTER_WHISPER=1 python3 fetch_latest.py`

First run downloads the model to `~/.cache/whisper/`. Use `--model small` or `--model medium` in the script for better quality.

**Note:** `transcribe_faster_whisper.py` is available for a faster engine but may crash on some Macs; use `transcribe_local.py` if you see SIGABRT.

## Publishing transcripts from whisper_done

When the LaunchAgent (or another process) writes transcripts to `workspace/whisper_done/`, sweep them into the pipeline and refresh the site:

```bash
cd ~/.openclaw/workspace/pipeline
python3 sweep_whisper_done_and_publish.py
```

This copies any new `.txt` and `.meta.json` from `whisper_done/` to `pipeline/transcripts/`, then runs analyze → promote → scores → prices → charts → export (same as `auto_pipeline.py --analyze-only`). The site’s `site/data/data.js` will include the new episode and insights.

**Manual steps** (if you prefer):

1. Copy (or move) files:  
   `cp workspace/whisper_done/ALLIN-E262_Ch_1.txt workspace/whisper_done/ALLIN-E262_Ch_1.meta.json pipeline/transcripts/`
2. Analyze:  
   `python3 analyze_transcript.py`
3. Export site:  
   `python3 auto_pipeline.py --analyze-only`  
   (or run only the export step from `run_pipeline.py` / `auto_pipeline.py` as needed.)
