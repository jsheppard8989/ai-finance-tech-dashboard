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

EXTRACTION_PROMPT_BASE = """
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
  "companies_and_assets": [
    {
      "name": "Company Name",
      "ticker": "TICK",
      "claim": "What the speaker claims about this company",
      "evidence": "Supporting evidence from transcript",
      "key_quotes": [{"speaker": "Full Name", "quote": "Verbatim quote about this company, full sentence"}],
      "falsification": "What would prove this claim wrong, with date/condition if stated"
    }
  ],
  "predictions": [],
  "catalysts": [],
  "risks": [],
  "investment_ideas": [],
  "contrarian_ideas": [],
  "unanswered_questions": [],
  "high_value_quotes": [],
  "guests": [],
  "hosts": [],
  "falsification_tracks": ["Track 1: What would prove the overall thesis wrong", "Track 2: ..."]
}

"""

EXTRACTION_PROMPT_SUFFIX = """

SPEAKER ATTRIBUTION RULES:
- For high_value_quotes, you MUST attribute quotes to the specific named speaker when identifiable from context.
- Use the KNOWN SPEAKERS list above when the speaker is identifiable (do NOT use generic labels like "Unidentified speaker" or "Guest" when you can identify who spoke).
- For guests, include: {"name": "Full Name", "role": "guest", "bio": "Brief bio if mentioned"}
- For hosts, include: {"name": "Full Name", "role": "host"}

HIGH_VALUE_QUOTES RULES:
- Extract 5-8 high-value quotes from the transcript.
- Each quote MUST be: verbatim from the transcript, a complete self-contained sentence or sentences (15-60 words), and carry a specific claim, number, prediction, or contrarian view.
- Do NOT pick fragments, filler phrases, or generic statements that could apply to any podcast.
- Prefer quotes with: specific numbers/percentages, named companies, concrete predictions, contrarian positions, or testable claims.
- Format: {"speaker": "Full Name", "quote": "Exact verbatim quote 15-60 words"}
- NEVER attribute a host's words to the guest or vice versa.

NUMBERS FILTER:
- For numbers[], include only investment-relevant statistics: revenue, market size, growth rates, valuations, dates/timelines, percentages.
- EXCLUDE event logistics like broadcast times, masterclass schedules, Patreon amounts, episode numbers, or self-promotional timestamps.

COMPANIES_AND_ASSETS RULES:
- For each company or asset discussed with substance, include:
  - key_quotes: 1-3 verbatim quotes about this company from the transcript, each with {speaker, quote}. Use the KNOWN SPEAKERS list. Full sentences, 15-60 words.
  - falsification: What would prove the speaker's thesis about this company wrong? If the speaker states a date or condition, include it. If not stated, describe what evidence would falsify the claim.

FALSIFICATION_TRACKS:
- Include 3-5 top-level falsification tracks that would disprove the episode's overall thesis.
- Be specific: include timeframes, metrics, or observable conditions where stated or inferable.
- Example: "If HBM supply exceeds demand by Q3 2027, the capacity shortage thesis fails."

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

Produce ALL of the following sections (do not skip any):

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

You MUST complete all sections above. Do not truncate or stop early.

Here is the extracted intelligence:

"""


SITE_CONTRACT_PROMPT = """
Based on the podcast extraction data below, produce a JSON object with these site-contract fields.

RULES:
- For notable_quotes: Select the 3 MOST INSIGHTFUL quotes from high_value_quotes — those with specific claims, numbers, or contrarian views. Do NOT just pick the first 3. Keep them verbatim with CORRECT speaker names. NEVER attribute a host's words to the guest.
- Use the extraction's guests and hosts fields for those fields.
- For sentiment, default to "neutral". Use bullish/bearish ONLY when the speaker explicitly states a direction.
- For key_tickers and ticker_mentions: ONLY include a ticker when the speaker ACTUALLY DISCUSSED that company with investment-relevant substance (claims, numbers, catalysts, risks) as shown in the extraction's companies_and_assets, major_claims, investment_ideas, or risks. Do NOT invent "comparison points" or add tickers the speaker never discussed. If unsure, omit.
- For ticker_mentions: The context must describe what the SPEAKER said about that company, not what you infer. If there is no speaker quote or claim about that company in the extraction, do not include it.

Return ONLY this JSON object:
{
  "summary": "3-5 paragraph recap of the actual argument, numbers, dates, disagreements, predictions",
  "key_takeaways": ["5-7 bullets, each one specific claim with attribution to speaker"],
  "investment_thesis": "ONE sentence under 40 words stating the episode's single most important specific claim",
  "sentiment": "neutral|bullish|bearish",
  "notable_quotes": [{"speaker": "Full Name", "quote": "Verbatim 15-60 words, the 3 most insightful"}],
  "key_tickers": ["GOOGL"],
  "ticker_mentions": [{"ticker": "GOOGL", "context": "What the SPEAKER said about this company (from extraction)", "sentiment": "neutral", "conviction_score": 75, "timeframe": "medium_term", "is_contrarian": false, "is_disruption_focused": false}],
  "emerging_terms": [{"term": "Term Name", "definition": "1-2 sentences", "investment_angle": "Why it matters", "speaker_quote": "Short verbatim line"}],
  "guests": [{"name": "Full Name", "role": "guest", "bio": "1-2 sentences"}],
  "hosts": [{"name": "Full Name", "role": "host"}]
}

Extraction data:
"""


