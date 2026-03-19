## LLM & Model Priorities

This is the quick reference for which models we use where, and in what order. Treat this as the single source of truth for model choices.

---

### 1. Pipeline (heavy analysis)

**Use for:** podcast transcript analysis, Deep Dives, Emerging Terms, Overton auto‑curation.

- **Primary:** `moonshot-v1-8k`  
  - Provider: Moonshot/Kimi (via `moonshot:default` profile in `auth-profiles.json`).  
  - Used in: `analyze_transcript.py`, `auto_pipeline.py`, `ai_analyze_transcript.py`, `generate_deepdives.py`, `fix_ticker_mentions.py` (when base_url is Moonshot).

- **Fallback:** `gpt-4o-mini`  
  - Provider: OpenAI.  
  - Used automatically when we don’t have a Moonshot base_url on the client.

- **Secondary fallback (rare):** `gemini-1.5-flash`  
  - Provider: Google Generative AI, when `GEMINI_API_KEY` is set.  
  - Used only when Moonshot/OpenAI are unavailable.

**Do NOT use (deprecated/forbidden):**

- `openai/codex-mini-latest`
- `kimi-coding/kimi-k2-thinking`

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

- Extraction from episodes: same as pipeline analysis (Moonshot primary, GPT‑4o‑mini fallback).
- Auto‑curation thresholds live in `auto_curate_terms.py`:
  - `MIN_RELEVANCE_AUTO`, `MIN_SOURCES_AUTO`, `MIN_MENTIONS_AUTO`, `PROMOTE_MENTIONS_THRESHOLD`.

Sorting on the front page uses these scores; Overton will get a 30‑day half‑life decay based on `last_mentioned_date`.

---

### 4. Chat / Assistants

**Cursor (this assistant):**

- Optimized for: code, pipeline wiring, local tools, HEARTBEAT/MEMORY updates.
- Treat as the “Clawbot brain” for design and implementation work.

**OpenClaw agents (cron/heartbeat):**

- Use the same model priorities as above for heavy tasks.
- Heartbeats should be light: read JSONs, only trigger heavy models when runs are stale or blocked.

---

### 5. Cost Guardrails (summary)

- Heavy cost = long‑context LLM calls (transcripts, Deep Dives, term curation), not chats.
- Don’t run `auto_pipeline.py` on every chat; keep it on:
  - Scheduled jobs (midnight, 4am, 7am, 10pm), and
  - Explicit commands when something is clearly stale/broken.
- Heartbeats:
  - Read `status.json` / `pipeline_state.json`.  
  - Only trigger `auto_pipeline.py` when `last_pipeline_run` is past the configured threshold.  
  - Notify Jared only on `blocked_*` states or stuck episodes, not on normal in‑flight work.

