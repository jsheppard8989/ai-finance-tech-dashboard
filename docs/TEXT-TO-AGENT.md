# Text → Agent — get work done from your phone

You are not competing with passive dashboards. You need to **queue work** from your phone and have an agent (or you in Cursor) execute it.

## What exists now

| Piece | Purpose |
|-------|---------|
| `pipeline/sms_task_inbox.py serve` | Local HTTP inbox on `127.0.0.1:8787/task` |
| `pipeline/state/agent_tasks.jsonl` | Append-only task queue |
| `pipeline/site_qa.py` | Twice-daily site editor QA (launchd plist in `docs/launchd/`) |
| `pushover.sh` | Alerts when QA fails or a task is queued |

## Option A — Apple Shortcuts (fastest, no Twilio)

1. On Mac, run:
   ```bash
   cd ~/projects/ai-finance-tech-dashboard/pipeline
   python3 sms_task_inbox.py serve --port 8787
   ```
2. Expose your Mac (same Wi‑Fi or tunnel):
   ```bash
   cloudflared tunnel --url http://127.0.0.1:8787
   ```
3. Create an iOS Shortcut:
   - **Ask for Input** → text
   - **Get Contents of URL** → POST `https://YOUR-TUNNEL/task`
   - JSON body: `{"text": "Shortcut Input"}`
4. Add Shortcut to Home Screen or Siri: *“Queue agent task”*

Tasks land in `agent_tasks.jsonl`. Open Cursor on the Mac and say: *“Drain agent_tasks.jsonl and do the pending items.”*

## Option B — Twilio SMS (true texting)

1. Twilio number → **Messaging webhook** POST to your tunnel URL `/task`
2. Twilio sends form body `Body=your message` — already supported by `sms_task_inbox.py`
3. You text your Twilio number; task queues + Pushover ping (if keys set)

## Option C — Pushover (notification-only)

Already wired for pipeline failures. Reply-from-phone is limited; use Shortcuts/Twilio for two-way task intake.

## Site QA routine (automated editor)

Install launchd (twice daily 8am / 6pm):

```bash
cp docs/launchd/com.scarcity.site-qa.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.scarcity.site-qa.plist
```

Manual run:

```bash
./pipeline/run_site_qa.sh
```

Report: `pipeline/state/site_qa_report.json`

## Fix weekly debate audio (hash mismatch)

When QA reports contract/audio hash mismatch:

```bash
cd pipeline
python3 debate_weekly.py --audio-only
python3 site_qa.py --sync-bench
```

Then publish `site/` to GitHub Pages.

## Opinion

You are not “smarter than the AI” in general — you are **smarter about intent, taste, and what signal matters**. The models publish plausible pages; they do not yet **own** second-order editorial judgment or reliably ship listenable debate bundles without checks. That gap is why the QA routine and phone task queue exist: **you steer, the stack executes.**