PASS1_MODEL = "gpt-5.4-nano"
PASS2_MODEL = "gpt-5.4-mini"

CHUNK_TOKEN_BUDGET = 350_000

PREFERRED_SHARE_CLASS = {
    "alphabet inc": "GOOGL",
    "fox corporation": "FOXA",
    "news corporation": "NWSA",
}

COMPANY_TO_TICKER = {
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "google x": "GOOGL",
    "x (the moonshot factory)": "GOOGL",
    "waymo": "GOOGL",
    "google brain": "GOOGL",
    "deepmind": "GOOGL",
    "youtube": "GOOGL",
    "nvidia": "NVDA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "instagram": "META",
    "whatsapp": "META",
    "coinbase": "COIN",
    "bitcoin": "BTC",
    "microstrategy": "MSTR",
    "netflix": "NFLX",
    "salesforce": "CRM",
    "oracle": "ORCL",
    "ibm": "IBM",
    "intel": "INTC",
    "amd": "AMD",
    "qualcomm": "QCOM",
    "broadcom": "AVGO",
    "palantir": "PLTR",
    "snowflake": "SNOW",
    "uber": "UBER",
    "lyft": "LYFT",
    "airbnb": "ABNB",
    "openai": "MSFT",
    "anthropic": "GOOGL",
}

TICKER_TO_COMPANIES = {}
for company, ticker in COMPANY_TO_TICKER.items():
    if ticker not in TICKER_TO_COMPANIES:
        TICKER_TO_COMPANIES[ticker] = []
    TICKER_TO_COMPANIES[ticker].append(company)

ANALOGY_PHRASES = [
    "skunk works",
    "like lockheed",
    "similar to",
    "reminds me of",
    "analogy",
    "comparable to",
    "the way that",
]

KNOWN_HOSTS = {
    "Moonshots with Peter Diamandis": ["Peter Diamandis"],
    "Monetary Matters with Jack Farley": ["Jack Farley"],
    "The a16z Show": [],
    "a16z Live": [],
    "All-In Podcast": ["Chamath Palihapitiya", "Jason Calacanis", "David Sacks", "David Friedberg"],
}


class InsufficientQuotaError(Exception):
    """Raised on 429 / insufficient_quota to signal batch stop."""
    pass


def extract_guest_names_from_title(episode_title: str) -> List[str]:
    """Extract guest names from episode title patterns like 'Guest Name: Topic' or 'Guest's Topic'."""
    import re
    guests = []
    
    patterns = [
        r"^([A-Z][a-z]+ [A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)[:\s]+",
        r"^([A-Z][a-z]+'s [A-Z][a-z]+ [A-Z][a-z]+)[:\s]+",
        r"(?:with|featuring|ft\.?|&)\s+([A-Z][a-z]+ [A-Z][a-z]+)",
        r"([A-Z][a-z]+ [A-Z][a-z]+)(?:'s|:)",
    ]
    
    title = episode_title.split("|")[0].strip()
    
    known_title_patterns = [
        (r"Google X's (Astro Teller)", "Astro Teller"),
        (r"([A-Z][a-z]+ [A-Z][a-z]+) on ", None),
        (r"([A-Z][a-z]+ [A-Z][a-z]+): ", None),
    ]
    
    for pattern, fixed_name in known_title_patterns:
        match = re.search(pattern, title)
        if match:
            name = fixed_name or match.group(1)
            if name and len(name.split()) >= 2:
                guests.append(name)
                break
    
    return guests


def collapse_share_class(ticker: str) -> str:
    """Collapse share classes to preferred ticker (GOOG → GOOGL)."""
    ticker = ticker.upper().strip()
    
    share_class_map = {
        "GOOG": "GOOGL",
        "FOXB": "FOXA",
        "NWSB": "NWSA",
        "BRK.B": "BRK.A",
    }
    
    return share_class_map.get(ticker, ticker)


