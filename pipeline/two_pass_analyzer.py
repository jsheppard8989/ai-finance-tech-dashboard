#!/usr/bin/env python3
"""
Two-Pass Podcast Analyzer - Jared's cost-efficient design.

Pass 1 (gpt-5.4-nano): Extract structured intelligence from transcript
Pass 2 (gpt-5.4-mini): Synthesize REAL ALPHA brief from extraction only (never sees transcript)

Feature flag: ANALYZER_MODE=two_pass (default: legacy)

Waste guards:
- Cache by episode_id + transcript sha256
- Stop batch on 429/insufficient_quota with single notification
- Log usage tokens per call
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from workspace_paths import DB_PATH

EXTRACTION_PROMPT = """
You are a high-quality research analyst processing a long-form podcast transcript.

Your job is NOT to summarize the conversation.

Instead, extract the information that could be useful for future research,
investment analysis, business decisions, or understanding important trends.

Identify:

1. Major claims made by the speakers
2. Evidence supporting those claims
3. Important statistics, numbers and estimates
4. Companies, stocks, technologies and industries mentioned
5. Predictions about the future
6. Catalysts
7. Risks and potential failure modes
8. Contrarian or non-consensus ideas
9. Investment opportunities
10. Investment threats
11. Important unanswered questions
12. Particularly insightful observations

For investment ideas, distinguish between:

FACT
OPINION
PREDICTION
SPECULATION

Do not blindly accept claims made by the speaker.

Return structured JSON.

The JSON should contain:

{
  "episode_summary": "...",
  "major_claims": [],
  "important_facts": [],
  "numbers": [],
  "companies_and_assets": [],
  "predictions": [],
  "catalysts": [],
  "risks": [],
  "investment_ideas": [],
  "contrarian_ideas": [],
  "unanswered_questions": [],
  "high_value_quotes": []
}

IMPORTANT: For high_value_quotes, include the speaker's FULL NAME (when known from the transcript) and keep the quote VERBATIM exactly as spoken. Format each quote as:
{"speaker": "Full Name", "quote": "Exact verbatim quote from transcript"}

Transcript:

"""


SYNTHESIS_PROMPT = """
You are the senior analyst of an investment research team.

You have been given structured intelligence extracted from a podcast.

Your job is to produce a concise but deep "REAL ALPHA" briefing.

Do NOT simply repeat the podcast.

Separate:

FACTS
from
SPEAKER OPINIONS
from
YOUR INFERENCES.

Identify ideas that could actually affect an investor's thinking.

For every investment idea, consider:

• What is the thesis?
• Why now?
• What is the catalyst?
• What could prove the thesis wrong?
• What is the likely time horizon?
• What evidence supports it?
• Is the idea already consensus?
• What would create an information advantage?

Be skeptical.

If the speaker makes a weak argument, say so.

If the podcast contains no meaningful investment insight, explicitly say that.

Produce the following sections:

# REAL ALPHA — PODCAST INTELLIGENCE BRIEF

## Executive Take

## 10 Most Important Ideas

## Investment Implications

### Bullish
### Bearish
### Watch

## Numbers Worth Remembering

## Companies / Assets Mentioned

## Contrarian / Non-Consensus Ideas

## What the Speaker May Be Wrong About

## Action Items

## Independent Analyst Take

## Confidence

ALSO, you must provide site-contract fields in a structured JSON block at the END of your response.
After the markdown brief, add a line "---SITE_CONTRACT_JSON---" followed by a JSON object with these keys:
{
  "episode_title": "Full episode title",
  "summary": "3-5 paragraph recap of the actual argument, numbers, dates, disagreements, predictions",
  "key_takeaways": ["5-7 bullets, each one specific claim with attribution"],
  "investment_thesis": "ONE sentence under 40 words stating the episode's single most important specific claim",
  "sentiment": "neutral|bullish|bearish (default neutral unless explicit directional language)",
  "notable_quotes": [{"speaker": "Full Name", "quote": "Verbatim under 240 chars"}],
  "key_tickers": ["TICKER1", "TICKER2"],
  "ticker_mentions": [{"ticker": "TICKER", "context": "1-2 sentences", "sentiment": "neutral", "conviction_score": 75, "timeframe": "medium_term", "is_contrarian": false, "is_disruption_focused": false}],
  "emerging_terms": [{"term": "Term Name", "definition": "1-2 sentences", "investment_angle": "Why it matters", "speaker_quote": "Short verbatim line"}],
  "guests": [{"name": "Full Name", "role": "guest", "bio": "1-2 sentences"}],
  "hosts": [{"name": "Full Name", "role": "host"}]
}

