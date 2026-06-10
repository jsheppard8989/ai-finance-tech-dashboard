#!/usr/bin/env python3
"""
Stage A: evidence-preserving markdown digest of long transcripts using a cheap,
large-context model: **auto** order is OpenAI > Gemini > Anthropic > Moonshot.
Writes ``<stem>.digest.md`` next to ``<stem>.txt``.
Downstream Insight + Deep Dive steps prefer this file when present.

Env:
  TRANSCRIPT_DIGEST_ENABLED — default 1; set 0 to disable.
  DIGEST_MIN_RAW_CHARS — minimum raw transcript length to run Stage A (default 10000).
  STAGE_A_PROVIDER — auto | openai | gemini | anthropic | moonshot (default auto).
  STAGE_A_MOONSHOT_MODEL — default moonshot-v1-8k
  STAGE_A_GEMINI_MODEL — default gemini-2.0-flash (fallback gemini-1.5-flash if needed).
  STAGE_A_ANTHROPIC_MODEL — default claude-3-5-haiku-20241022
  STAGE_A_OPENAI_MODEL — default gpt-4o-mini
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Tuple

_WORKSPACE = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = _WORKSPACE / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k or not v:
                continue
            if k.endswith("_API_KEY") or k in ("GITHUB_PUSH_TOKEN", "MOONSHOT_API_KEY"):
                if not str(os.environ.get(k, "")).strip():
                    os.environ[k] = v
            elif k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


def digest_path_for(transcript_path: Path) -> Path:
    """foo.txt -> foo.digest.md (same directory)."""
    p = transcript_path
    return p.parent / f"{p.stem}.digest.md"


def _min_raw_chars() -> int:
    try:
        return max(0, int(os.environ.get("DIGEST_MIN_RAW_CHARS", "10000")))
    except ValueError:
        return 10000


def is_digest_enabled() -> bool:
    _load_dotenv()
    v = os.environ.get("TRANSCRIPT_DIGEST_ENABLED", "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _has_any_stage_a_credentials() -> bool:
    _load_dotenv()
    return bool(
        (os.environ.get("GEMINI_API_KEY") or "").strip()
        or (os.environ.get("MOONSHOT_API_KEY") or "").strip()
        or (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        or (os.environ.get("OPENAI_API_KEY") or "").strip()
    )


def _digest_prompt(podcast_name: str, raw_transcript: str) -> str:
    return f"""You are an elite research analyst and executive briefing writer.

Your job is NOT to casually summarize this podcast.
Your job is to extract only the highest-value ideas, frameworks, and actionable intelligence for downstream investment analysis.

Return PLAIN MARKDOWN ONLY.
Do not return JSON.
Do not add any preamble like "Here is the analysis."

Podcast: {podcast_name}

HARD FILTER — EXCLUDE:
- filler
- jokes
- sponsor reads / ads
- conversational fluff
- vague motivational language
- rambling/tangents
- repeated stories that add no new information
- redundant phrasing

HARD FOCUS — PRIORITIZE:
- unique insights
- actionable advice
- mental models and decision frameworks
- contrarian viewpoints
- quantitative claims (numbers, dates, percentages, ranges)
- step-by-step processes
- concrete predictions
- investment/business/health lessons
- systems and operating principles
- specific tools, resources, or companies mentioned

NON-NEGOTIABLE RULES:
1) Do not invent facts, quotes, people, numbers, or conclusions.
2) If uncertain, say "Unclear from transcript."
3) Keep only high-signal content; prefer precision over coverage.
4) Preserve critical repeated references if they materially affect conviction (e.g., repeated ticker/company mentions).
5) No timestamps.
6) ASCII only.

OUTPUT FORMAT (exact section headers, in this exact order):

# Executive Summary
- 5-15 bullets, each one high-signal and specific.
- No generic bullets.

# Key Insights
For each major insight, use this template:

## Insight: <short title>
- What it is: <detailed explanation>
- Why it matters: <decision relevance / impact>
- Evidence from transcript: <specific supporting paraphrase or short quote, with speaker attribution if available>
- Practical implication: <how an operator/investor should use this>

Include only genuinely distinct insights (no duplicates with different wording).

