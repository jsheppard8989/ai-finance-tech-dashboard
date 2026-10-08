#!/usr/bin/env python3
"""
Comparison script: Run OLD (legacy) and NEW (two-pass) analyzers on the same episode.

Uses a COPY of the database at /tmp/two-pass-test.db, never touches the live DB.
"""

import json
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

DAEMON_ENV = Path("/Users/jaredsheppard/projects/ai-finance-tech-dashboard/.env")
load_dotenv(DAEMON_ENV)

TEST_DB_PATH = Path("/tmp/two-pass-test.db")
COMPARISON_OUTPUT_DIR = Path("/tmp/two-pass-comparison")
COMPARISON_OUTPUT_DIR.mkdir(exist_ok=True)


def run_legacy_analysis(transcript_path: Path, podcast_name: str) -> dict:
    """Run the legacy single-pass gpt-5.5 analyzer."""
    from openai import OpenAI
    from transcript_window import TRANSCRIPT_WINDOW_CHARS, sample_transcript_window, openai_chat_kwargs
    
    transcript = transcript_path.read_text(encoding="utf-8", errors="ignore")
    transcript_sampled = sample_transcript_window(transcript, TRANSCRIPT_WINDOW_CHARS)
    
    prompt = f"""You are an expert financial analyst and podcast curator. 
Analyze this podcast transcript from "{podcast_name}" and extract structured investment insights.

TRANSCRIPT:
{transcript_sampled}

Please provide your analysis in this exact JSON format:
{{
  "episode_title": "Full episode title",
  "episode_date": "YYYY-MM-DD",
  "summary": "3-5 paragraph recap",
  "key_takeaways": ["5-7 bullets"],
  "key_tickers": ["TICKER1", "TICKER2"],
  "investment_thesis": "ONE sentence under 40 words",
  "notable_quotes": [{{"speaker": "Full Name", "quote": "Verbatim quote"}}],
  "sentiment": "neutral|bullish|bearish",
  "ticker_mentions": [{{"ticker": "TICKER", "context": "...", "sentiment": "neutral", "conviction_score": 75}}],
  "guests": [{{"name": "Full Name", "role": "guest"}}],
  "hosts": [{{"name": "Full Name", "role": "host"}}]
}}

Return ONLY valid JSON."""

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    
    response = client.chat.completions.create(
        model="gpt-5.5",
        messages=[
            {"role": "system", "content": "You are a precise financial analyst. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=16000,
    )
    
    content = response.choices[0].message.content or ""
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    
    cost = (input_tokens / 1_000_000 * 5.00) + (output_tokens / 1_000_000 * 30.00)
    
    parsed = json.loads(content.strip())
    
    return {
        "analysis": parsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "model": "gpt-5.5",
    }


def run_two_pass_analysis(transcript_path: Path, podcast_name: str) -> dict:
    """Run the new two-pass analyzer."""
    from openai import OpenAI
    from two_pass_analyzer import (
        pass1_extract, pass2_synthesize, map_to_site_fields,
        PASS1_MODEL, PASS2_MODEL
    )
    
    transcript = transcript_path.read_text(encoding="utf-8", errors="ignore")
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    
    print("  Running Pass 1 (extraction with nano)...")
    extraction, p1_in, p1_out = pass1_extract(client, transcript)
    extraction_json = json.dumps(extraction, indent=2)
    
    print("  Running Pass 2 (synthesis with mini)...")
    brief, site_contract, p2_in, p2_out = pass2_synthesize(client, extraction_json, podcast_name)
    
    result = map_to_site_fields(extraction, site_contract, brief)
    
    p1_cost = (p1_in / 1_000_000 * 0.20) + (p1_out / 1_000_000 * 1.25)
    p2_cost = (p2_in / 1_000_000 * 0.75) + (p2_out / 1_000_000 * 4.50)
    total_cost = p1_cost + p2_cost
    
    return {
        "analysis": {k: v for k, v in result.items() if not k.startswith("_")},
        "extraction_json": extraction_json,
        "brief_markdown": brief,
        "pass1_input_tokens": p1_in,
        "pass1_output_tokens": p1_out,
        "pass2_input_tokens": p2_in,
        "pass2_output_tokens": p2_out,
        "total_input_tokens": p1_in + p2_in,
        "total_output_tokens": p1_out + p2_out,
        "pass1_cost_usd": p1_cost,
        "pass2_cost_usd": p2_cost,
        "cost_usd": total_cost,
        "model": f"{PASS1_MODEL} + {PASS2_MODEL}",
    }


def generate_comparison_report(
    episode_info: dict,
    legacy_result: dict,
    two_pass_result: dict,
) -> str:
    """Generate a markdown comparison report."""
    
    leg = legacy_result["analysis"]
    tp = two_pass_result["analysis"]
    
    report = f"""# Two-Pass Analyzer Comparison Report

**Generated:** {datetime.now().isoformat()}

**Episode:** {episode_info['podcast_name']} - {episode_info['episode_title']}  
**Episode ID:** {episode_info['id']}  
**Episode Date:** {episode_info['episode_date']}  
**Transcript:** `{episode_info['transcript_path']}`

---

## Cost Comparison

| Metric | Legacy (gpt-5.5) | Two-Pass (nano+mini) | Savings |
|--------|------------------|----------------------|---------|
| Input Tokens | {legacy_result['input_tokens']:,} | {two_pass_result['total_input_tokens']:,} | — |
| Output Tokens | {legacy_result['output_tokens']:,} | {two_pass_result['total_output_tokens']:,} | — |
| **Cost (USD)** | **${legacy_result['cost_usd']:.4f}** | **${two_pass_result['cost_usd']:.4f}** | **{(1 - two_pass_result['cost_usd']/legacy_result['cost_usd'])*100:.1f}%** |

### Two-Pass Breakdown

| Pass | Model | Input Tokens | Output Tokens | Cost |
|------|-------|--------------|---------------|------|
| Pass 1 (Extraction) | {PASS1_MODEL} | {two_pass_result['pass1_input_tokens']:,} | {two_pass_result['pass1_output_tokens']:,} | ${two_pass_result['pass1_cost_usd']:.4f} |
| Pass 2 (Synthesis) | {PASS2_MODEL} | {two_pass_result['pass2_input_tokens']:,} | {two_pass_result['pass2_output_tokens']:,} | ${two_pass_result['pass2_cost_usd']:.4f} |

---

## Side-by-Side: Site Contract Fields

### Headline (Investment Thesis)

**Legacy:**
> {leg.get('investment_thesis', 'N/A')}

**Two-Pass:**
> {tp.get('investment_thesis', 'N/A')}

---

### Summary (Recap)

**Legacy:**
{leg.get('summary', 'N/A')[:1500]}

**Two-Pass:**
{tp.get('summary', 'N/A')[:1500]}

---

### Key Takeaways

**Legacy:**
{chr(10).join(f"- {t}" for t in (leg.get('key_takeaways') or [])[:5])}

**Two-Pass:**
{chr(10).join(f"- {t}" for t in (tp.get('key_takeaways') or [])[:5])}

---

### Notable Quotes (with Speaker Names)

**Legacy:**
{chr(10).join(f'> "{q.get("quote", "")}" — **{q.get("speaker", "Unknown")}**' for q in (leg.get('notable_quotes') or [])[:3])}

**Two-Pass:**
{chr(10).join(f'> "{q.get("quote", "")}" — **{q.get("speaker", "Unknown")}**' for q in (tp.get('notable_quotes') or [])[:3])}

---

### Sentiment

**Legacy:** {leg.get('sentiment', 'N/A')}  
**Two-Pass:** {tp.get('sentiment', 'N/A')}

---

### Key Tickers

**Legacy:** {', '.join(leg.get('key_tickers') or ['None'])}  
**Two-Pass:** {', '.join(tp.get('key_tickers') or ['None'])}

---

### Deep Dive (Ticker Mentions)

**Legacy:**
{chr(10).join(f"- **{tm.get('ticker', 'N/A')}**: {tm.get('context', 'N/A')[:200]}" for tm in (leg.get('ticker_mentions') or [])[:5])}

**Two-Pass:**
{chr(10).join(f"- **{tm.get('ticker', 'N/A')}**: {tm.get('context', 'N/A')[:200]}" for tm in (tp.get('ticker_mentions') or [])[:5])}

---

## REAL ALPHA Brief (Two-Pass Only)

{two_pass_result.get('brief_markdown', 'N/A')[:8000]}

---

## Extraction JSON (Two-Pass Only)

```json
{two_pass_result.get('extraction_json', '{}')}
```

---

## Raw Analysis JSON

### Legacy

```json
{json.dumps(leg, indent=2, default=str)[:6000]}
```

### Two-Pass

```json
{json.dumps(tp, indent=2, default=str)[:6000]}
```
"""
    return report


def main():
    episode_id = 560
    
    conn = sqlite3.connect(str(TEST_DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, podcast_name, episode_title, episode_date, transcript_path FROM podcast_episodes WHERE id = ?",
        (episode_id,)
    ).fetchone()
    conn.close()
    
    if not row:
        print(f"Episode {episode_id} not found in test DB")
        sys.exit(1)
    
    episode_info = dict(row)
    transcript_path = Path(episode_info["transcript_path"])
    
    if not transcript_path.exists():
        print(f"Transcript not found: {transcript_path}")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"COMPARISON: Episode {episode_id}")
    print(f"{'='*60}")
    print(f"Podcast: {episode_info['podcast_name']}")
    print(f"Title: {episode_info['episode_title']}")
    print(f"Transcript: {transcript_path}")
    print()
    
    print("Running LEGACY analyzer (gpt-5.5)...")
    legacy_result = run_legacy_analysis(transcript_path, episode_info['podcast_name'])
    print(f"  Tokens: {legacy_result['input_tokens']:,} in / {legacy_result['output_tokens']:,} out")
    print(f"  Cost: ${legacy_result['cost_usd']:.4f}")
    print()
    
    print("Running TWO-PASS analyzer (nano+mini)...")
    two_pass_result = run_two_pass_analysis(transcript_path, episode_info['podcast_name'])
    print(f"  Total tokens: {two_pass_result['total_input_tokens']:,} in / {two_pass_result['total_output_tokens']:,} out")
    print(f"  Cost: ${two_pass_result['cost_usd']:.4f}")
    print()
    
    savings_pct = (1 - two_pass_result['cost_usd'] / legacy_result['cost_usd']) * 100
    print(f"SAVINGS: {savings_pct:.1f}%")
    print()
    
    report = generate_comparison_report(episode_info, legacy_result, two_pass_result)
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_path = COMPARISON_OUTPUT_DIR / f"two-pass-comparison-{date_str}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report saved: {report_path}")
    
    extraction_path = COMPARISON_OUTPUT_DIR / f"extraction-{date_str}.json"
    extraction_path.write_text(two_pass_result['extraction_json'], encoding="utf-8")
    print(f"Extraction saved: {extraction_path}")
    
    brief_path = COMPARISON_OUTPUT_DIR / f"brief-{date_str}.md"
    brief_path.write_text(two_pass_result['brief_markdown'], encoding="utf-8")
    print(f"Brief saved: {brief_path}")
    
    return {
        "report_path": str(report_path),
        "extraction_path": str(extraction_path),
        "brief_path": str(brief_path),
        "legacy_cost": legacy_result['cost_usd'],
        "two_pass_cost": two_pass_result['cost_usd'],
        "savings_pct": savings_pct,
    }


PASS1_MODEL = "gpt-5.4-nano"
PASS2_MODEL = "gpt-5.4-mini"


if __name__ == "__main__":
    result = main()
    print(f"\nDone. Savings: {result['savings_pct']:.1f}%")
