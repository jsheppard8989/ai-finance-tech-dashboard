# AI Bench Press — POC

A proof-of-concept "AI only" debate. Two frontier models argue a resolution live
(opening → rebuttal → 2 cross-examination rounds → closing), then AI models judge it
blind. No humans on the panel.

**Match 1 resolution:** _AI data centers are bad for your community._
- **Ada (YES)** = Claude (Anthropic)
- **Gil (NO)** = GPT (OpenAI)
- **Judges** = independent AI models, blind to who's who

## Files
- `generate_debate.py` — runs the live multi-round debate + judging, writes `data/debate.json`
- `debate.js` — `data/debate.json` embedded as `window.DEBATE` (so the page works from `file://`)
- `index.html` — mobile-first page that shows the debate, downloads the final MP3, and falls back to on-device Web Speech when segment audio is not present
- `audio/match1.mp3` — committed downloadable episode
- `synthesize_audio.py` — regenerates local ElevenLabs segment audio (`audio/seg_*.mp3`) and `audio.js`; those generated files are ignored

## Run
```bash
python3 generate_debate.py                      # regenerate the debate (uses pipeline/.env keys)
python3 -c "import json,pathlib; pathlib.Path('debate.js').write_text('window.DEBATE = '+pathlib.Path('data/debate.json').read_text()+';')"
```

## View
Open `index.html` directly on your phone/desktop, or serve locally:
```bash
python3 -m http.server 8000   # then open http://localhost:8000
```
Tap ▶ to listen. Tap any turn to jump to it.

The committed page includes a real downloadable episode at `audio/match1.mp3`.
For per-turn studio playback, run `python3 synthesize_audio.py` locally to regenerate `audio.js` and the ignored `audio/seg_*.mp3` clips.