# Actionable Takeaways
- Concrete actions someone could implement immediately.
- Use imperative phrasing.
- Include any prerequisites or constraints when relevant.

# Memorable Quotes
- Include only genuinely high-signal quotes.
- Max 10 quotes.
- Prefer quotes with direct practical or strategic value.
- If speaker identity is known, include "- <speaker>".

# Claims Requiring Verification
- List factual/scientific/market claims that should be independently checked.
- For each claim include:
  - Claim
  - Why verification is needed
  - Suggested verification source type (e.g., earnings report, peer-reviewed paper, regulator filing, BLS/FRED, company 10-K)

# Overall Signal Rating
- Practical value: <1-10>
- Originality: <1-10>
- Depth: <1-10>
- Credibility: <1-10>
- One-paragraph justification for all four scores.

TRANSCRIPT (full):
{raw_transcript}
"""


def _call_gemini(raw: str, podcast_name: str) -> Optional[str]:
    try:
        import google.generativeai as genai
    except ImportError:
        print("    ⚠ transcript_digest: google-generativeai not installed", flush=True)
        return None
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    genai.configure(api_key=key)
    model_id = (os.environ.get("STAGE_A_GEMINI_MODEL") or "gemini-2.0-flash").strip()
    model = genai.GenerativeModel(model_id)
    prompt = _digest_prompt(podcast_name, raw)
    try:
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=8192,
            ),
        )
        text = (resp.text or "").strip()
        return text if len(text) > 200 else None
    except Exception as e:
        err = str(e).lower()
        if "404" in err or "not found" in err or "invalid" in err:
            # Fallback model name
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                resp = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.2,
                        max_output_tokens=8192,
                    ),
                )
                text = (resp.text or "").strip()
                print("    ℹ transcript_digest: fell back to gemini-1.5-flash", flush=True)
                return text if len(text) > 200 else None
            except Exception as e2:
                print(f"    ⚠ transcript_digest Gemini fallback failed: {e2}", flush=True)
                return None
        print(f"    ⚠ transcript_digest Gemini failed: {e}", flush=True)
        return None


def _call_anthropic(raw: str, podcast_name: str) -> Optional[str]:
    try:
        import anthropic
    except ImportError:
        print("    ⚠ transcript_digest: anthropic not installed (pip install anthropic)", flush=True)
        return None
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.environ.get("STAGE_A_ANTHROPIC_MODEL") or "claude-3-5-haiku-20241022").strip()
    client = anthropic.Anthropic(api_key=key)
    prompt = _digest_prompt(podcast_name, raw)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=8192,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for b in msg.content:
            if hasattr(b, "text"):
                parts.append(b.text)
        text = "\n".join(parts).strip()
        return text if len(text) > 200 else None
    except Exception as e:
        print(f"    ⚠ transcript_digest Anthropic failed: {e}", flush=True)
        return None


def _call_openai(raw: str, podcast_name: str) -> Optional[str]:
    try:
        from openai import OpenAI
    except ImportError:
        print("    ⚠ transcript_digest: openai package not installed", flush=True)
        return None
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.environ.get("STAGE_A_OPENAI_MODEL") or "gpt-4o-mini").strip()
    client = OpenAI(api_key=key)
    prompt = _digest_prompt(podcast_name, raw)
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=8192,
        )
        text = (r.choices[0].message.content or "").strip()
        return text if len(text) > 200 else None
    except Exception as e:
        print(f"    ⚠ transcript_digest OpenAI failed: {e}", flush=True)
        return None


def _call_moonshot(raw: str, podcast_name: str) -> Optional[str]:
    try:
        from openai import OpenAI
    except ImportError:
        print("    ⚠ transcript_digest: openai package not installed for Moonshot", flush=True)
        return None
    key = (os.environ.get("MOONSHOT_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.environ.get("STAGE_A_MOONSHOT_MODEL") or "moonshot-v1-8k").strip()
    prompt = _digest_prompt(podcast_name, raw)
    try:
        client = OpenAI(api_key=key, base_url="https://api.moonshot.ai/v1")
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=8192,
        )
        text = (r.choices[0].message.content or "").strip()
        return text if len(text) > 200 else None
    except Exception as e:
        print(f"    ⚠ transcript_digest Moonshot failed: {e}", flush=True)
        return None


def _pick_provider() -> str:
    p = (os.environ.get("STAGE_A_PROVIDER") or "auto").strip().lower()
    if p in ("openai", "gemini", "moonshot", "anthropic"):
        return p
    return "auto"


def generate_digest_markdown(
    raw_transcript: str,
    podcast_name: str,
) -> Optional[str]:
    """Run Stage A and return markdown text, or None on failure/skip."""
    _load_dotenv()
    if not is_digest_enabled():
        return None
    if not _has_any_stage_a_credentials():
        return None

    order: list[str]
    prov = _pick_provider()
    if prov == "openai":
        order = ["openai"]
    elif prov == "gemini":
        order = ["gemini"]
    elif prov == "moonshot":
        order = ["moonshot"]
    elif prov == "anthropic":
        order = ["anthropic"]
    else:
        order = ["openai", "gemini", "anthropic", "moonshot"]

    for which in order:
        if which == "gemini":
            out = _call_gemini(raw_transcript, podcast_name)
        elif which == "moonshot":
            out = _call_moonshot(raw_transcript, podcast_name)
        elif which == "anthropic":
            out = _call_anthropic(raw_transcript, podcast_name)
        else:
            out = _call_openai(raw_transcript, podcast_name)
        if out:
            return out
    return None


def ensure_digest_file(
    transcript_path: Path,
    podcast_name: str,
    raw_content: str,
    *,
    force: bool = False,
) -> Optional[Path]:
    """
    If enabled and raw is long enough, write ``stem.digest.md`` next to the transcript.
    Returns path to digest if available, else None (caller uses raw transcript).
    """
    _load_dotenv()
    if not is_digest_enabled():
        return None
    if not _has_any_stage_a_credentials():
        return None

    out_path = digest_path_for(transcript_path)
    if out_path.exists() and not force:
        try:
            if out_path.stat().st_mtime >= transcript_path.stat().st_mtime:
                return out_path
        except Exception:
            return out_path

    min_c = _min_raw_chars()
    if len(raw_content) < min_c:
        print(
            f"    ℹ transcript_digest: raw length {len(raw_content)} < DIGEST_MIN_RAW_CHARS ({min_c}); skipping Stage A",
            flush=True,
        )
        return None

    print(f"    Stage A: building evidence-preserving digest ({len(raw_content)} chars raw)...", flush=True)
    md = generate_digest_markdown(raw_content, podcast_name)
    if not md:
        print("    ⚠ transcript_digest: Stage A failed; using full transcript for downstream steps", flush=True)
        return None

    header = "> Evidence-preserving digest (Stage A). Same file is used for Insight extraction and Deep Dives.\n\n"
    try:
        out_path.write_text(header + md, encoding="utf-8")
        print(f"    ✓ Wrote digest: {out_path.name} ({len(md)} chars)", flush=True)
        return out_path
    except Exception as e:
        print(f"    ⚠ transcript_digest: could not write {out_path}: {e}", flush=True)
        return None


def load_digest_or_raw(transcript_path: Path) -> Tuple[str, bool]:
    """Return (text, is_digest). Prefer digest file if present on disk."""
    dp = digest_path_for(transcript_path)
    if dp.exists():
        try:
            return dp.read_text(encoding="utf-8"), True
        except Exception:
            pass
    try:
        return transcript_path.read_text(encoding="utf-8"), False
    except Exception:
        return "", False


def main() -> int:
    """CLI: python3 transcript_digest.py path/to/transcript.txt [Podcast Name]"""
    _load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: transcript_digest.py <transcript.txt> [podcast_name]")
        return 1
    tp = Path(sys.argv[1])
    if not tp.is_file():
        print(f"Not found: {tp}")
        return 1
    name = sys.argv[2] if len(sys.argv) > 2 else "Unknown Podcast"
    raw = tp.read_text(encoding="utf-8")
    p = ensure_digest_file(tp, name, raw, force=True)
    print(p or "failed")
    return 0 if p else 1


if __name__ == "__main__":
    raise SystemExit(main())
