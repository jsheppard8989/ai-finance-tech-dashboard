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


def _rss_filter_criteria():
    """RSS filter criteria for Pipeline Health (from curate.py / cutoff_date)."""
    try:
        from cutoff_date import CUTOFF_DATE_ISO
    except Exception:
        CUTOFF_DATE_ISO = "2026-02-01"
    try:
        from curate import CURRENT_MONTH_ONLY
    except Exception:
        CURRENT_MONTH_ONLY = True
    criteria = {
        "cutoff_date": CUTOFF_DATE_ISO,
        "approval": "Feed list is the filter. If a feed is in podcast_feeds.txt, all its episodes (within window) are approved. No per-episode relevance score.",
        "feeds": "podcast_feeds.txt; episodes already in DB (by rss_guid) are skipped.",
    }
    if CURRENT_MONTH_ONLY:
        criteria["window"] = "Current calendar month only (forward-looking; no backfill of prior months)."
    else:
        criteria["max_episode_age_days"] = 60
    return criteria


def _export_episode_status(site_dir: Path):
    """Write sanitized episode pipeline status to site/data for Pipeline Health."""
    state_dir = Path(__file__).parent / "state"
    status_path = state_dir / "pipeline_status.json"
    out_path = site_dir / "episode_status.json"
    if not status_path.exists():
        try:
            from curate import get_feed_episodes_not_in_db
            available_from_rss = get_feed_episodes_not_in_db()
        except Exception:
            available_from_rss = []
        try:
            from cutoff_date import CUTOFF_DATE_ISO
        except Exception:
            CUTOFF_DATE_ISO = "2026-02-01"
        payload = {
            "last_updated": None,
            "last_3_completed": [],
            "episodes": [],
            "available_from_rss": available_from_rss,
            "rss_filter_criteria": _rss_filter_criteria(),
            "note": "Run full pipeline (curate → fetch → …) to populate. RSS list = live on feeds, not in DB yet.",
        }
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"  ✓ Exported episode status: 0 in pipeline, 0 completed, {len(available_from_rss)} available from RSS")
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
        # stages_raw already has the canonical per-stage state from pipeline_tracker
        stages = {
            "downloaded": bool((stages_raw.get("downloaded") or {}).get("complete")),
            "transcribed": bool((stages_raw.get("transcribed") or {}).get("complete")),
            "analyzed": bool((stages_raw.get("analyzed") or {}).get("complete")),
            "insight_created": bool((stages_raw.get("insight_created") or {}).get("complete")),
            "published": bool((stages_raw.get("published") or {}).get("complete")),
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
            "status": data.get("status", "unknown"),
        })
    # Sort by published date descending (parse common RSS-style dates)
    def parse_published(s):
        if not s:
            return None
        s = (s or "").strip()
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
        m = re.search(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})", s, re.I)
        if m:
            return (int(m.group(3)), months.get(m.group(2)[:3], 0), int(m.group(1)))
        return (0, 0, 0)
    episodes_out.sort(key=lambda e: parse_published(e.get("published")) or (0, 0, 0), reverse=True)

    # Last 3 completed (all stages ✓) for Pipeline Health
    stage_keys = ["downloaded", "transcribed", "analyzed", "insight_created", "published"]
    completed = [e for e in episodes_out if all((e.get("stages") or {}).get(k) for k in stage_keys)]
    last_3_completed = completed[:3]

    # In-pipeline = all tracked episodes
    in_pipeline = episodes_out

    # Available from RSS but not yet in DB (same age/cutoff as curation; no keyword filter).
    # Deduplicate against in-pipeline episodes so a given episode never appears in both lists.
    def _norm(s: str) -> str:
        return (s or "").strip().lower()

    in_pipeline_keys = {
        (_norm(e.get("podcast", "")), _norm(e.get("title", "")))
        for e in in_pipeline
    }
    try:
        from curate import get_feed_episodes_not_in_db
        raw_available = get_feed_episodes_not_in_db()
        available_from_rss = [
            ep for ep in raw_available
            if (_norm(ep.get("podcast", "")), _norm(ep.get("title", ""))) not in in_pipeline_keys
        ]
    except Exception as ex:
        available_from_rss = []
        print(f"  ⚠ Could not fetch RSS episodes not in DB: {ex}")

    rss_filter_criteria = _rss_filter_criteria()

    payload = {
        "last_updated": raw.get("last_updated"),
        "last_3_completed": last_3_completed,
        "episodes": in_pipeline,
        "available_from_rss": available_from_rss,
        "rss_filter_criteria": rss_filter_criteria,
        "note": "Episodes from curation (approved). Pipeline: curate → fetch → analyze → export. RSS list = live on feeds, not in DB yet.",
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  ✓ Exported episode status: {len(in_pipeline)} in pipeline, {len(last_3_completed)} last completed, {len(available_from_rss)} available from RSS")


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
