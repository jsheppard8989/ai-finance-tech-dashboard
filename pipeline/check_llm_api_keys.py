#!/usr/bin/env python3
"""
Probe configured LLM backends (same order as analyze_transcript.get_ai_client).
Prints OK / FAIL only — never prints API keys.

Usage: cd pipeline && python3 check_llm_api_keys.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env like auto_pipeline
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.is_file():
    try:
        for line in _ENV.read_text(encoding="utf-8").splitlines():
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


def _try_moonshot() -> tuple[str, bool, str]:
    try:
        from openai import OpenAI
    except ImportError:
        return ("moonshot", False, "openai package missing")
    from analyze_transcript import resolve_llm_model
    key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not key:
        return ("moonshot", False, "MOONSHOT_API_KEY unset")
    try:
        c = OpenAI(api_key=key, base_url="https://api.moonshot.ai/v1")
        model = resolve_llm_model("moonshot")
        r = c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say OK in one word."}],
            max_tokens=8,
        )
        text = (r.choices[0].message.content or "").strip()
        return ("moonshot", True, f"model={model} reply={text[:30]}")
    except Exception as e:
        return ("moonshot", False, str(e)[:200])


def _try_openai() -> tuple[str, bool, str]:
    try:
        from openai import OpenAI
    except ImportError:
        return ("openai", False, "openai package missing")
    from analyze_transcript import resolve_llm_model
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return ("openai", False, "OPENAI_API_KEY unset")
    try:
        c = OpenAI(api_key=key)
        model = resolve_llm_model("openai")
        r = c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say OK in one word."}],
            max_tokens=8,
        )
        text = (r.choices[0].message.content or "").strip()
        return ("openai", True, f"model={model} reply={text[:30]}")
    except Exception as e:
        return ("openai", False, str(e)[:200])


def _try_gemini() -> tuple[str, bool, str]:
    from analyze_transcript import resolve_llm_model
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return ("gemini", False, "GEMINI_API_KEY unset")
    try:
        import google.generativeai as genai
    except ImportError:
        return ("gemini", False, "google-generativeai missing")
    try:
        genai.configure(api_key=key)
        model_name = resolve_llm_model("gemini")
        model = genai.GenerativeModel(model_name)
        r = model.generate_content("Say OK in one word.")
        text = (r.text or "").strip()
        return ("gemini", True, f"model={model_name} reply={text[:30]}")
    except Exception as e:
        return ("gemini", False, str(e)[:200])


def main() -> int:
    print("LLM API probes (keys never shown):\n")
    results = [_try_moonshot(), _try_openai(), _try_gemini()]
    for name, ok, detail in results:
        status = "OK " if ok else "FAIL"
        print(f"  {status}  {name:10}  {detail}")
    print(
        "\nNote: Transcript analysis uses get_ai_client() priority: Moonshot (auth profile or MOONSHOT_API_KEY) → Gemini → OpenAI."
    )
    print("Model defaults (env-overridable): Moonshot=kimi-k2.6, OpenAI=gpt-4o-mini, Gemini=gemini-1.5-flash.")
    print("Override via DEBATE_LLM_MODEL / MOONSHOT_MODEL, OPENAI_DEBATE_MODEL / OPENAI_MODEL, GEMINI_DEBATE_MODEL / GEMINI_MODEL.")
    return 0 if any(r[1] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
