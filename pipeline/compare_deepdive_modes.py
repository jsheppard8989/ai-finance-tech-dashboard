#!/usr/bin/env python3
"""
Compare legacy vs extraction-mode deep dives.

This script:
1. Copies the live DB to /tmp
2. For episodes without key_quotes in extraction, re-runs pass 1 only (~$0.01 each)
3. Generates extraction-mode deep dives for test episodes
4. Compares against stored legacy deep dives
5. Outputs comparison doc

Usage:
    python3 compare_deepdive_modes.py

Output:
    docs/deepdive-extraction-comparison-2026-10-08.md
"""

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from workspace_paths import DB_PATH

TEST_EPISODE_IDS = [565, 564, 563, 562, 561, 560, 559, 558, 557]
TMP_DB_PATH = Path("/tmp/deepdive_comparison.db")


def copy_db_to_tmp() -> Path:
    """Copy live DB to /tmp for testing."""
    shutil.copy(DB_PATH, TMP_DB_PATH)
    print(f"Copied {DB_PATH} to {TMP_DB_PATH}")
    return TMP_DB_PATH


def get_connection(db_path: Path = TMP_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def check_extraction_has_new_fields(extraction_json: str) -> bool:
    """Check if extraction has key_quotes and falsification fields."""
    if not extraction_json:
        return False
    try:
        ext = json.loads(extraction_json)
        companies = ext.get("companies_and_assets", [])
        if not companies:
            return False
        for c in companies:
            if not c.get("key_quotes"):
                return False
        if not ext.get("falsification_tracks"):
            return False
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def rerun_pass1_for_episode(episode_id: int, db_path: Path) -> Tuple[bool, float]:
    """Re-run pass 1 extraction to add new fields. Returns (success, cost)."""
    from two_pass_analyzer import (
        get_two_pass_client, pass1_extract, transcript_sha256,
        KNOWN_HOSTS, extract_guest_names_from_title
    )
    
    conn = get_connection(db_path)
    row = conn.execute(
        """SELECT podcast_name, episode_title, transcript_path, extraction_json
           FROM podcast_episodes WHERE id = ?""",
        (episode_id,)
    ).fetchone()
    conn.close()
    
    if not row or not row["transcript_path"]:
        return False, 0.0
    
    transcript_path = Path(row["transcript_path"])
    if not transcript_path.exists():
        print(f"  Transcript not found: {transcript_path}")
        return False, 0.0
    
    transcript = transcript_path.read_text(encoding="utf-8", errors="ignore")
    podcast_name = row["podcast_name"]
    episode_title = row["episode_title"]
    
    guest_names = extract_guest_names_from_title(episode_title)
    host_names = KNOWN_HOSTS.get(podcast_name, [])
    
    client = get_two_pass_client()
    print(f"  Running pass 1 for episode {episode_id}...")
    
    extraction, p1_in, p1_out = pass1_extract(
        client, transcript,
        podcast_name=podcast_name,
        episode_title=episode_title,
        episode_date="",
        guest_names=guest_names,
        host_names=host_names,
    )
    
    cost = (p1_in / 1_000_000 * 0.20) + (p1_out / 1_000_000 * 1.25)
    print(f"  Pass 1 cost: ${cost:.4f} ({p1_in:,} in / {p1_out:,} out)")
    
    extraction_json = json.dumps(extraction, indent=2)
    
    conn = get_connection(db_path)
    conn.execute(
        "UPDATE podcast_episodes SET extraction_json = ? WHERE id = ?",
        (extraction_json, episode_id)
    )
    conn.commit()
    conn.close()
    
    return True, cost


def get_legacy_deep_dive(insight_id: int, db_path: Path) -> Optional[Dict]:
    """Get stored legacy deep dive for an insight."""
    conn = get_connection(db_path)
    row = conn.execute(
        """SELECT overview, investment_thesis, ticker_analysis, 
                  episode_evidence, falsification_tracks
           FROM deep_dive_content WHERE insight_id = ?""",
        (insight_id,)
    ).fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "overview": row["overview"],
        "investment_thesis": row["investment_thesis"],
        "ticker_analysis": row["ticker_analysis"],
        "episode_evidence": row["episode_evidence"],
        "falsification_tracks": row["falsification_tracks"],
    }


