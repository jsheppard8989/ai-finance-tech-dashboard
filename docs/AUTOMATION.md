# Pipeline automation: 10pm run and sleep reliability

This doc explains how the 10pm pipeline is scheduled, why **sleep can prevent it from running**, and how to make it reliable.

---

## The problem: launchd only runs when the Mac is awake

Your pipeline is triggered by **launchd** (`com.openclaw.pipeline.schedule.plist`) with:

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

Plist files live in the repo at **`docs/launchd/`** so you can version them. Copy into `~/Library/LaunchAgents` and load.

If you always have to log in with Touch ID when you sit down, the session is locking and LaunchAgents may not run when locked. Use section 3 (LaunchDaemon) so the job runs anyway.

### 1. Scheduled 10pm (and 5am) run

Copy the plist into your LaunchAgents and load it:

```bash
cp /Users/jaredsheppard/.openclaw/workspace/docs/launchd/com.openclaw.pipeline.schedule.plist \
   ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.openclaw.pipeline.schedule.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.openclaw.pipeline.schedule.plist
```

### 2. Catch-up on login/wake (optional but recommended)

```bash
cp /Users/jaredsheppard/.openclaw/workspace/docs/launchd/com.openclaw.pipeline.catchup.plist \
   ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.openclaw.pipeline.catchup.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.openclaw.pipeline.catchup.plist
```

### 3. Use LaunchDaemon (runs when screen is locked)

If you have to log in with Touch ID every time you sit down, the Mac is locking when you walk away. **LaunchAgents** (user-level) may not run when the screen is locked. Use a **LaunchDaemon** so the 10pm job runs at system level—**unaffected by lock or login**.

1. Unload the user LaunchAgent (so you don’t run twice):
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.openclaw.pipeline.schedule.plist
   ```
2. Install the daemon (requires admin password):
   ```bash
   sudo cp /Users/jaredsheppard/.openclaw/workspace/docs/launchd/com.openclaw.pipeline.daemon.plist /Library/LaunchDaemons/
   sudo chown root:wheel /Library/LaunchDaemons/com.openclaw.pipeline.daemon.plist
   sudo chmod 644 /Library/LaunchDaemons/com.openclaw.pipeline.daemon.plist
   sudo launchctl load /Library/LaunchDaemons/com.openclaw.pipeline.daemon.plist
   ```
3. Verify: `sudo launchctl list | grep openclaw.pipeline.daemon`

The daemon runs as your user so it sees your HOME and `.env`; same logs in `pipeline/logs/`.

---

## Verify it’s working

1. **After a run:**  
   `cat ~/.openclaw/workspace/pipeline/state/last_evening_run.txt`  
   should show today’s date and time (e.g. `2026-03-07 22:45`).

2. **Logs:**  
   - stdout: `~/.openclaw/workspace/pipeline/logs/pipeline_schedule.out`  
   - stderr: `~/.openclaw/workspace/pipeline/logs/pipeline_schedule.err`

3. **LaunchAgent status:**  
   `launchctl list | grep openclaw`  
   You should see `com.openclaw.pipeline.schedule` and, if installed, `com.openclaw.pipeline.catchup`.

4. **Manual test (without waiting for 10pm):**  
   `~/.openclaw/workspace/pipeline/run_evening_pipeline.sh`  
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
