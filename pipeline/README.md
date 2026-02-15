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
