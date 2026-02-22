# HEARTBEAT.md

## ⏳ PENDING TASK: Pipeline Dry-Run Test

**What:** Run a dry-run test of `auto_pipeline.py` before tonight's 10pm cron run.
**When:** After Jared has been silent for 30 consecutive minutes (last message: 2:22pm CST Feb 22).
**Why:** We've been fixing the pipeline all day and need to verify it runs clean before 10pm.

**Track last-message timestamp:** 2026-02-22 14:49 CST

### On each heartbeat:
1. Check if it has been 30+ minutes since 14:22 CST (or since Jared's last message if he messages again)
2. If YES and dry-run not yet done → run it (see instructions below)
3. If NO → HEARTBEAT_OK

### Dry-run instructions (no AI calls, no DB writes):
```bash
cd ~/.openclaw/workspace/pipeline

# 1. Syntax check
python3 -m py_compile auto_pipeline.py analyze_transcript.py fetch_latest.py curate.py export_data.py db_manager.py && echo 'Syntax OK'

# 2. DB connection
python3 -c "from db_manager import get_db; db=get_db(); print(db.get_stats())"

# 3. RSS feeds reachable
python3 -c "
import urllib.request
feeds = open('../podcast_feeds.txt').read().splitlines()
feeds = [f for f in feeds if f.strip() and not f.startswith('#')]
for url in set(feeds):
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=10)
        print('OK:', url[:60])
    except Exception as e:
        print('FAIL:', url[:60], str(e))
"

# 4. Export test
python3 export_data.py

# 5. Import check
python3 -c "import auto_pipeline; print('imports OK')"
```

Report PASS/FAIL for each step. Fix syntax errors if found. Do NOT run full pipeline or make AI calls.

**Clear this task once done** (delete or empty this file).