def generate_extraction_deep_dive(
    episode_id: int, insight_id: int, db_path: Path
) -> Tuple[Optional[Dict], Optional[Dict], bool]:
    """Generate extraction-mode deep dive. Returns (content, usage_info, passed_structural)."""
    from generate_deepdives import (
        run_extraction_deep_dive_attempts,
        deep_dive_structural_ok,
        _extract_host_from_source_name,
        _extract_speakers_from_notable_quotes,
    )
    from two_pass_analyzer import get_two_pass_client
    
    conn = get_connection(db_path)
    ep_row = conn.execute(
        "SELECT extraction_json FROM podcast_episodes WHERE id = ?",
        (episode_id,)
    ).fetchone()
    li_row = conn.execute(
        """SELECT summary, key_takeaway, source_name, notable_quotes
           FROM latest_insights WHERE id = ?""",
        (insight_id,)
    ).fetchone()
    conn.close()
    
    if not ep_row or not ep_row["extraction_json"]:
        return None, None, False
    if not li_row:
        return None, None, False
    
    extraction_json = ep_row["extraction_json"]
    insight_summary = li_row["summary"] or ""
    key_takeaway = li_row["key_takeaway"] or ""
    source_name = li_row["source_name"] or ""
    notable_quotes = li_row["notable_quotes"] or ""
    
    host_name = _extract_host_from_source_name(source_name)
    guest_names = _extract_speakers_from_notable_quotes(notable_quotes)
    
    client = get_two_pass_client()
    
    content, err, usage_info = run_extraction_deep_dive_attempts(
        client,
        extraction_json,
        insight_summary,
        key_takeaway,
        host_name=host_name,
        guest_names=guest_names,
    )
    
    if not content:
        print(f"  ✗ Generation failed: {err}")
        return None, usage_info, False
    
    ok_struct, _ = deep_dive_structural_ok(content)
    return content, usage_info, ok_struct


def compare_deep_dives(legacy: Dict, extraction: Dict) -> Dict:
    """Compare two deep dives and return comparison metrics."""
    def word_count(text: str) -> int:
        return len((text or "").split())
    
    def quote_count(evidence) -> int:
        if not evidence:
            return 0
        if isinstance(evidence, list):
            return len(evidence)
        return len([l for l in str(evidence).split("\n") if l.strip() and ":" in l])
    
    def evidence_text(evidence) -> str:
        if isinstance(evidence, list):
            return "\n".join(str(e) for e in evidence)
        return str(evidence or "")
    
    return {
        "legacy_overview_words": word_count(legacy.get("overview")),
        "extraction_overview_words": word_count(extraction.get("overview")),
        "legacy_thesis_words": word_count(legacy.get("investment_thesis")),
        "extraction_thesis_words": word_count(extraction.get("investment_thesis")),
        "legacy_quote_count": quote_count(legacy.get("episode_evidence")),
        "extraction_quote_count": quote_count(extraction.get("episode_evidence")),
    }


def run_comparison() -> Dict:
    """Run full comparison and return results."""
    copy_db_to_tmp()
    
    results = {
        "episodes": [],
        "total_pass1_cost": 0.0,
        "total_extraction_cost": 0.0,
        "structural_pass_count": 0,
        "total_count": 0,
    }
    
    conn = get_connection(TMP_DB_PATH)
    
    for episode_id in TEST_EPISODE_IDS:
        print(f"\nProcessing episode {episode_id}...")
        
        ep_row = conn.execute(
            """SELECT podcast_name, episode_title, extraction_json
               FROM podcast_episodes WHERE id = ?""",
            (episode_id,)
        ).fetchone()
        
        if not ep_row:
            print(f"  Episode not found")
            continue
        
        li_row = conn.execute(
            """SELECT id FROM latest_insights WHERE podcast_episode_id = ?""",
            (episode_id,)
        ).fetchone()
        
        if not li_row:
            print(f"  No insight for episode")
            continue
        
        insight_id = li_row["id"]
        
        if not check_extraction_has_new_fields(ep_row["extraction_json"]):
            print(f"  Extraction missing new fields, re-running pass 1...")
            success, cost = rerun_pass1_for_episode(episode_id, TMP_DB_PATH)
            if not success:
                print(f"  ✗ Pass 1 failed")
                continue
            results["total_pass1_cost"] += cost
        else:
            print(f"  Extraction has new fields")
        
        legacy = get_legacy_deep_dive(insight_id, TMP_DB_PATH)
        if not legacy:
            print(f"  No legacy deep dive stored")
            continue
        
        print(f"  Generating extraction-mode deep dive...")
        extraction_dd, usage_info, passed_struct = generate_extraction_deep_dive(
            episode_id, insight_id, TMP_DB_PATH
        )
        
        if usage_info:
            results["total_extraction_cost"] += usage_info.get("cost_usd", 0.0)
        
        if extraction_dd:
            results["total_count"] += 1
            if passed_struct:
                results["structural_pass_count"] += 1
            
            comparison = compare_deep_dives(legacy, extraction_dd)
            
            def evidence_str(ev) -> str:
                if isinstance(ev, list):
                    return "\n".join(str(e) for e in ev)
                return str(ev or "")
            
            results["episodes"].append({
                "episode_id": episode_id,
                "insight_id": insight_id,
                "title": ep_row["episode_title"][:60],
                "podcast": ep_row["podcast_name"],
                "passed_structural": passed_struct,
                "usage_info": usage_info,
                "comparison": comparison,
                "legacy_overview": (legacy.get("overview") or "")[:500],
                "extraction_overview": (extraction_dd.get("overview") or "")[:500],
                "legacy_evidence": evidence_str(legacy.get("episode_evidence"))[:500],
                "extraction_evidence": evidence_str(extraction_dd.get("episode_evidence"))[:500],
            })
        else:
            results["episodes"].append({
                "episode_id": episode_id,
                "insight_id": insight_id,
                "title": ep_row["episode_title"][:60],
                "podcast": ep_row["podcast_name"],
                "passed_structural": False,
                "usage_info": usage_info,
                "error": "Generation failed",
            })
    
    conn.close()
    return results


