# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod

### Whisper (speech-to-text)

- **openai-whisper** (local CLI): installed via `pip install openai-whisper`; `whisper` is at `~/anaconda3/bin/whisper`. Both skills **openai-whisper** and **openai-whisper-api** are ready. If the gateway runs as a service (LaunchAgent), ensure its PATH includes the directory containing `whisper` so the bot can transcribe audio.
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

## Openclaw: Add API key for a new model

**Interactive (recommended):**

- **Full wizard:** `openclaw onboard` — then choose model/auth when prompted.
- **Model + auth only:** `openclaw configure --section model` — guided model and credential setup.

**Provider login (OAuth / device flow):**

- `openclaw models auth login --provider <id>` — e.g. `openai-codex`, `qwen-portal`. Use `--set-default` to apply that provider’s default model.
- See which providers support login: `openclaw plugins list` (auth is often built-in; docs list provider IDs).

**API key via onboard (non-interactive):**

- `openclaw onboard --auth-choice <choice> --<provider>-api-key "$VAR"`  
  Examples: `--auth-choice openai-api-key --openai-api-key "$OPENAI_API_KEY"`, `--auth-choice apiKey --token-provider openrouter --token "$OPENROUTER_API_KEY"`.
- Auth choices include: `openai-api-key`, `anthropic` (setup-token), `openrouter-api-key`, `gemini-api-key`, `zai-api-key`, `moonshot-api-key`, `synthetic-api-key`, `opencode-zen`, `apiKey` (generic + `--token-provider`), etc. Run `openclaw onboard --help` for the full list.

**Paste or add token:**

- `openclaw models auth add` — interactive: setup-token or paste token.
- `openclaw models auth paste-token --provider <id>` — paste a token for a provider (e.g. `anthropic`).

**Config (manual key):**

- `openclaw config set models.providers.<provider>.apiKey "your-key"` — e.g. Ollama: `openclaw config set models.providers.ollama.apiKey "ollama-local"`.

**Check status:**

- `openclaw models status` — current default model and auth overview; use `--probe` for live auth checks.

---

## Email Ingestion Account

**Newsletter Collection:**
- Provider: Gmail
- Address: jsheppard8989@gmail.com
- Password: F@llP@ssW0rD$
- Purpose: Receive forwarded newsletters for stock analysis pipeline
- IMAP: imap.gmail.com:993 (SSL)

---

Add whatever helps you do your job. This is your cheat sheet.