Use the extraction's high_value_quotes for notable_quotes - keep them verbatim with correct speaker names.
For sentiment, default to neutral. Use bullish/bearish ONLY when the speaker explicitly states a direction.

Here is the extracted intelligence:

"""


PASS1_MODEL = "gpt-5.4-nano"
PASS2_MODEL = "gpt-5.4-mini"

CHUNK_TOKEN_BUDGET = 350_000


class InsufficientQuotaError(Exception):
    """Raised on 429 / insufficient_quota to signal batch stop."""
    pass


class TwoPassAnalyzerCache:
    """SQLite-backed cache for extraction results by episode_id + transcript sha256."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._ensure_table()
    
    def _ensure_table(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS two_pass_cache (
                episode_id INTEGER NOT NULL,
                transcript_sha256 TEXT NOT NULL,
                extraction_json TEXT,
                brief_markdown TEXT,
                pass1_input_tokens INTEGER,
                pass1_output_tokens INTEGER,
                pass2_input_tokens INTEGER,
                pass2_output_tokens INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (episode_id, transcript_sha256)
            )
        """)
        conn.commit()
        conn.close()
    
    def get(self, episode_id: int, transcript_sha256: str) -> Optional[Dict]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM two_pass_cache WHERE episode_id = ? AND transcript_sha256 = ?",
            (episode_id, transcript_sha256)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return None
    
    def put(
        self,
        episode_id: int,
        transcript_sha256: str,
        extraction_json: str,
        brief_markdown: str,
        pass1_input_tokens: int = 0,
        pass1_output_tokens: int = 0,
        pass2_input_tokens: int = 0,
        pass2_output_tokens: int = 0,
    ):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            INSERT OR REPLACE INTO two_pass_cache
            (episode_id, transcript_sha256, extraction_json, brief_markdown,
             pass1_input_tokens, pass1_output_tokens, pass2_input_tokens, pass2_output_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (episode_id, transcript_sha256, extraction_json, brief_markdown,
             pass1_input_tokens, pass1_output_tokens, pass2_input_tokens, pass2_output_tokens)
        )
        conn.commit()
        conn.close()


def transcript_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_transcript(text: str, max_tokens: int = CHUNK_TOKEN_BUDGET) -> List[str]:
    """Split transcript into chunks if it exceeds token budget.
    
    Returns list of chunks. For transcripts under budget, returns single-element list.
    Uses approximate 4 chars/token heuristic for speed.
    """
    approx_chars = max_tokens * 4
    if len(text) <= approx_chars:
        return [text]
    
    chunks = []
    words = text.split()
    current_chunk = []
    current_len = 0
    
    for word in words:
        word_len = len(word) + 1
        if current_len + word_len > approx_chars and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_len = word_len
        else:
            current_chunk.append(word)
            current_len += word_len
    
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    return chunks


def merge_extractions(extractions: List[Dict]) -> Dict:
    """Deterministically merge multiple chunk extractions.
    
    Deduplicates by content similarity. No LLM call.
    """
    if len(extractions) == 1:
        return extractions[0]
    
    merged = {
        "episode_summary": "",
        "major_claims": [],
        "important_facts": [],
        "numbers": [],
        "companies_and_assets": [],
        "predictions": [],
        "catalysts": [],
        "risks": [],
        "investment_ideas": [],
        "contrarian_ideas": [],
        "unanswered_questions": [],
        "high_value_quotes": [],
    }
    
    seen_strings: Dict[str, set] = {k: set() for k in merged if isinstance(merged[k], list)}
    
    summaries = []
    for ext in extractions:
        if ext.get("episode_summary"):
            summaries.append(ext["episode_summary"])
        
        for key in merged:
            if key == "episode_summary":
                continue
            items = ext.get(key) or []
            for item in items:
                if isinstance(item, dict):
                    item_key = json.dumps(item, sort_keys=True)
                else:
                    item_key = str(item).lower().strip()
                
                if item_key not in seen_strings[key]:
                    seen_strings[key].add(item_key)
                    merged[key].append(item)
    
    merged["episode_summary"] = " ".join(summaries)
    
    return merged


def call_openai_json(
    client,
    model: str,
    prompt: str,
    system_prompt: str = "You are a precise financial analyst. Return only valid JSON.",
) -> Tuple[Dict, int, int]:
    """Call OpenAI with JSON mode. Returns (parsed_json, input_tokens, output_tokens).
    
    Raises InsufficientQuotaError on 429/insufficient_quota.
    """
    from openai import RateLimitError
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=16000,
        )
    except RateLimitError as e:
        if "insufficient_quota" in str(e).lower() or "429" in str(e):
            raise InsufficientQuotaError(f"Rate limit / quota exceeded: {e}")
        raise
    
    content = response.choices[0].message.content or ""
    content = content.strip()
    
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    parsed = json.loads(content)
    return parsed, input_tokens, output_tokens


def call_openai_text(
    client,
    model: str,
    prompt: str,
    system_prompt: str = "You are a senior investment analyst.",
) -> Tuple[str, int, int]:
    """Call OpenAI for text output. Returns (text, input_tokens, output_tokens).
    
    Raises InsufficientQuotaError on 429/insufficient_quota.
    """
    from openai import RateLimitError
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=16000,
        )
    except RateLimitError as e:
        if "insufficient_quota" in str(e).lower() or "429" in str(e):
            raise InsufficientQuotaError(f"Rate limit / quota exceeded: {e}")
        raise
    
    content = response.choices[0].message.content or ""
    
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    return content, input_tokens, output_tokens


def pass1_extract(client, transcript: str) -> Tuple[Dict, int, int]:
    """Pass 1: Extract structured intelligence from transcript using nano.
    
    Handles chunking for overlong transcripts.
    Returns (extraction_dict, total_input_tokens, total_output_tokens).
    """
    chunks = chunk_transcript(transcript)
    
    extractions = []
    total_input = 0
    total_output = 0
    
    for i, chunk in enumerate(chunks):
        print(f"    Pass 1 chunk {i+1}/{len(chunks)}...", flush=True)
        prompt = EXTRACTION_PROMPT + chunk
        
        extraction, inp, out = call_openai_json(client, PASS1_MODEL, prompt)
        extractions.append(extraction)
        total_input += inp
        total_output += out
        
        print(f"      Tokens: {inp:,} in / {out:,} out", flush=True)
    
    merged = merge_extractions(extractions)
    return merged, total_input, total_output


def pass2_synthesize(client, extraction_json: str, podcast_name: str = "") -> Tuple[str, Dict, int, int]:
    """Pass 2: Synthesize REAL ALPHA brief from extraction JSON using mini.
    
    Never sees the transcript.
    Returns (brief_markdown, site_contract_dict, input_tokens, output_tokens).
    """
    prompt = SYNTHESIS_PROMPT + extraction_json
    
    content, inp, out = call_openai_text(client, PASS2_MODEL, prompt)
    
    print(f"    Pass 2 tokens: {inp:,} in / {out:,} out", flush=True)
    
    brief_markdown = content
    site_contract = {}
    
    if "---SITE_CONTRACT_JSON---" in content:
        parts = content.split("---SITE_CONTRACT_JSON---", 1)
        brief_markdown = parts[0].strip()
        try:
            json_part = parts[1].strip()
            if json_part.startswith("```json"):
                json_part = json_part[7:]
            if json_part.startswith("```"):
                json_part = json_part[3:]
            if json_part.endswith("```"):
                json_part = json_part[:-3]
            site_contract = json.loads(json_part.strip())
        except (json.JSONDecodeError, IndexError):
            pass
    
    return brief_markdown, site_contract, inp, out


def map_to_site_fields(extraction: Dict, site_contract: Dict, brief_markdown: str) -> Dict:
    """Map REAL ALPHA extraction + synthesis to the site contract fields.
    
    Returns dict compatible with the current analyzer's output format.
    """
    quotes = site_contract.get("notable_quotes") or []
    if not quotes:
        hvq = extraction.get("high_value_quotes") or []
        for q in hvq[:3]:
            if isinstance(q, dict) and q.get("speaker") and q.get("quote"):
                quotes.append({
                    "speaker": q["speaker"][:120],
                    "quote": q["quote"][:400]
                })
    
    tickers = site_contract.get("key_tickers") or []
    if not tickers:
        companies = extraction.get("companies_and_assets") or []
        for c in companies[:6]:
            if isinstance(c, str) and c.isupper() and len(c) <= 5:
                tickers.append(c)
    
    result = {
        "episode_title": site_contract.get("episode_title", ""),
        "episode_date": date.today().isoformat(),
        "summary": site_contract.get("summary") or extraction.get("episode_summary", ""),
        "key_takeaways": site_contract.get("key_takeaways") or [],
        "key_tickers": tickers[:6],
        "investment_thesis": site_contract.get("investment_thesis", ""),
        "notable_quotes": quotes[:3],
        "ticker_mentions": site_contract.get("ticker_mentions") or [],
        "emerging_terms": site_contract.get("emerging_terms") or [],
        "guests": site_contract.get("guests") or [],
        "hosts": site_contract.get("hosts") or [],
        "sentiment": site_contract.get("sentiment", "neutral"),
        "_extraction_json": json.dumps(extraction),
        "_brief_markdown": brief_markdown,
    }
    
    if result["sentiment"] not in ("bullish", "bearish", "neutral"):
        result["sentiment"] = "neutral"
    
    return result


def analyze_transcript_two_pass(
    client,
    transcript: str,
    podcast_name: str,
    episode_id: Optional[int] = None,
    cache: Optional[TwoPassAnalyzerCache] = None,
) -> Optional[Dict]:
    """Full two-pass analysis. Returns dict compatible with existing analyzer output.
    
    Args:
        client: OpenAI client
        transcript: Full transcript text
        podcast_name: Name of podcast
        episode_id: Episode ID for caching (optional)
        cache: Cache instance (optional)
    
    Returns:
        Analysis dict, or None on failure
    
    Raises:
        InsufficientQuotaError: On 429/insufficient_quota (caller should stop batch)
    """
    sha = transcript_sha256(transcript)
    
    if cache and episode_id:
        cached = cache.get(episode_id, sha)
        if cached and cached.get("extraction_json") and cached.get("brief_markdown"):
            print(f"    Cache hit for episode {episode_id}", flush=True)
            extraction = json.loads(cached["extraction_json"])
            brief = cached["brief_markdown"]
            
            if "---SITE_CONTRACT_JSON---" in brief:
                parts = brief.split("---SITE_CONTRACT_JSON---", 1)
                brief_clean = parts[0].strip()
                try:
                    site_contract = json.loads(parts[1].strip())
                except:
                    site_contract = {}
            else:
                site_contract = {}
                brief_clean = brief
            
            return map_to_site_fields(extraction, site_contract, brief_clean)
    
    print(f"    Pass 1: Extracting with {PASS1_MODEL}...", flush=True)
    extraction, p1_in, p1_out = pass1_extract(client, transcript)
    
    extraction_json = json.dumps(extraction, indent=2)
    
    print(f"    Pass 2: Synthesizing with {PASS2_MODEL}...", flush=True)
    brief, site_contract, p2_in, p2_out = pass2_synthesize(
        client, extraction_json, podcast_name
    )
    
    total_cost = (
        (p1_in / 1_000_000 * 0.20) + (p1_out / 1_000_000 * 1.25) +
        (p2_in / 1_000_000 * 0.75) + (p2_out / 1_000_000 * 4.50)
    )
    print(f"    Total tokens: {p1_in + p2_in:,} in / {p1_out + p2_out:,} out", flush=True)
    print(f"    Estimated cost: ${total_cost:.4f}", flush=True)
    
    if cache and episode_id:
        cache.put(
            episode_id, sha, extraction_json, brief,
            p1_in, p1_out, p2_in, p2_out
        )
    
    return map_to_site_fields(extraction, site_contract, brief)


def is_two_pass_enabled() -> bool:
    """Check if two-pass mode is enabled via ANALYZER_MODE env var."""
    mode = os.environ.get("ANALYZER_MODE", "").strip().lower()
    return mode == "two_pass"


def get_two_pass_client():
    """Get OpenAI client for two-pass analysis.
    
    Reads OPENAI_API_KEY from environment (loaded from .env by caller).
    """
    from openai import OpenAI
    
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    
    return OpenAI(api_key=api_key)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python two_pass_analyzer.py <transcript_path> [episode_id]")
        sys.exit(1)
    
    transcript_path = Path(sys.argv[1])
    episode_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    if not transcript_path.exists():
        print(f"Transcript not found: {transcript_path}")
        sys.exit(1)
    
    from dotenv import load_dotenv
    load_dotenv()
    
    transcript = transcript_path.read_text(encoding="utf-8", errors="ignore")
    client = get_two_pass_client()
    
    cache = TwoPassAnalyzerCache()
    
    result = analyze_transcript_two_pass(
        client, transcript, "Test Podcast", episode_id, cache
    )
    
    if result:
        print("\n" + "="*60)
        print("ANALYSIS RESULT")
        print("="*60)
        print(json.dumps({k: v for k, v in result.items() if not k.startswith("_")}, indent=2))
        print("\n" + "="*60)
        print("REAL ALPHA BRIEF")
        print("="*60)
        print(result.get("_brief_markdown", ""))
    else:
        print("Analysis failed")
        sys.exit(1)
