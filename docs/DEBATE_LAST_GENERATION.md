# Debate audio: what prompt produced the latest MP3?

This file explains **how** the weekly debate audio (`site/audio/emp_ai_the_debate_11labs.mp3`) is built and gives the **exact LLM prompt templates** from code.  

**Ground truth for your machine’s last run** (verbatim contract question, debater names, and the full TTS scripts) lives in JSON on disk **after** you run `pipeline/debate_weekly.py`:

| File | What it holds |
|------|----------------|
| `site/audio/debate_contract.json` | Public contract: `prompt`, `debater_a`, `debater_b`, `friday_iso`, `prompt_hash`, `generated_at`, etc. |
| `pipeline/state/last_debate_scripts.json` | Full text sent to ElevenLabs: `host`, `yes`, `no`, `close` |
| `site/audio/debate_audio_meta.json` | Safety metadata: speakers extracted from scripts, `prompt_hash`, byte size |

**To see the exact last contract + scripts:** open those three files in your workspace (or run `cat` on them). They override any summary here.

---

## End-to-end process (3 LLM steps + deterministic glue + TTS)

1. **Contract (JSON)** — `debate_weekly.generate_contract()` calls the configured LLM (Moonshot / OpenAI / Gemini via `analyze_transcript.get_ai_client`) with the **system** and **user** blocks below. Context is loaded from SQLite: active Overton terms + recent insight titles. Past week prompts are passed so the model avoids repeats.

2. **Debater speeches (JSON)** — `debate_weekly.generate_speeches()` uses the contract’s `prompt` and `crux_theme`, plus the two pundits’ display names and optional voice notes from `pundits.json` (`voice_tone`, `voice_style`, `voice_delivery_notes`).

3. **Host + close (no LLM)** — `build_host_script()` wraps the contract question and debater names; close line is fixed in `write_scripts_state()`.

4. **TTS** — `generate_debate_audio_11labs.tts()` concatenates: host voice → YES speech → NO speech → host again for close. Output: `emp_ai_the_debate_11labs.mp3`. `debate_audio_meta.json` records `prompt_hash` so the site can warn if contract and audio drift.

---

## 1) Contract generation — exact `system` string

*(from `pipeline/debate_weekly.py`, function `generate_contract`)*

```
You are the editorial brain for a weekly investor debate show.
Return ONLY valid JSON with keys:
  "prompt": string — one clear Yes/No question, falsifiable within ~42 days, no single-stock tickers (no AAPL, NVDA, etc.); themes like AI, rates, labor, policy, indices OK.
  "expires_rule": string — human-readable e.g. "Resolves Friday 12:00 PM CST YYYY-MM-DD" (pick date = contract Friday + 42 days).
  "crux_theme": short label for the substance (e.g. "AI labor", "rates path").
  "resolution_clarity": { "source_of_truth": string, "resolution_sources": [string], "resolution_criteria": [string] } — brief, practical.
```

## 1b) Contract — exact `user` template

Placeholders: Overton terms list, insight titles list, and `avoid` = bulleted past prompts.

```
Overton-style terms:
{terms joined or "(none)"}

Recent insight titles:
- {title}
...

Avoid repeating these past prompts:
{avoid bullets}

Produce ONE fresh contract JSON. The question must be specific enough to argue yes/no on substance, not philosophy.
```

---

## 2) Speeches generation — exact `system` string

*(from `generate_speeches`)*

```
Return ONLY valid JSON:
  "yes_speech": string — plain text for text-to-speech. Speaker is arguing YES on the contract.
  "no_speech": string — plain text for TTS, arguing NO.

Rules:
- Start each speech with only the speaker's first line as their name plus period, e.g. "Sam." then blank line, then body. Use the exact names given.
- The first sentence of YES body must begin with "The long of it".
- The first sentence of NO body must begin with "The short of it".
- Three substantive paragraphs (or sections) plus a short "Concession." paragraph.
- Argue the CRUX of the issue (e.g. real economic force vs narrative). Do NOT nitpick the contract wording or hide behind legal parsing.
- Do NOT repeat or quote the full Yes/No question; the listener already heard it from the host.
- No stage directions, no markdown.
```

## 2b) Speeches — exact `user` template

```
Contract question (for your reasoning only — do not read it back verbatim in the speeches):
{prompt}

Crux theme: {crux or "general"}

YES speaker display name: {name_yes}
NO speaker display name: {name_no}
YES speaker style notes: {voice_yes or "(none)"}
NO speaker style notes: {voice_no or "(none)"}

Write yes_speech and no_speech.
```

---

## 3) Deterministic host script (not from an LLM)

```text
Welcome to The Long and Short of It.
Today’s contract debate topic is:
{prompt}

{name_a} will make the case for yes.
{name_b} will make the case for no.
```

**Close** (fixed string in `write_scripts_state`):

```text
This has been The Long and Short of It. Choose evidence over tribe.
```

---

## 4) What to open to see the *actual* last generation

1. `site/audio/debate_contract.json` → field **`prompt`** is the exact Yes/No question used for that MP3.  
2. `pipeline/state/last_debate_scripts.json` → **`host`**, **`yes`**, **`no`**, **`close`** are the exact strings sent to ElevenLabs.  
3. Compare `debate_contract.json` **`prompt_hash`** with `debate_audio_meta.json` **`prompt_hash`** — they must match when publishing.

If those files are missing, the debate pipeline has not been run successfully on this machine yet; the strings above are still the **templates** the code will use on the next run.

---

## Commands

```bash
# Full week: new contract + speeches + TTS + write JSON
python3 pipeline/debate_weekly.py

# Regenerate audio only from saved scripts (same TTS inputs)
python3 pipeline/debate_weekly.py --audio-only
```

Env: LLM per `analyze_transcript` / `.env`; ElevenLabs `ELEVENLABS_HOST_VOICE_ID`, `ELEVENLABS_A_VOICE_ID`, `ELEVENLABS_B_VOICE_ID`.
