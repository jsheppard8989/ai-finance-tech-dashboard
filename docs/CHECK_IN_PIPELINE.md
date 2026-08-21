# Good morning — pipeline daemon fix

**TL;DR:** Run this **once** (needs your password):

```bash
$WORKSPACE_ROOT/scripts/reload_pipeline_daemon.sh
```

That installs the updated daemon that runs **every 5 minutes** and triggers the 10pm/5am pipeline when it’s in the right time window. No more relying on a single exact minute that wasn’t firing.

**Verify:**

- `sudo launchctl list | grep scarcity.pipeline.daemon` — should list the job.
- After a few minutes: `cat $WORKSPACE_ROOT/pipeline/state/daemon_last_check.txt` — should show a recent timestamp.

Details and rationale are in `memory/2025-02-12.md`.

---

## Pipeline health at a glance

To see how well episodes are being picked up, processed, and posted **without asking each time**:

- **On the site:** Open **Pipeline health** (link next to “Last updated” in the header) or go to `pipeline-health.html`. It shows last run time, step pass/fail, and key counts (episodes, insights, Overton terms, pundits).
- **Data sources:** `site/data/status.json` and `site/data/pipeline_state.json` (both updated on export). Local debug copy: `pipeline/state/last_run_report.json`.
