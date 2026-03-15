#!/usr/bin/env python3
"""
Standalone data export script for website updates.
Called by cron job for midday price refreshes.
"""

import re
import sys
from pathlib import Path
from datetime import datetime
import json

# Add pipeline directory to path
sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db


def export_website_data():
    """Export data for website."""
    print("="*60)
    print("Exporting Website Data")
    print("="*60)
    
    db = get_db()
    site_dir = Path.home() / ".openclaw/workspace/site/data"
    site_dir.mkdir(parents=True, exist_ok=True)
    
    stats = db.export_for_website(site_dir)
    print(f"✓ Exported: {stats}")

    # Main-page section counts (same content that feeds the three dashboard sections)
    main_content = db.get_main_page_content()
    main_page = {
        "overton": len(main_content.get("overton", [])),
        "insights": len(main_content.get("insights", [])),
        "pundits": stats.get("pundits", 0),
    }

    # Write a lightweight status.json for frontend health display
    status = {
        "last_pipeline_run": datetime.now().isoformat(),
        "last_steps": {
            "podcasts_analyzed": stats.get("podcast_summaries", 0),
            "overton_terms": db.get_stats().get("overton_terms_total", 0) if hasattr(db, "get_stats") else 0,
            "pundits": stats.get("pundits", 0),
        },
        "main_page": main_page,
        "counts": db.get_stats() if hasattr(db, "get_stats") else {}
    }
    with open(site_dir / "status.json", "w") as f:
        json.dump(status, f, indent=2, default=str)

    # Export episode pipeline status for Pipeline Health (sanitized: no local paths)
    _export_episode_status(site_dir)

    return stats


def _export_episode_status(site_dir: Path):
    """Write sanitized episode pipeline status to site/data for Pipeline Health."""
    state_dir = Path(__file__).parent / "state"
    status_path = state_dir / "pipeline_status.json"
    out_path = site_dir / "episode_status.json"
    if not status_path.exists():
        with open(out_path, "w") as f:
            json.dump({"last_updated": None, "episodes": [], "note": "Run full pipeline to populate."}, f, indent=2)
        return
    try:
        with open(status_path, "r") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"  ⚠ Could not read pipeline_status.json: {e}")
        return
    episodes_in = raw.get("episodes") or {}
    episodes_out = []
    for ep_id, data in episodes_in.items():
        info = data.get("info") or {}
        stages_raw = data.get("stages") or {}
        stages = {
            "downloaded": bool(stages_raw.get("downloaded", {}).get("complete")),
            "transcribed": bool(stages_raw.get("transcribed", {}).get("complete")),
            "analyzed": bool(stages_raw.get("analyzed", {}).get("complete")),
            "insight_created": bool(stages_raw.get("insight_created", {}).get("complete")),
            "published": bool(stages_raw.get("published", {}).get("complete")),
        }
        stage_reasons = {}
        for stage_name in ["downloaded", "transcribed", "analyzed", "insight_created", "published"]:
            r = (stages_raw.get(stage_name) or {}).get("reason")
            if r:
                stage_reasons[stage_name] = r
        episodes_out.append({
            "id": ep_id,
            "podcast": info.get("podcast", ""),
            "title": info.get("title", ""),
            "published": info.get("published", ""),
            "stages": stages,
            "stage_reasons": stage_reasons,
        })
    # Sort by published date descending (parse common RSS-style dates)
    def parse_published(s):
        if not s:
            return None
        s = (s or "").strip()
        # Try "03 Feb 2026" or "2026-02-03" or "Wed, 11 Feb 2026 22:46:00 -0000"
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
        m = re.search(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})", s, re.I)
        if m:
            return (int(m.group(3)), months.get(m.group(2)[:3], 0), int(m.group(1)))
        return (0, 0, 0)
    episodes_out.sort(key=lambda e: parse_published(e.get("published")) or (0, 0, 0), reverse=True)
    payload = {
        "last_updated": raw.get("last_updated"),
        "episodes": episodes_out,
        "note": "Episodes from curation (approved). Pipeline: curate → fetch → analyze → export.",
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  ✓ Exported episode status: {len(episodes_out)} episodes")


def generate_website_js():
    """Generate JavaScript file with data for website."""
    print("\n" + "="*60)
    print("Generating Website JavaScript")
    print("="*60)
    
    db = get_db()
    site_dir = Path.home() / ".openclaw/workspace/site/data"
    
    # Get all data including archive
    archive = db.export_archive_data()
    main_content = db.get_main_page_content()
    deepdives = db.get_all_deep_dive_content()
    suggested_terms = db.get_suggested_terms_for_website(limit=4)
    podcast_guests = db.get_podcast_guests_for_site(limit=20)
    # Load pundits (semantic layer) from JSON exported by export_for_website
    pundits_path = site_dir / "pundits.json"
    try:
        with open(pundits_path, "r") as f:
            pundits = json.load(f)
    except FileNotFoundError:
        pundits = []

    # Chart metadata for cache-busting
    charts_version = None
    last_chart_run_path = Path.home() / ".openclaw/workspace/pipeline/state/last_chart_run.json"
    if last_chart_run_path.exists():
        try:
            with open(last_chart_run_path, "r") as f:
                meta = json.load(f)
            charts_version = meta.get("timestamp")
        except Exception:
            charts_version = None

    # Load ticker scores
    try:
        with open(site_dir / 'ticker_scores.json', 'r') as f:
            ticker_scores = json.load(f)
    except FileNotFoundError:
        ticker_scores = []
    
    # Generate data.js that the HTML can load
    # Pre-serialize to avoid f-string issues
    ticker_json = json.dumps(ticker_scores, indent=2)
    archive_json = json.dumps(archive, indent=2)
    main_json = json.dumps(main_content, indent=2)
    deepdives_json = json.dumps(deepdives, indent=2)
    suggested_json = json.dumps(suggested_terms, indent=2)
    podcast_guests_json = json.dumps(podcast_guests, indent=2)
    pundits_json = json.dumps(pundits, indent=2)

    schema_version = 2

    js_content = f"""// Auto-generated data file
// DO NOT EDIT MANUALLY

const dashboardData = {{
  schemaVersion: {schema_version},
  generatedAt: "{datetime.now().isoformat()}",
  chartsVersion: {json.dumps(charts_version) if 'charts_version' in locals() else 'null'},
  tickerScores: {ticker_json},
  archive: {archive_json},
  mainContent: {main_json},
  deepDives: {deepdives_json},
  suggestedTerms: {suggested_json},
  podcastGuests: {podcast_guests_json},
  pundits: {pundits_json}
}};

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {{
  module.exports = dashboardData;
}}
"""
    
    with open(site_dir / 'data.js', 'w') as f:
        f.write(js_content)
    
    total_archive = sum(len(v) for v in archive.values() if isinstance(v, list))
    print(f"✓ Generated data.js with {len(ticker_scores)} tickers, {total_archive} archive items, {len(deepdives)} deep dives, {len(suggested_terms)} suggested terms, {len(podcast_guests)} legacy guests, {len(pundits)} pundits; chartsVersion={charts_version}")
    return True


def main():
    """Run data export."""
    print(f"Data Export Started: {datetime.now()}")
    
    export_website_data()
    generate_website_js()
    
    print(f"\n✓ Data export complete")


if __name__ == "__main__":
    main()
