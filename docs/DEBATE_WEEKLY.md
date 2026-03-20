# The Long and Short of It — weekly automation

## What runs

| Piece | Role |
|-------|------|
| `pipeline/debate_weekly.py` | Friday job: archive last week → LLM Yes/No contract (Overton + insights + **live Polymarket Gamma themes** + anti-repeat / banned numerics) → LLM speeches (**full pundit profile** per debater) → rotate pair → ElevenLabs MP3 |
| `pipeline/polymarket_debate_context.py` | Fetches public [Gamma API](https://gamma-api.polymarket.com) events (no auth), filters out sports/pop noise, sorts by volume + relevance for macro/policy/crypto/tech ideas only. |
| `site/audio/debate_contract.json` | **Current week** (prompt, debaters, expiry, bet status). Often gitignored; push with `-f` for Pages. |
| `site/debate_history.json` | **Prior weeks** + `rotation_index`. Commit so the site shows history and resolution. |
| `pipeline/state/last_debate_scripts.json` | Last TTS scripts (local). `generate_debate_audio_11labs.py` / `--audio-only` reuse this. |

## Cron (example)

Friday morning America/Chicago after pipeline export:

```bash
cd ~/.openclaw/workspace && python3 pipeline/debate_weekly.py
```

Optional: `0 9 * * 5` (9am Fri CST) — adjust for host TZ.

## CLI

```bash
python3 pipeline/debate_weekly.py              # new week only (same friday_iso = no-op)
python3 pipeline/debate_weekly.py --force        # regenerate current week
python3 pipeline/debate_weekly.py --dry-run      # print sample contract JSON, no writes
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

Previous weeks’ MP3s are copied to `site/audio/archive/debate_YYYY-MM-DD.mp3` (large; add to `.gitignore` or store off-repo).
