# dragonfly/ops — launchd TEMPLATES (not installed)

Nothing here is installed or loaded. These are templates for the Mac. Ditka
gives an explicit go (after the dry run, docs/dragonfly/ENGINE.md "Dry run")
and Jared approves before anything loads.

| File | Purpose |
| --- | --- |
| `com.dragonfly.prep.plist.template` | LaunchAgent: 15:30 CT Mon–Fri, runs `run_prep.sh`. `RunAtLoad` false. |
| `run_prep.sh.template` | Wrapper: refuses the pipeline checkout, weekday + 15:25–18:00 wake guard, `git pull --ff-only` of the run clone, then `/usr/bin/python3 -m dragonfly.jobs prep` (targets the next NYSE session). |
| `com.dragonfly.preopen.plist.template` | LaunchAgent: 08:05 CT Mon–Fri, runs `run_preopen.sh`. `RunAtLoad` false. |
| `run_preopen.sh.template` | Wrapper: same checks, 08:00–08:15 wake guard, then `/usr/bin/python3 -m dragonfly.jobs preopen` (READY is its last step; exits 0 on NYSE holidays). |
| `com.dragonfly.engine.plist.template` | LaunchAgent: 08:08 CT Mon–Fri, runs `run_engine.sh`. `RunAtLoad` false. |
| `run_engine.sh.template` | Wrapper: weekday + 08:00–08:24 guard, then `/usr/bin/python3 -m dragonfly.engine run` (the engine itself idles, exit 0, on NYSE holidays). |

## Where it runs: the run clone

Never the pipeline checkout `~/projects/ai-finance-tech-dashboard` (the site
daemon autostashes and pulls it). Placeholders:

- `__REPO__` = `~/projects/dragonfly-run`, a separate clone of this repo on
  `main`. The prep/pre-open wrappers fast-forward it (`git pull --ff-only
  origin main`) at job start and abort if that fails.
- `__HOME__` = the user's home directory.
- dragonfly-private checkout: `__HOME__/projects/dragonfly-private`
  (`DRAGONFLY_PRIVATE_DIR`), pushed with the Mac's own git credentials.
- Live book: `__REPO__/dragonfly/state/live/book.json` (gitignored;
  override `--book` / `DRAGONFLY_BOOK`).

Installed copies belong under `__REPO__/dragonfly/state/live/ops/`
(gitignored), logs under `__REPO__/dragonfly/state/live/logs/`. The
templates set `DRAGONFLY_PIPELINE_LOCK` to the pipeline's two lock files so
the load guards still see a running pipeline (read only).