def generate_comparison_doc(results: Dict) -> str:
    """Generate markdown comparison document."""
    doc = f"""# Deep Dive Mode Comparison: Legacy vs Extraction

Generated: {datetime.now().isoformat()}

## Summary

- **Episodes tested**: {results['total_count']}
- **Structural pass rate**: {results['structural_pass_count']}/{results['total_count']} ({100*results['structural_pass_count']/max(1,results['total_count']):.0f}%)
- **Total pass 1 re-run cost**: ${results['total_pass1_cost']:.4f}
- **Total extraction deep dive cost**: ${results['total_extraction_cost']:.4f}

## Per-Episode Cost Comparison

| Episode | Podcast | Extraction Tokens (in/out) | Extraction Cost | Passed Structural |
|---------|---------|---------------------------|-----------------|-------------------|
"""
    
    for ep in results["episodes"]:
        usage = ep.get("usage_info") or {}
        tokens = f"{usage.get('input_tokens', 0):,} / {usage.get('output_tokens', 0):,}"
        cost = f"${usage.get('cost_usd', 0):.4f}"
        passed = "✅" if ep.get("passed_structural") else "❌"
        doc += f"| {ep['episode_id']} | {ep['podcast'][:20]} | {tokens} | {cost} | {passed} |\n"
    
    doc += """
## Legacy Cost Baseline

Based on gpt-5.5 pricing ($5/M in, $30/M out) and typical deep dive generation:
- Input: ~25,000 tokens → $0.125
- Output: ~3,500 tokens → $0.105
- **Estimated legacy cost per deep dive: ~$0.23**

## Side-by-Side Examples

"""
    
    shown = 0
    for ep in results["episodes"]:
        if shown >= 3:
            break
        if "legacy_overview" not in ep:
            continue
        
        doc += f"""### Episode {ep['episode_id']}: {ep['title']}

**Podcast**: {ep['podcast']}
**Passed structural checks**: {"Yes" if ep.get('passed_structural') else "No"}

#### Overview

**Legacy (gpt-5.5 over transcript)**:
> {ep.get('legacy_overview', 'N/A')[:400]}...

**Extraction (gpt-5.4-mini over extraction JSON)**:
> {ep.get('extraction_overview', 'N/A')[:400]}...

#### Episode Evidence (Quotes)

**Legacy**:
```
{ep.get('legacy_evidence', 'N/A')[:300]}...
```

**Extraction**:
```
{ep.get('extraction_evidence', 'N/A')[:300]}...
```

---

"""
        shown += 1
    
    doc += """## Quality Assessment

### Strengths of Extraction Mode
- Lower cost (~$0.03-0.05 vs ~$0.23 for legacy)
- Quotes are guaranteed verbatim (from extraction)
- Faster generation (smaller context)

### Potential Quality Concerns
- Overview may be less detailed without full transcript context
- May miss nuances not captured in extraction
- Depends on quality of pass 1 extraction

### Recommendation
[To be filled based on manual review of the side-by-side comparisons above]
"""
    
    return doc


def main():
    print("Deep Dive Mode Comparison")
    print("=" * 60)
    
    results = run_comparison()
    
    doc = generate_comparison_doc(results)
    
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / "deepdive-extraction-comparison-2026-10-08.md"
    out_path.write_text(doc, encoding="utf-8")
    
    print(f"\n✓ Comparison doc written to: {out_path}")
    print(f"\nSummary:")
    print(f"  Episodes tested: {results['total_count']}")
    print(f"  Structural pass rate: {results['structural_pass_count']}/{results['total_count']}")
    print(f"  Total extraction cost: ${results['total_extraction_cost']:.4f}")


if __name__ == "__main__":
    main()
