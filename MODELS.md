## LLM & Model Priorities

This is the quick reference for which models we use where, and in what order. Treat this as the single source of truth for model choices.

---

### 1. Pipeline (heavy analysis)

**Use for:** podcast transcript analysis, Deep Dives, Emerging Terms, Overton auto‑curation.

- **Primary:** `gpt-5.5`
  - Provider: OpenAI (`OPENAI_API_KEY`). Not mini. Not Flash. Not Kimi.
  - Used in: `analyze_transcript.py`, `generate_deepdives.py`.
  - Override via `OPENAI_MODEL` or `OPENAI_DEBATE_MODEL`.
  - gpt-5.5 rejects `max_tokens` and non-default temperature; `openai_chat_kwargs()` sends `max_completion_tokens` and omits temperature.
  - Transcript window: `TRANSCRIPT_WINDOW_CHARS` = 100000 characters of the raw transcript (start/middle/end sample only if longer). Do not use the 12000-character slice or the Stage A mini digest for insight recaps.

- **Do not call:** Moonshot/Kimi (`kimi-k2.6` and the rest). The account is suspended (429, insufficient balance). Default client selection skips it. `ANALYZE_BACKEND=moonshot` still exists for an explicit override and is not the pipeline default.

- **Not used for this path:** `gpt-4o-mini`, `gemini-1.5-flash`, `gemini-2.5-flash`.

**Do NOT use (deprecated/retired):**

- `moonshot-v1-8k` (retired 2026-08-31, returns 404)
- `moonshot-v1-32k` (retired 2026-08-31)
- `moonshot-v1-128k` (retired 2026-08-31)
- `openai/codex-mini-latest`
- `kimi-coding/kimi-k2-thinking`

**Moonshot/Kimi:** suspended. Do not put these first in `resolve_llm_model` and do not call them from the insight or deep-dive generators.

---

### 2. Transcription

**Use for:** turning audio into text before analysis.

- **Default (queue/worker path):**
  - `fetch_latest.py` → `whisper_worker.sh` (configured separately).
  - Model is configured in the worker; prefer small Whisper/OpenAI or faster‑whisper models for cost.

- **Local helpers (manual / debugging):**
  - `transcribe_local.py` → `openai-whisper` (CLI) with `model=base` by default.
  - `transcribe_faster_whisper.py` → `faster-whisper` with default `base` model; can override via CLI.

---

### 3. Overton & Emerging Terms

**Use for:** extracting and curating terminology.

- Extraction from episodes: same OpenAI model as pipeline analysis (`gpt-5.5`).
- Auto‑curation thresholds live in `auto_curate_terms.py`:
  - `MIN_RELEVANCE_AUTO`, `MIN_SOURCES_AUTO`, `MIN_MENTIONS_AUTO`, `PROMOTE_MENTIONS_THRESHOLD`.

Sorting on the front page uses these scores; Overton will get a 30‑day half‑life decay based on `last_mentioned_date`.

---

### 4. Chat / Assistants

**Cursor (this assistant):**

- Optimized for: code, pipeline wiring, local tools, docs/HEARTBEAT-style status notes where you keep them.
- Treat Cursor as the place to design pipeline changes before they land in git.

**Other assistants / bots (outside this repo):** model choice belongs in whichever host configures them; keep outbound heartbeats cheap (read lightweight JSON/state) and invoke `auto_pipeline.py` only when data is stale or blocked.

---

### 5. Cost Guardrails (summary)

- Heavy cost = long‑context LLM calls (transcripts, Deep Dives, term curation), not chats.
- Don't run `auto_pipeline.py` on every chat; keep it on:
  - Scheduled jobs (midnight, 4am, 7am, 10pm), and
  - Explicit commands when something is clearly stale/broken.
- Heartbeats:
  - Read `status.json` / `pipeline_state.json`.
  - Only trigger `auto_pipeline.py` when `last_pipeline_run` is past the configured threshold.
  - Notify Jared only on `blocked_*` states or stuck episodes, not on normal in‑flight work.
