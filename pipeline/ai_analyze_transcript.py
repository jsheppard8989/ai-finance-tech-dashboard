#!/usr/bin/env python3
"""
AI Transcript Entity/Idea Analyzer.

Goal:
- Take a single podcast episode transcript.
- Call an AI client in a token-efficient way (chunked) to extract:
  - people (hosts/guests) with optional bios/known_for
  - main investment-relevant ideas
- Ingest into semantic layer tables via ingest_ai_analysis.ingest_ai_result.

This file is the only new place where we add AI calls for podcast entities/ideas.
"""

import argparse
from pathlib import Path
from typing import Dict, Any, List

from ingest_ai_analysis import ingest_ai_result
from db_manager import get_db
from analyze_transcript import get_ai_client  # reuse existing AI client config


def load_episode_meta(episode_id: int) -> dict:
    """Fetch minimal metadata for a podcast episode."""
    db = get_db()
    with db._get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, podcast_name, episode_title, episode_date, transcript_path
            FROM podcast_episodes
            WHERE id = ?
            """,
            (episode_id,),
        ).fetchone()
    if not row:
        raise SystemExit(f"No podcast_episodes row found for id={episode_id}")
    return dict(row)


def segment_transcript(text: str, max_chars: int = 4000) -> List[str]:
    """
    Split transcript into roughly max_chars chunks on paragraph boundaries.
    This keeps each AI call to a manageable token size.
    """
    text = text.strip()
    if not text:
        return []
    paragraphs = text.split("\n\n")
    segments: List[str] = []
    buf: List[str] = []
    cur_len = 0
    for para in paragraphs:
        p = para.strip()
        if not p:
            continue
        if cur_len + len(p) + 2 > max_chars and buf:
            segments.append("\n\n".join(buf))
            buf = [p]
            cur_len = len(p)
        else:
            buf.append(p)
            cur_len += len(p) + 2
    if buf:
        segments.append("\n\n".join(buf))
    return segments


def analyze_segment(segment: str, episode_meta: dict, client_info) -> Dict[str, Any]:
    """
    Call AI once for a segment to get lightweight people/idea candidates.
    Returns a dict with 'people' and 'ideas' keys.
    """
    client_type, client = client_info
    title = episode_meta.get("episode_title") or ""
    podcast = episode_meta.get("podcast_name") or ""

    prompt = f"""You are extracting investment-relevant structure from a podcast transcript segment.

Episode: "{title}" from "{podcast}"

Segment:
{segment[:3500]}

Return JSON with two keys:
- "people": array of objects with fields:
    - "name": person speaking or discussed (only real people, no shows or topics)
    - "role": "host", "guest", or "panelist" (best guess)
- "ideas": array of objects with fields:
    - "speaker_name": who primarily advances the idea
    - "summary": 1-2 sentence summary of the idea (investment/macro relevant)
    - "thesis": optional longer thesis (can be empty string)
    - "tickers": list of ticker symbols if clearly discussed (or [])
    - "sentiment": "bullish", "bearish", or "neutral"

Be concise. If there are no clear people or investment ideas in this segment, return empty arrays.
"""

    # Use same pattern as newsletter AI: JSON response_format
    if client_type in ("openai", "moonshot"):
        model_name = "moonshot-v1-8k" if client_type == "moonshot" else "gpt-4o-mini"
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=400,
        )
        import json as _json

        return _json.loads(resp.choices[0].message.content)
    elif client_type == "gemini":
        import json as _json
        import google.generativeai as genai  # type: ignore

        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        return _json.loads(resp.text)
    else:
        return {"people": [], "ideas": []}


def call_ai_transcript(transcript_text: str, episode_meta: dict) -> dict:
    """
    Token-efficient AI pipeline:
    - Segment transcript into chunks.
    - Run one AI call per chunk to get candidate people/ideas.
    - Merge candidates into a final payload.
    """
    segments = segment_transcript(transcript_text)
    if not segments:
        return {"people": [], "ideas": []}

    client_info = get_ai_client()
    if not client_info:
        # Fallback: behave like stub
        return {"people": [], "ideas": []}

    merged_people: Dict[str, Dict[str, Any]] = {}
    merged_ideas: List[Dict[str, Any]] = []

    for seg in segments:
        try:
            result = analyze_segment(seg, episode_meta, client_info) or {}
        except Exception as e:
            print(f"  ⚠ AI segment analysis failed: {e}")
            continue

        for p in result.get("people") or []:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            existing = merged_people.get(key)
            if existing:
                # Prefer guest over host over panelist, and higher prominence
                role_order = {"guest": 3, "host": 2, "panelist": 1}
                new_role = (p.get("role") or existing.get("role") or "guest").lower()
                old_role = (existing.get("role") or "guest").lower()
                new_prom = int(p.get("prominence") or 1)
                old_prom = int(existing.get("prominence") or 1)
                if role_order.get(new_role, 0) > role_order.get(old_role, 0) or new_prom > old_prom:
                    existing["role"] = new_role
                    existing["prominence"] = max(new_prom, old_prom)
            else:
                merged_people[key] = {
                    "name": name,
                    "role": (p.get("role") or "guest").lower(),
                    "bio": p.get("bio") or None,
                    "known_for": p.get("known_for") or None,
                    "prominence": int(p.get("prominence") or 1),
                }

        for idea in result.get("ideas") or []:
            summary = (idea.get("summary") or "").strip()
            if not summary:
                continue
            merged_ideas.append(
                {
                    "speaker_name": idea.get("speaker_name"),
                    "summary": summary,
                    "thesis": idea.get("thesis") or None,
                    "tickers": idea.get("tickers") or [],
                    "sentiment": idea.get("sentiment") or None,
                }
            )

    return {
        "people": list(merged_people.values()),
        "ideas": merged_ideas,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-enhanced transcript analyzer (stub).")
    parser.add_argument("--episode-id", type=int, required=True, help="podcast_episodes.id")
    parser.add_argument(
        "--transcript-path",
        type=str,
        required=True,
        help="Path to transcript text file for this episode",
    )
    args = parser.parse_args()

    episode_meta = load_episode_meta(args.episode_id)
    tpath = Path(args.transcript_path).expanduser()
    if not tpath.exists():
        raise SystemExit(f"Transcript file not found: {tpath}")

    text = tpath.read_text(encoding="utf-8", errors="ignore")

    ai_payload = call_ai_transcript(text, episode_meta)

    ingest_ai_result("podcast", args.episode_id, ai_payload)
    print(f"✓ Ingested AI analysis result for episode {args.episode_id}")


if __name__ == "__main__":
    main()

