# dragonfly/ops — launchd TEMPLATES (not installed)

Nothing here is installed or loaded. These are templates for the Mac. Ditka runs
a dry run first (docs/dragonfly/ENGINE.md, "Dry run"); schedules go on only
after that and Jared's approval.

| File | Purpose |
| --- | --- |
| `com.dragonfly.engine.plist.template` | LaunchAgent: 08:08 CT Mon–Fri, runs the wrapper. `RunAtLoad` false. |
| `run_engine.sh.template` | Wrapper: weekday + 08:00–08:24 guard, then `/usr/bin/python3 -m dragonfly.engine run` (the engine itself idles, exit 0, on NYSE holidays). |

Placeholders: `__REPO__` (the Mac checkout of this repo), `__HOME__`.
Installed copies belong under `dragonfly/state/live/ops/` (gitignored), logs
under `dragonfly/state/live/logs/`.

The READY marker is not scheduled here: it is the last command of the 08:05
pre-open job (`python3 -m dragonfly.engine ready`), which is built separately.
