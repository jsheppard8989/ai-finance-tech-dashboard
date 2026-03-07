# Refactor: Openclaw vs Website Separation

## Current state

Everything lives in one repo under `~/.openclaw/workspace`:

| Category | Paths | Purpose |
|----------|--------|---------|
| **Openclaw (agent)** | `AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `MEMORY.md`, `HEARTBEAT.md`, `TOOLS.md`, `memory/`, `.env` | Agent identity, memory, rules, secrets |
| **Website (product)** | `site/` (HTML, JS, `data/`, `charts/`, `price_data.json`) | Static dashboard and generated assets |
| **Pipeline (feeds website)** | `pipeline/*.py`, `pipeline/dashboard.db`, `pipeline/transcripts/`, `pipeline/state/`, etc. | Fetch → transcribe → analyze → export into `site/` |
| **Shared / ambiguous** | `audio/`, `whisper_queue/`, `whisper_done/`, `podcast_feeds.txt`, `scripts/`, `pushover.sh`, `send_imessage.sh` | Used by pipeline but live at workspace root |

Coupling:

- Pipeline scripts **hardcode** `~/.openclaw/workspace/site` (and sometimes the full workspace path). No env or config.
- Export writes: `site/data/data.js`, `site/data/*.json`, `site/price_data.json`, `site/charts/*.png`; `auto_pipeline.py` also edits `site/index.html` (cache-buster).
- Deploy workflow and README assume `site/` at repo root.
- `scripts/update_recent_posts.py` assumes cwd is workspace and uses `site/index.html`.

So the “website program” is the pipeline + `site/`, and it’s comingled with Openclaw agent files in the same tree.

---

## Security: What’s currently on GitHub?

**Is Openclaw data public?**  
**Yes.** The repo `jsheppard8989/ai-finance-tech-dashboard` is **public**, and the following are **tracked and committed** (so they are on GitHub):

- **Openclaw agent files:** `AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `MEMORY.md`, `HEARTBEAT.md`, `TOOLS.md`
- **Daily memory:** `memory/2026-02-01-1956.md`, `memory/2026-02-14.md`, `memory/2026-02-16.md`, `memory/2026-02-19.md`, `memory/2026-02-22.md`, etc.
- **Sensitive:** `bip39.txt`, `pending_contacts.json`
- **Pipeline state/logs:** `pipeline/state/curation_log.json`, `fetch_log.json`, `pending_approval.json`, `votes.json`, `pipeline/inbox/*.json`, etc.

`.env` and `audio/` are in `.gitignore` and are **not** committed. Everything in the list above **is** in git history.

**Is that a security issue?**  
**Yes.**

- **Privacy:** MEMORY.md, USER.md, SOUL.md, and `memory/*.md` describe you, who the agent helps, and ongoing context. That’s private context you may not want public.
- **Critical risk:** If `bip39.txt` contains a real BIP39 mnemonic (recovery phrase), anyone with the repo can derive wallet keys and move funds. Treat it as **compromised if the repo was ever public**; move assets and use a new wallet/mnemonic.
- **Other:** TOOLS.md (e.g. Pushover/WhatsApp notes), contact form data in `pending_contacts.json`, and pipeline state may be semi-sensitive.

---

## Refactor options (easiest → more work)

### Option 1: Configurable site path (low effort, keeps one repo)

**Goal:** Single source of truth for “where the website lives” so you can later move it without hunting through the codebase.

**Steps:**

1. **Add a single config for paths**  
   In `pipeline/` (e.g. `pipeline/config.py` or read from `.env`):
   - `WORKSPACE_ROOT = Path(os.environ.get("OPENCLAW_WORKSPACE", str(Path.home() / ".openclaw/workspace")))`
   - `SITE_DIR = Path(os.environ.get("SITE_DIR", str(WORKSPACE_ROOT / "site")))`

2. **Replace every pipeline path that touches the site**  
   Use `SITE_DIR` (or `SITE_DIR / "data"`, `SITE_DIR / "charts"`, etc.) instead of `Path.home() / ".openclaw/workspace/site/..."`.  
   Files to update:
   - `export_data.py` — `site_dir` → from config
   - `fetch_prices.py` — `PRICE_FILE`, `ticker_scores_file` → under `SITE_DIR`
   - `generate_charts.py` — `CHARTS_DIR`, `price_file` → under `SITE_DIR`
   - `pipeline_tracker.py` — `data_js` path → under `SITE_DIR`
   - `auto_pipeline.py` — `WORKSPACE` and any `site/` reference (index.html cache-buster) → use `SITE_DIR`
   - `run_pipeline.py` — same idea if it still writes to site

3. **Optional:** In workspace root `.env`, add:
   - `SITE_DIR=/path/to/your/site`  
   so you can point at a different directory (or another repo) without changing code.

4. **Scripts:** `scripts/update_recent_posts.py` — resolve `INDEX_FILE` from the same config (e.g. `SITE_DIR / "index.html"`) or from `SITE_DIR` env so it still works if you move the site.

**Result:** Openclaw and website still live in one repo, but the “website” output is no longer hardcoded. You can move `site/` elsewhere and set `SITE_DIR` (and run pipeline from workspace) and keep everything working. No folder moves required to stay working today.

**Difficulty:** Low. Mostly find-and-replace plus one small config and env.

---

### Option 2: Same repo, put website under one folder (medium effort)

**Goal:** Clear separation: “Openclaw stuff at root, website + pipeline under one tree.”

**Steps:**

1. **Create a website tree:**
   - `website/site/` — move current `site/` here (HTML, JS, data, charts).
   - `website/pipeline/` — move current `pipeline/` here (code, DB, state, transcripts, etc.).

2. **Paths:**
   - In `website/pipeline/`, introduce e.g. `config.py`:
     - `WORKSPACE_ROOT = Path(__file__).resolve().parents[2]` (workspace root)
     - `SITE_DIR = WORKSPACE_ROOT / "website" / "site"`
     - `AUDIO_DIR = WORKSPACE_ROOT / "audio"`, `TRANSCRIPT_DIR = WORKSPACE_ROOT / "website" / "pipeline" / "transcripts", etc.
   - Replace all hardcoded `~/.openclaw/workspace/...` in pipeline with these (workspace root for audio, whisper_*, podcast_feeds; `website/pipeline` for DB/state/transcripts; `SITE_DIR` for any site output).

3. **Cron / entrypoints:** Run from workspace root, e.g. `python3 website/pipeline/auto_pipeline.py`. Any scripts that assume `pipeline/` as cwd must use the new path or be invoked from workspace with the right cwd.

4. **Deploy:** In `.github/workflows/deploy.yml`, change to copy `website/site/**` instead of `site/**` (and adjust `paths:` if you use path filters).

5. **Docs:** Update README, WORKSPACE_LAYOUT.md, MEMORY.md, HEARTBEAT.md to say “website lives under `website/`”.

6. **Scripts:** `scripts/update_recent_posts.py` — use `workspace/website/site/index.html` (or from config).

**Result:** Root contains only Openclaw agent files, memory, `.env`, and shared data (audio, whisper_*, podcast_feeds). Everything that is “the website program” is under `website/`. Pipeline still uses workspace root for audio and feeds; site output is under `website/site/`.

**Difficulty:** Medium. More moves and path updates; need to run pipeline from workspace or adjust cwd.

---

### Option 3: Two repos (higher effort)

**Goal:** One repo for Openclaw (agent + optional “runner” that invokes the pipeline), one repo for the website + pipeline.

**Steps:**

1. **New repo (e.g. `scarcity-abundance-site`):** Contains `site/` and `pipeline/` (or `website/site` and `website/pipeline`). Pipeline’s config assumes:
   - “Workspace” for pipeline = this repo’s root (or a subfolder).
   - “Site” = `site/` inside this repo.
   - No dependency on `~/.openclaw/workspace` for site output.

2. **Openclaw workspace:** Keeps agent files, memory, `.env`. It can:
   - Clone the website repo into e.g. `~/projects/scarcity-abundance-site` and run the pipeline there (pipeline writes into that repo’s `site/`), or
   - Have a small script that runs the pipeline in the other repo (e.g. `cd ~/projects/scarcity-abundance-site && python3 pipeline/auto_pipeline.py`).

3. **Pipeline in the website repo:** Must get “input” data from somewhere:
   - Either the pipeline is fully self-contained (fetches, transcribes, DB, everything inside the website repo), and only “notification” or “trigger” lives in Openclaw, or
   - Pipeline reads shared resources (e.g. `audio/`, `whisper_done/`, `podcast_feeds.txt`) from a configured path (e.g. `OPENCLAW_WORKSPACE`) and writes only to the website repo’s `site/`.

4. **Deploy:** From the website repo only (e.g. GitHub Actions there deploying `site/` or `website/site/`).

**Result:** Clean split: Openclaw repo = agent; website repo = product + pipeline. More moving parts (two repos, possibly shared dirs or env for audio/feeds).

**Difficulty:** Higher. Two repos, clear contract for shared paths (if any), and cron/automation must run the correct repo from the correct place.

---

## Recommendation

- **Do Option 1 first.** Small, safe change; everything keeps working; you get a single place (config + env) for “where is the site.” No need to move folders or repos.
- **If you want a clearer tree in the same repo,** do Option 2 after Option 1 (reuse the same `SITE_DIR` / config idea so pipeline stays path-agnostic).
- **Only do Option 3** if you really want separate repos (e.g. different access, separate deploys, or reuse of the dashboard in another context).

---

## Files that need path updates (for Option 1 or 2)

| File | Current usage |
|------|----------------|
| `pipeline/export_data.py` | `site_dir = Path.home() / ".openclaw/workspace/site/data"` |
| `pipeline/fetch_prices.py` | `PRICE_FILE`, `ticker_scores_file` under workspace/site |
| `pipeline/generate_charts.py` | `CHARTS_DIR`, `price_file` under workspace/site |
| `pipeline/auto_pipeline.py` | `WORKSPACE`, edits `site/index.html` |
| `pipeline/run_pipeline.py` | `site_dir` (if still used) |
| `pipeline/pipeline_tracker.py` | `data_js` path under site |
| `pipeline/db_manager.py` | `DB_PATH` (only if moving pipeline in Option 2) |
| `pipeline/fetch_latest.py` | AUDIO_DIR, TRANSCRIPT_DIR, etc. (workspace paths) |
| … (other pipeline scripts) | Any `Path.home() / ".openclaw/workspace/..."` |
| `scripts/update_recent_posts.py` | `INDEX_FILE = 'site/index.html'` |
| `.github/workflows/deploy.yml` | `site/**` → optionally `website/site/**` |

Once a single `WORKSPACE_ROOT` and `SITE_DIR` (and optionally `PIPELINE_DIR`) are defined and used everywhere, further moves (Option 2 or 3) are mostly file moves and updating that one config.

---

## Recommendation given security

Because **Openclaw and sensitive data are already in a public repo**, the priority is to **stop exposing that data** and **keep only website-safe content** in the public repo.

**Recommended: Option 3 (two repos), with immediate cleanup.**

1. **Immediate (this repo, before any refactor):**
   - Add to `.gitignore`: `AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `MEMORY.md`, `HEARTBEAT.md`, `TOOLS.md`, `memory/`, `bip39.txt`, `pending_contacts.json`. Optionally ignore `pipeline/state/*.json`, `pipeline/inbox/` if you don’t want them in the public repo.
   - Run `git rm --cached` on those paths so they stop being tracked (files stay on disk).
   - **If `bip39.txt` is a real mnemonic:** Assume it was exposed; move funds to a new wallet and never use that phrase again.
   - To remove the files from **all history** (so they’re not in clones/forks): use [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) or `git filter-repo` to strip those paths from history, then force-push. Only do this if you’re comfortable rewriting history and coordinating with any collaborators.

2. **Structural fix: Option 3 — two repos.**
   - **Public repo (e.g. `ai-finance-tech-dashboard`):** Contains only what’s needed for the site and its pipeline: `site/`, `pipeline/` (code + schema + requirements), `.github/workflows/deploy.yml`, README for the dashboard. No AGENTS.md, no MEMORY.md, no USER.md, no `memory/`, no `bip39.txt`, no `pending_contacts.json`. Pipeline in this repo can write to `site/` from local runs or CI; if it needs a DB or secrets, use env vars or GitHub Secrets and never commit them.
   - **Openclaw workspace (private or local-only):** Stays at `~/.openclaw/workspace` with AGENTS.md, SOUL.md, USER.md, MEMORY.md, memory/, .env, etc. Either:
     - **A)** No git, or a **private** repo that you don’t push to the same GitHub account’s public Pages repo, or  
     - **B)** A small “runner” that clones or pulls the public website repo, runs the pipeline (with DB/secrets from the Openclaw env), and pushes only the generated `site/` (or triggers the public repo’s deploy).  
   That way Openclaw data **never** lives in a public repo.

3. **If you want to keep a single repo for now:**  
   Make the repo **private** (Settings → General → Danger Zone → Change visibility). Then you can do Option 1 or 2 later without exposing Openclaw. GitHub Pages can still work with a private repo (with possible restrictions depending on plan).

**Summary:** Yes, Openclaw data is currently public; yes, that’s a security/privacy issue (and critical if bip39 is real). Recommend Option 3 plus immediate .gitignore and `git rm --cached` (and history cleanup + bip39 rotation if applicable).

**Exact steps:** See **REFACTOR_OPENCLAW_STEPS.md** for the full .gitignore block and `git rm --cached` commands. Run **scripts/untrack_sensitive.sh** to untrack in one go (then commit and push).