FILLER_CONTEXT_PHRASES = [
    "not a core topic",
    "not the main topic",
    "not the focus",
    "not central",
    "comparison point",
    "natural comparison",
    "benchmark",
    "for reference",
    "as a reference",
    "for context",
    "worth noting",
    "tangentially",
    "indirectly relevant",
    "not directly discussed",
]


def filter_substantive_tickers(
    ticker_mentions: List[Dict],
    companies_and_assets: List[str],
    major_claims: List[str] = None,
    investment_ideas: List[str] = None,
) -> List[Dict]:
    """Filter ticker mentions to only those with substantive speaker discussion.
    
    A ticker is substantive ONLY if:
    - A company that maps to that ticker appears in companies_and_assets, major_claims, or investment_ideas
    
    Drops:
    - Tickers with "no substantive discussion" or filler phrases
    - Tickers mentioned only as analogies (e.g., "like Skunk Works" for LMT)
    - Tickers the model invents as "comparison points" but the speaker never discussed
    """
    if not ticker_mentions:
        return []
    
    companies_text = ""
    for c in (companies_and_assets or []):
        if isinstance(c, str):
            companies_text += " " + c.lower()
        elif isinstance(c, dict):
            companies_text += " " + (c.get("name") or c.get("ticker") or "").lower()
    
    claims_text = " ".join(str(c).lower() for c in (major_claims or []))
    ideas_text = " ".join(str(i).lower() for i in (investment_ideas or []))
    all_text = companies_text + " " + claims_text + " " + ideas_text
    
    filtered = []
    seen_tickers = set()
    
    for tm in ticker_mentions:
        ticker = collapse_share_class(tm.get("ticker") or "")
        if not ticker or ticker in seen_tickers:
            continue
        
        context = (tm.get("context") or "").strip()
        context_lower = context.lower()
        
        no_discussion_phrases = [
            "no substantive discussion",
            "not discussed",
            "not mentioned",
            "passing mention",
            "briefly mentioned",
            "not analyzed",
        ]
        if any(phrase in context_lower for phrase in no_discussion_phrases):
            continue
        
        if any(phrase in context_lower for phrase in FILLER_CONTEXT_PHRASES):
            continue
        
        company_names = TICKER_TO_COMPANIES.get(ticker, [])
        ticker_in_extraction = any(cn in all_text for cn in company_names)
        
        if not ticker_in_extraction:
            ticker_in_extraction = ticker.lower() in all_text
        
        is_analogy_only = any(phrase in context_lower for phrase in ANALOGY_PHRASES)
        if is_analogy_only:
            continue
        
        if ticker_in_extraction:
            tm_copy = dict(tm)
            tm_copy["ticker"] = ticker
            filtered.append(tm_copy)
            seen_tickers.add(ticker)
    
    return filtered


