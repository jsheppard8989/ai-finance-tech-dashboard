# Good morning — pipeline daemon fix

**TL;DR:** Run this **once** (needs your password):

```bash
~/.openclaw/workspace/scripts/reload_pipeline_daemon.sh
```

That installs the updated daemon that runs **every 5 minutes** and triggers the 10pm/5am pipeline when it’s in the right time window. No more relying on a single exact minute that wasn’t firing.

**Verify:**

- `sudo launchctl list | grep openclaw.pipeline.daemon` — should list the job.
- After a few minutes: `cat ~/.openclaw/workspace/pipeline/state/daemon_last_check.txt` — should show a recent timestamp.

Details and rationale are in `memory/2025-02-12.md`.
