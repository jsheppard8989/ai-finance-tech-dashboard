# The Long and Short of It — weekly automation

## What runs

| Piece | Role |
|-------|------|
| `pipeline/debate_weekly.py` | Friday job: archive last week → use that Friday's editorially approved contract, or generate an LLM fallback → LLM speeches (**full pundit profile** per debater) → rotate pair → ElevenLabs MP3 |
| `pipeline/debate_editorial_contract.json` | Human-approved Friday topic and resolution rules. It is used only when its `friday_iso` matches the scheduled run. |
| `pipeline/polymarket_debate_context.py` | Fetches public [Gamma API](https://gamma-api.polymarket.com) events (no auth), filters out sports/pop noise, sorts by volume + relevance for macro/policy/crypto/tech ideas only. |
| `site/audio/debate_contract.json` | **Current week** (prompt, debaters, expiry, bet status). Often gitignored; push with `-f` for Pages. |
| `site/debate_history.json` | **Prior weeks** + `rotation_index`. Commit so the site shows history and resolution. |
| `pipeline/state/last_debate_scripts.json` | Last TTS scripts (local). `generate_debate_audio_11labs.py` / `--audio-only` reuse this. |

## Cron (example)

Friday morning America/Chicago after pipeline export:

```bash
cd $WORKSPACE_ROOT && python3 pipeline/debate_weekly.py
```

Optional: `0 9 * * 5` (9am Fri CST) — adjust for host TZ.

## Editorial contract

Before Friday, review and edit `pipeline/debate_editorial_contract.json`. The scheduled run uses it
only when `friday_iso` matches that Friday; a stale file is ignored. If no matching approved contract
exists, topic generation falls back to Overton + insights + live Polymarket context and the quality
gates. Run `python3 pipeline/debate_weekly.py --dry-run` to validate the approved contract without
generating speeches or audio.

Add editor-verified facts and source URLs under `evidence_brief`. Speech generation may use empirical
specifics only from this packet; otherwise it must label claims as assumptions or first-principles
inferences. Both sides are instructed to steelman the opposition, expose their weakest causal link,
state what would change their conclusion, and offer a conditional path to U.S. economic upside from AI.

Before publishing, run `--scripts-only` and review `pipeline/state/last_debate_scripts.json`. This
generates the selected debaters' written cases and review metadata, then exits before changing history,
calling ElevenLabs, writing the public contract, or touching site audio.

## CLI

```bash
python3 pipeline/debate_weekly.py              # new week only (same friday_iso = no-op)
python3 pipeline/debate_weekly.py --force        # regenerate current week
python3 pipeline/debate_weekly.py --dry-run      # print sample contract JSON, no writes
python3 pipeline/debate_weekly.py --scripts-only # review arguments; no archive, TTS, or publish
python3 pipeline/debate_weekly.py --audio-only   # re-encode MP3 from last scripts
python3 pipeline/debate_weekly.py --mark-resolved 2026-03-14 yes --notes "Per SEC filings"
```

## Resolving a bet

Update `site/debate_history.json` via `--mark-resolved`, or edit the matching `weeks[]` entry:

- `resolution_status`: `pending` | `yes` | `no` | `void`
- `resolution_notes`, `resolved_at`

## Requirements

- LLM: Moonshot (primary) or OpenAI/Gemini (see `analyze_transcript.get_ai_client`).
- ElevenLabs: `ELEVENLABS_*` in `.env`.
- `site/data/pundits.json` from export (debater rotation).
- `pipeline/dashboard.db` with Overton + insights for topic context.
- Network (optional): Polymarket Gamma for fresh market themes; `requests` in env.

## Archived audio

Previous weeks’ MP3s are copied to `site/audio/archive/debate_YYYY-MM-DD.mp3`. The pipeline writes `site/audio/archive_manifest.json` (which files exist on disk). **Commit both the manifest and any archive MP3s** so GitHub Pages can serve history listen links; stale `audio_href` entries are cleared automatically when the file is missing.