def build_extraction_prompt(
    transcript: str,
    podcast_name: str = "",
    episode_title: str = "",
    episode_date: str = "",
    guest_names: List[str] = None,
    host_names: List[str] = None,
) -> str:
    """Build the full extraction prompt with episode metadata for speaker attribution."""
    
    metadata_block = ""
    
    if podcast_name or episode_title or episode_date:
        metadata_block += "EPISODE METADATA:\n"
        if podcast_name:
            metadata_block += f"- Podcast: {podcast_name}\n"
        if episode_title:
            metadata_block += f"- Episode Title: {episode_title}\n"
        if episode_date:
            metadata_block += f"- Episode Date: {episode_date}\n"
        metadata_block += "\n"
    
    all_guests = list(guest_names or [])
    if not all_guests:
        all_guests = extract_guest_names_from_title(episode_title or "")
    
    all_hosts = list(host_names or [])
    if not all_hosts and podcast_name:
        all_hosts = KNOWN_HOSTS.get(podcast_name, [])
    
    if all_guests or all_hosts:
        metadata_block += "KNOWN SPEAKERS (use these names for attribution when identifiable):\n"
        for g in all_guests:
            metadata_block += f"- Guest: {g}\n"
        for h in all_hosts:
            metadata_block += f"- Host: {h}\n"
        metadata_block += "\n"
    
    prompt = EXTRACTION_PROMPT_BASE
    if metadata_block:
        prompt += metadata_block
    prompt += EXTRACTION_PROMPT_SUFFIX
    prompt += transcript
    
    return prompt


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
    max_tokens: int = 24000,
) -> Tuple[str, int, int, bool]:
    """Call OpenAI for text output. Returns (text, input_tokens, output_tokens, was_truncated).
    
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
            max_completion_tokens=max_tokens,
        )
    except RateLimitError as e:
        if "insufficient_quota" in str(e).lower() or "429" in str(e):
            raise InsufficientQuotaError(f"Rate limit / quota exceeded: {e}")
        raise
    
    content = response.choices[0].message.content or ""
    finish_reason = response.choices[0].finish_reason
    
    was_truncated = finish_reason == "length"
    if was_truncated:
        print(f"    ⚠ Response truncated (finish_reason=length)", flush=True)
    
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    return content, input_tokens, output_tokens, was_truncated


def pass1_extract(
    client,
    transcript: str,
    podcast_name: str = "",
    episode_title: str = "",
    episode_date: str = "",
    guest_names: List[str] = None,
    host_names: List[str] = None,
) -> Tuple[Dict, int, int]:
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
        
        prompt = build_extraction_prompt(
            transcript=chunk,
            podcast_name=podcast_name,
            episode_title=episode_title,
            episode_date=episode_date,
            guest_names=guest_names,
            host_names=host_names,
        )
        
        extraction, inp, out = call_openai_json(client, PASS1_MODEL, prompt)
        extractions.append(extraction)
        total_input += inp
        total_output += out
        
        print(f"      Tokens: {inp:,} in / {out:,} out", flush=True)
    
    merged = merge_extractions(extractions)
    return merged, total_input, total_output


def pass2_synthesize(
    client,
    extraction_json: str,
    podcast_name: str = "",
    extraction_dict: Dict = None,
) -> Tuple[str, Dict, int, int, bool]:
    """Pass 2: Synthesize REAL ALPHA brief + site contract from extraction JSON using mini.
    
    Split into two calls to avoid truncation:
    1. Brief markdown (full REAL ALPHA sections)
    2. Site contract JSON
    
    Never sees the transcript.
    Returns (brief_markdown, site_contract_dict, total_input_tokens, total_output_tokens, was_truncated).
    """
    total_inp = 0
    total_out = 0
    was_truncated = False
    
    prompt_brief = SYNTHESIS_PROMPT + extraction_json
    brief_content, inp1, out1, truncated1 = call_openai_text(
        client, PASS2_MODEL, prompt_brief, max_tokens=12000
    )
    total_inp += inp1
    total_out += out1
    was_truncated = was_truncated or truncated1
    
    print(f"    Pass 2a (brief) tokens: {inp1:,} in / {out1:,} out", flush=True)
    
    prompt_contract = SITE_CONTRACT_PROMPT + extraction_json
    site_contract, inp2, out2 = call_openai_json(client, PASS2_MODEL, prompt_contract)
    total_inp += inp2
    total_out += out2
    
    print(f"    Pass 2b (contract) tokens: {inp2:,} in / {out2:,} out", flush=True)
    
    if extraction_dict:
        ext_guests = extraction_dict.get("guests") or []
        ext_hosts = extraction_dict.get("hosts") or []
        if ext_guests and not site_contract.get("guests"):
            site_contract["guests"] = ext_guests
        if ext_hosts and not site_contract.get("hosts"):
            site_contract["hosts"] = ext_hosts
        
        ext_quotes = extraction_dict.get("high_value_quotes") or []
        if ext_quotes and not site_contract.get("notable_quotes"):
            site_contract["notable_quotes"] = [
                {"speaker": q.get("speaker", ""), "quote": q.get("quote", "")}
                for q in ext_quotes[:3]
                if q.get("speaker") and q.get("quote")
            ]
    
    return brief_content, site_contract, total_inp, total_out, was_truncated


def map_to_site_fields(
    extraction: Dict,
    site_contract: Dict,
    brief_markdown: str,
    episode_title: str = "",
    episode_date: str = "",
) -> Dict:
    """Map REAL ALPHA extraction + synthesis to the site contract fields.
    
    Args:
        extraction: Pass 1 extraction dict
        site_contract: Pass 2 site contract dict
        brief_markdown: Pass 2 REAL ALPHA brief
        episode_title: From DB/sidecar (not model-generated)
        episode_date: From DB/sidecar (not model-generated)
    
    Returns dict compatible with the current analyzer's output format.
    """
    quotes = site_contract.get("notable_quotes") or []
    if not quotes:
        hvq = extraction.get("high_value_quotes") or []
        for q in hvq[:3]:
            if isinstance(q, dict) and q.get("speaker") and q.get("quote"):
                speaker = q["speaker"]
                if speaker.lower().startswith("unidentified") or speaker.lower() in ("guest", "host", "speaker"):
                    continue
                quotes.append({
                    "speaker": speaker[:120],
                    "quote": q["quote"][:400]
                })
    
    raw_ticker_mentions = site_contract.get("ticker_mentions") or []
    companies = extraction.get("companies_and_assets") or []
    major_claims = extraction.get("major_claims") or []
    investment_ideas = extraction.get("investment_ideas") or []
    filtered_tickers = filter_substantive_tickers(raw_ticker_mentions, companies, major_claims, investment_ideas)
    
    for tm in filtered_tickers:
        tm["ticker"] = collapse_share_class(tm.get("ticker", ""))
    
    tickers = []
    seen = set()
    for tm in filtered_tickers:
        t = tm.get("ticker", "")
        if t and t not in seen:
            tickers.append(t)
            seen.add(t)
    
    if not tickers:
        raw_tickers = site_contract.get("key_tickers") or []
        for t in raw_tickers:
            tc = collapse_share_class(t)
            if tc and tc not in seen:
                tickers.append(tc)
                seen.add(tc)
    
    guests = site_contract.get("guests") or extraction.get("guests") or []
    hosts = site_contract.get("hosts") or extraction.get("hosts") or []
    
    result = {
        "episode_title": episode_title or site_contract.get("episode_title", ""),
        "episode_date": episode_date or date.today().isoformat(),
        "summary": site_contract.get("summary") or extraction.get("episode_summary", ""),
        "key_takeaways": site_contract.get("key_takeaways") or [],
        "key_tickers": tickers[:6],
        "investment_thesis": site_contract.get("investment_thesis", ""),
        "notable_quotes": quotes[:3],
        "ticker_mentions": filtered_tickers,
        "emerging_terms": site_contract.get("emerging_terms") or [],
        "guests": guests,
        "hosts": hosts,
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
    episode_title: str = "",
    episode_date: str = "",
    guest_names: List[str] = None,
    host_names: List[str] = None,
) -> Optional[Dict]:
    """Full two-pass analysis. Returns dict compatible with existing analyzer output.
    
    Args:
        client: OpenAI client
        transcript: Full transcript text
        podcast_name: Name of podcast
        episode_id: Episode ID for caching (optional)
        cache: Cache instance (optional)
        episode_title: From DB/sidecar (used for speaker extraction and stored as-is)
        episode_date: From DB/sidecar (used as-is, not model-generated)
        guest_names: Known guest names for attribution
        host_names: Known host names for attribution
    
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
            
            return map_to_site_fields(
                extraction, site_contract, brief_clean,
                episode_title=episode_title, episode_date=episode_date
            )
    
    print(f"    Pass 1: Extracting with {PASS1_MODEL}...", flush=True)
    extraction, p1_in, p1_out = pass1_extract(
        client, transcript,
        podcast_name=podcast_name,
        episode_title=episode_title,
        episode_date=episode_date,
        guest_names=guest_names,
        host_names=host_names,
    )
    
    extraction_json = json.dumps(extraction, indent=2)
    
    print(f"    Pass 2: Synthesizing with {PASS2_MODEL}...", flush=True)
    brief, site_contract, p2_in, p2_out, was_truncated = pass2_synthesize(
        client, extraction_json, podcast_name, extraction_dict=extraction
    )
    
    if was_truncated:
        print(f"    ⚠ Brief may be incomplete - check sections", flush=True)
    
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
    
    result = map_to_site_fields(
        extraction, site_contract, brief,
        episode_title=episode_title, episode_date=episode_date
    )
    
    result["_pass1_input_tokens"] = p1_in
    result["_pass1_output_tokens"] = p1_out
    result["_pass2_input_tokens"] = p2_in
    result["_pass2_output_tokens"] = p2_out
    result["_analysis_cost_usd"] = total_cost
    result["_transcript_sha256"] = sha
    
    return result


def is_two_pass_enabled() -> bool:
    """Check if two-pass mode is enabled via ANALYZER_MODE env var."""
    mode = os.environ.get("ANALYZER_MODE", "").strip().lower()
    return mode == "two_pass"


def get_deepdive_mode() -> str:
    """Get deep dive mode: 'legacy' (gpt-5.5 over transcript) or 'extraction' (gpt-5.4-mini over extraction).
    
    DEEPDIVE_MODE=legacy|extraction, default legacy.
    """
    mode = os.environ.get("DEEPDIVE_MODE", "").strip().lower()
    if mode == "extraction":
        return "extraction"
    return "legacy"


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
