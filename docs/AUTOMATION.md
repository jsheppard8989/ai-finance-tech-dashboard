# Pipeline automation: 10pm run and sleep reliability

This doc explains how the 10pm pipeline is scheduled, why **sleep can prevent it from running**, and how to make it reliable.

---

## The problem: launchd only runs when the Mac is awake

Your pipeline can be triggered by **launchd** (`com.scarcity.pipeline.schedule.plist`) with:

- **StartCalendarInterval:** 22:00 (10pm) and 05:00 (5am)

**Important:** StartCalendarInterval runs only when the Mac is **already awake** at that time. If the Mac is asleep at 10pm, the job **does not run** when it wakes later. So “computer set to not fall asleep” (or falling asleep anyway) is exactly the right concern.

---

## What we did to harden automation

1. **Last-run marker**  
   After a successful run, `auto_pipeline.py` writes the date/time to  
   `pipeline/state/last_evening_run.txt`.  
   That lets “catch-up” logic know whether today’s run already happened.

2. **Wrapper script with caffeinate**  
   `pipeline/run_evening_pipeline.sh` runs the pipeline under **caffeinate -s -i -t 7200** (2 hours).  
   - **-s** = prevent **system** sleep  
   - **-i** = prevent **idle** sleep  
   So once the job starts, the Mac won’t sleep until the pipeline finishes or the timeout is hit.

3. **Catch-up on wake**  
   `pipeline/run_evening_catchup.sh` checks:  
   - Is it **after 10pm**?  
   - Has **today’s** run already been recorded in `last_evening_run.txt`?  
   If it’s after 10pm and we haven’t run today, it runs the evening pipeline.  
   When this script is run by a LaunchAgent with **RunAtLoad = true**, it runs every time you **log in** (or the Mac wakes and your session is active). So if the Mac was asleep at 10pm but you open the laptop at 11pm, the next login/wake can trigger the missed run.

4. **Updated plists**  
   - **Schedule plist** calls the wrapper script and sets **EnvironmentVariables** (PATH, HOME) so the job has a good environment.  
   - **Catch-up plist** runs at load and runs the catch-up script.

---

## Recommended: wake the Mac before 10pm

So that the **scheduled** 10pm fire always runs (and not only when you happen to log in later):

**Option A — Prevent sleep when plugged in (simplest)**  
If the Mac is on a power adapter at 10pm: **System Settings → Battery → Options** → enable **“Prevent automatic sleeping when the display is off”** (or equivalent) while on power adapter. Then the Mac often won’t sleep when plugged in, and the 10pm job will run without a wake schedule.

**Option B — Schedule a daily wake (Terminal)**  
Apple removed the wake schedule from System Settings in Ventura/Sonoma. Use Terminal:

1. **Check current schedule:**  
   `pmset -g sched`

2. **Set daily wake at 9:50 PM:**  
   `sudo pmset repeat wake MTWRFSU 21:50:00`  
   (MTWRFSU = every day; 21:50 = 9:50 PM)

3. **Confirm:**  
   `pmset -g sched`

4. **To remove later:**  
   `sudo pmset repeat cancel`

You can only have one repeat schedule; this overwrites any existing one.

---

## Install / update the LaunchAgents

Plist files live in the repo at **`docs/launchd/`** so you can version them. Copy into `~/Library/LaunchAgents` and load. They embed **absolute** paths to the pipeline scripts and log files — if your clone is not `/Users/jaredsheppard/projects/ai-finance-tech-dashboard`, search-replace in the plist **before** copying, or regenerate paths to match **`$WORKSPACE_ROOT`** on disk.

**Duplicate jobs:** If you ever installed an older copy of these plists under a different **Label**, check `launchctl list | grep pipeline` and `sudo launchctl list | grep pipeline` and **unload** any stale schedule/catch-up/daemon you no longer want so the evening pipeline is not started twice.

All supported jobs run from this repository as standard user LaunchAgents. They do not require an agent workspace or a system LaunchDaemon.

### 1. Scheduled 10pm (and 5am) run

Copy the plist into your LaunchAgents and load it:

```bash
cp $WORKSPACE_ROOT/docs/launchd/com.scarcity.pipeline.schedule.plist \
   ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.scarcity.pipeline.schedule.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.scarcity.pipeline.schedule.plist
```

### 2. Catch-up on login/wake (optional but recommended)

```bash
cp $WORKSPACE_ROOT/docs/launchd/com.scarcity.pipeline.catchup.plist \
   ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.scarcity.pipeline.catchup.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.scarcity.pipeline.catchup.plist
```

### 3. Interval fallback LaunchAgent

The interval runner executes `pipeline/run_if_scheduled.sh` every **45 minutes**. That script checks the configured run windows and the 90-minute cooldown before starting the evening pipeline.

```bash
$WORKSPACE_ROOT/scripts/reload_pipeline_daemon.sh
```

Verify: `launchctl list | grep scarcity.pipeline.daemon`

**Heartbeat:** The daemon writes the current time to `pipeline/state/daemon_last_check.txt` every run. If that file's timestamp is recent (within the last few minutes), the daemon is firing. Success marker for the pipeline itself is still `pipeline/state/last_evening_run.txt`.

The interval runner runs as your user so it sees your HOME and `.env`; logs remain in `pipeline/logs/`.

### 4. Local Whisper worker

```bash
cp $WORKSPACE_ROOT/docs/launchd/com.scarcity.whisper-worker.plist \
   ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.scarcity.whisper-worker.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.scarcity.whisper-worker.plist
```

The worker reads `$WORKSPACE_ROOT/whisper_queue/`, writes `$WORKSPACE_ROOT/whisper_done/`, and logs to `$WORKSPACE_ROOT/whisper_worker.log`.

---

## Verify it’s working

1. **After a run:**
   `cat $WORKSPACE_ROOT/pipeline/state/last_evening_run.txt`
   should show today’s date and time (e.g. `2026-03-07 22:45`).

2. **Daemon heartbeat (is the daemon firing?):**
   `cat $WORKSPACE_ROOT/pipeline/state/daemon_last_check.txt`
   should show a timestamp from the last few minutes if the daemon is running.

3. **Logs:**
   - stdout: `$WORKSPACE_ROOT/pipeline/logs/pipeline_schedule.out`
   - stderr: `$WORKSPACE_ROOT/pipeline/logs/pipeline_schedule.err`

4. **LaunchAgent status:**
   `launchctl list | grep scarcity.pipeline`
   You should see `com.scarcity.pipeline.schedule` and, if installed, `com.scarcity.pipeline.catchup`.

5. **Interval runner status:**
   `launchctl list | grep scarcity.pipeline.daemon`

6. **Manual test (without waiting for 10pm):**
   `$WORKSPACE_ROOT/pipeline/run_evening_pipeline.sh`
   Then check `last_evening_run.txt` and the logs.

---

## Summary

| Risk | Mitigation |
|------|------------|
| Mac asleep at 10pm | **Schedule wake at 9:50pm** (Energy Saver → Schedule). |
| Mac sleeps during run | **Wrapper uses caffeinate -s -i** for up to 2 hours. |
| Missed 10pm (e.g. slept through) | **Catch-up LaunchAgent** runs on login/wake; if it’s after 10pm and we haven’t run today, it runs the pipeline. |
| Wrong env in launchd | **EnvironmentVariables** (PATH, HOME) set in the schedule plist. |

The pipeline still runs **on this Mac**. If the Mac is off or never wakes, nothing runs. For “runs even when the Mac is off,” you’d need the pipeline (or a trigger) on another always-on machine or in the cloud (e.g. GitHub Actions, VPS); that’s a larger change.
