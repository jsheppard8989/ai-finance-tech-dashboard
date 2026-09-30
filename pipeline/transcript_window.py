"""Shared transcript window and OpenAI chat parameters for insights and deep dives.

The old 12_000-character slice (and the Stage A mini digest that replaced it) is
what made cards thin and names wrong. Feed the raw transcript up to
TRANSCRIPT_WINDOW_CHARS.
"""

from __future__ import annotations

# Full hour-plus episode is about 25k tokens. gpt-5.5 accepts this window.
TRANSCRIPT_WINDOW_CHARS = 100_000
# Strongest OpenAI chat model this paid account accepts for JSON recaps (probed 2026-09-30).
# Not mini, not Flash, not Kimi. gpt-5.5 requires max_completion_tokens and temperature default 1.
OPENAI_ANALYSIS_MODEL = "gpt-5.5"


def sample_transcript_window(text: str, max_chars: int = TRANSCRIPT_WINDOW_CHARS) -> str:
    """Return the full transcript, or a start/middle/end sample if it exceeds max_chars."""
    text = text or ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    chunk = max(1, max_chars // 3)
    beginning = text[:chunk]
    mid_start = max(0, len(text) // 2 - chunk // 2)
    middle = text[mid_start : mid_start + chunk]
    ending = text[-chunk:]
    marker_mid = "\n\n[...middle of transcript...]\n\n"
    marker_end = "\n\n[...end of transcript...]\n\n"
    return beginning + marker_mid + middle + marker_end + ending


def openai_chat_kwargs(model: str, max_out: int, temperature: float = 0.3) -> dict:
    """Parameter names the model will actually accept.

    gpt-5.x and o-series reject max_tokens and any temperature other than the default (1).
    """
    name = (model or "").strip().lower()
    if name.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": int(max_out)}
    return {"max_tokens": int(max_out), "temperature": temperature}


def model_is_flash(model: str) -> bool:
    return "flash" in (model or "").lower()


def normalize_notable_quotes(raw, known_names=None):
    """Keep 2 or 3 {speaker, quote} dicts. Drop unnamed speakers."""
    import json
    from difflib import SequenceMatcher

    known = []
    for name in known_names or []:
        name = " ".join(str(name or "").split())
        if len(name) >= 3 and name not in known:
            known.append(name)

    def align(speaker: str) -> str:
        speaker = " ".join((speaker or "").split())
        best = speaker
        best_ratio = 0.0
        for name in known:
            if speaker.lower() == name.lower():
                return name
            ratio = SequenceMatcher(None, speaker.lower(), name.lower()).ratio()
            if ratio > best_ratio:
                best, best_ratio = name, ratio
        if best_ratio >= 0.84:
            return best
        return speaker

    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            raw = json.loads(raw)
        except Exception:
            raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        speaker = ""
        quote = ""
        if isinstance(item, dict):
            speaker = str(item.get("speaker") or item.get("name") or "").strip()
            quote = str(item.get("quote") or item.get("text") or "").strip()
        elif isinstance(item, str) and ":" in item:
            speaker, quote = item.split(":", 1)
            speaker = speaker.lstrip("- ").strip()
            quote = quote.strip().strip('"').strip()
        speaker = align(speaker)
        quote = quote.strip().strip('"').strip()
        if len(speaker) < 2 or len(quote) < 12:
            continue
        if speaker.lower() in {"host", "guest", "speaker", "unknown", "narrator"}:
            continue
        out.append({"speaker": speaker[:120], "quote": quote[:400]})
        if len(out) == 3:
            break
    return out
