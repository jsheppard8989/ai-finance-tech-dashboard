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
import sqlite3

# Add pipeline directory to path
sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db


def _refresh_pipeline_tracker() -> None:
    """
    Keep pipeline_status.json fresh before exporting episode_status.json.
    Without this, the health page can show stale stage data for days.
    """
    try:
        from pipeline_tracker import PodcastPipelineTracker
        tracker = PodcastPipelineTracker()
        tracker.scan_pipeline()
    except Exception as e:
        print(f"  ⚠ Could not refresh pipeline tracker before export: {e}")


def _count_podcasts_analyzed_today() -> int:
    """
    Return count of podcast_episodes rows created today (local date).
    Used for status.json last_steps so notifications are per-run/day, not lifetime totals.
    """
    db_path = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM podcast_episodes
            WHERE date(created_at, 'localtime') = date('now', 'localtime')
            """
        )
        n = int(cursor.fetchone()[0] or 0)
        conn.close()
        return n
    except Exception:
        return 0


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
            # Per-day run signal (not lifetime total), so health/notifications stay truthful.
            "podcasts_analyzed": _count_podcasts_analyzed_today(),
            "overton_terms": db.get_stats().get("overton_terms_total", 0) if hasattr(db, "get_stats") else 0,
            "pundits": stats.get("pundits", 0),
        },
        "main_page": main_page,
        "counts": db.get_stats() if hasattr(db, "get_stats") else {}
    }
    with open(site_dir / "status.json", "w") as f:
        json.dump(status, f, indent=2, default=str)

    # Export episode pipeline status for Pipeline Health (legacy file).
    _export_episode_status(site_dir)

    # Export canonical pipeline state used by Pipeline Health (single source).
    _export_pipeline_state(site_dir)

    return stats


def _parse_iso_date_prefix(s: str):
    """Extract YYYY-MM-DD from many possible date strings."""
    if not s:
        return None
    s = str(s).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    return None


def _export_pipeline_state(site_dir: Path):
    """
    Canonical pipeline export consumed by `site/pipeline-health.html`.

    Design goal:
    - Episodes selection comes from `pipeline/state/curation_log.json` approvals.
    - Stage completion comes ONLY from DB rows (`podcast_episodes`, `latest_insights`).
    - No artifact-based inference (no substring search in data.js, no tracker snapshot dependency).
    """
    from db_manager import get_db

    state_dir = Path(__file__).parent / "state"
    curated_path = state_dir / "curation_log.json"
    rss_filter_criteria = _rss_filter_criteria()

    generated_at = datetime.now().isoformat()
    last_updated = generated_at

    # Load curated approvals (episodes Clawbot should be processing).
    curated_eps = []
    if curated_path.exists():
        try:
            curated = json.loads(curated_path.read_text(encoding="utf-8"))
            for ep in curated.get("episodes", []):
                if ep.get("status") != "APPROVED":
                    continue
                curated_eps.append(ep)
        except Exception:
            curated_eps = []

    # DB lookups
    db = get_db()
    episode_rows_by_guid = {}
    insights_by_episode_id = {}
    try:
        with db._get_connection() as conn:
            # Fetch all podcast_episodes rows for curated rss_guids in one shot.
            guids = [str(ep.get("rss_guid") or "").strip() for ep in curated_eps if ep.get("rss_guid")]
            guids = sorted(set([g for g in guids if g]))
            if guids:
                # SQLite parameter limit safety not needed for small windows.
                q_marks = ",".join(["?"] * len(guids))
                cur = conn.execute(
                    f"""
                    SELECT id, rss_guid, podcast_name, episode_title, episode_date,
                           audio_url, transcript_path, is_processed, added_to_site
                    FROM podcast_episodes
                    WHERE rss_guid IN ({q_marks})
                    """,
                    guids,
                )
                for row in cur.fetchall():
                    r = dict(row)
                    episode_rows_by_guid[str(r.get("rss_guid") or "")] = r

                # Fetch insight existence for all matched episode ids.
                ep_ids = [int(r["id"]) for r in episode_rows_by_guid.values() if r.get("id") is not None]
                if ep_ids:
                    q_marks = ",".join(["?"] * len(ep_ids))
                    cur2 = conn.execute(
                        f"""
                        SELECT podcast_episode_id, COUNT(*) as c
                        FROM latest_insights
                        WHERE podcast_episode_id IN ({q_marks})
                        GROUP BY podcast_episode_id
                        """,
                        ep_ids,
                    )
                    for row2 in cur2.fetchall():
                        rr = dict(row2)
                        insights_by_episode_id[int(rr["podcast_episode_id"])] = int(rr["c"] or 0)
    except Exception as e:
        print(f"  ⚠ Could not build pipeline_state from DB: {e}")

    def derive_status(downloaded: bool, transcribed: bool, analyzed: bool, insight_created: bool, published: bool) -> str:
        if not downloaded:
            return "needs_download"
        if not transcribed:
            return "needs_transcription"
        if not analyzed:
            return "needs_analysis"
        if not insight_created:
            return "needs_insight"
        if not published:
            return "needs_export"
        return "complete"

    def stage_reason_missing(missing_stage: str, has_db_row: bool) -> str:
        if not has_db_row:
            return "Not in DB yet (approved, but not pulled into pipeline DB)."
        # DB row exists; reason depends on stage.
        mapping = {
            "downloaded": "audio_url missing (fetch step not reflected in DB yet).",
            "transcribed": "transcript_path missing (transcribe step not reflected in DB yet).",
            "analyzed": "is_processed=0 (analysis step not reflected in DB yet).",
            "insight_created": "No latest_insights row for this episode (insight step not reflected in DB yet).",
            "published": "added_to_site=0 (export/publish step not reflected in DB yet).",
        }
        return mapping.get(missing_stage, "Missing stage.")

    # Build episode objects
    episodes_out = []
    stale_threshold_days = 2
    stale_episodes = []

    def compute_age_days(pub_str: str):
        tup = _parse_iso_date_prefix(pub_str)
        if not tup:
            return None
        try:
            from datetime import date

            pub_d = date(tup[0], tup[1], tup[2])
            return (date.today() - pub_d).days
        except Exception:
            return None

    stage_counts = {
        "downloaded": 0,
        "transcribed": 0,
        "analyzed": 0,
        "insight_created": 0,
        "published": 0,
        "total": len(curated_eps),
    }

    for ep in curated_eps:
        podcast = ep.get("podcast", "") or ""
        title = ep.get("title", "") or ""
        rss_guid = (ep.get("rss_guid") or "").strip()
        published_str = ep.get("published_date") or ep.get("published") or ""
        age_days = compute_age_days(published_str)

        pe = episode_rows_by_guid.get(rss_guid) if rss_guid else None
        has_db_row = bool(pe)
        podcast_episode_id = int(pe["id"]) if pe and pe.get("id") is not None else None

        audio_url = (pe.get("audio_url") or "") if pe else ""
        transcript_path = (pe.get("transcript_path") or "") if pe else ""
        is_processed = bool(pe.get("is_processed")) if pe else False
        added_to_site = bool(pe.get("added_to_site")) if pe else False

        downloaded = bool(audio_url) or bool(transcript_path)
        transcribed = bool(transcript_path)
        analyzed = is_processed
        insight_created = False
        if podcast_episode_id is not None:
            insight_created = bool(insights_by_episode_id.get(podcast_episode_id, 0) > 0)
        published = added_to_site

        # Stage reasons (deterministic, DB-based)
        st_reasons = {}
        if not downloaded:
            st_reasons["downloaded"] = stage_reason_missing("downloaded", has_db_row)
        if not transcribed:
            st_reasons["transcribed"] = stage_reason_missing("transcribed", has_db_row)
        if not analyzed:
            st_reasons["analyzed"] = stage_reason_missing("analyzed", has_db_row)
        if not insight_created:
            st_reasons["insight_created"] = stage_reason_missing("insight_created", has_db_row)
        if not published:
            st_reasons["published"] = stage_reason_missing("published", has_db_row)

        status = derive_status(downloaded, transcribed, analyzed, insight_created, published)
        ep_key = rss_guid if rss_guid else f"{podcast}_{title[:40]}".replace(" ", "_").lower()

        # Increment stage counts
        if downloaded:
            stage_counts["downloaded"] += 1
        if transcribed:
            stage_counts["transcribed"] += 1
        if analyzed:
            stage_counts["analyzed"] += 1
        if insight_created:
            stage_counts["insight_created"] += 1
        if published:
            stage_counts["published"] += 1

        episodes_out.append(
            {
                "id": ep_key,
                "podcast": podcast,
                "title": pe.get("episode_title") if pe and pe.get("episode_title") else title,
                "published": published_str,
                "rss_guid": rss_guid,
                "stages": {
                    "downloaded": downloaded,
                    "transcribed": transcribed,
                    "analyzed": analyzed,
                    "insight_created": insight_created,
                    "published": published,
                },
                "stage_reasons": st_reasons,
                "status": status,
            }
        )

        if status != "complete" and age_days is not None and age_days >= stale_threshold_days:
            blocker = next((k for k in ["downloaded", "transcribed", "analyzed", "insight_created", "published"] if not (episodes_out[-1]["stages"].get(k))), "unknown")
            stale_episodes.append(
                {
                    "id": ep_key,
                    "podcast": podcast,
                    "title": episodes_out[-1]["title"],
                    "status": status,
                    "published": published_str,
                    "age_days": age_days,
                    "next_blocker": blocker,
                }
            )

    # New on feeds: RSS-only episodes not yet in curation/db pipeline selection.
    # We preserve existing curate/filter logic (window + feeds list) by using the helper.
    curated_guid_set = {str(ep.get("rss_guid") or "").strip() for ep in curated_eps if ep.get("rss_guid")}
    try:
        from curate import get_feed_episodes_not_in_db

        raw_available = get_feed_episodes_not_in_db()
        available_from_rss = []
        for ep in raw_available:
            g = (ep.get("rss_guid") or "").strip() if isinstance(ep, dict) else ""
            if g and g in curated_guid_set:
                continue
            available_from_rss.append(
                {
                    "podcast": ep.get("podcast", ""),
                    "title": ep.get("title", ""),
                    "published": ep.get("published", "") or ep.get("published_date", ""),
                    "published_date": ep.get("published_date", ""),
                    "rss_guid": ep.get("rss_guid", ""),
                }
            )
    except Exception:
        available_from_rss = []

    # main-page tie-out and counts (keep dashboard consistent)
    try:
        main_content = db.get_main_page_content()
        main_page = {
            "overton": len(main_content.get("overton", [])),
            "insights": len(main_content.get("insights", [])),
            "pundits": main_content.get("pundits", 0),
        }
    except Exception:
        main_page = {"overton": 0, "insights": 0, "pundits": 0}

    try:
        counts = db.get_stats()
    except Exception:
        counts = {}
    # Health dashboard expects a "podcasts_analyzed" key for tie-out counts.
    # This should be a per-day signal (not lifetime totals).
    try:
        counts["podcasts_analyzed"] = _count_podcasts_analyzed_today()
    except Exception:
        counts["podcasts_analyzed"] = 0

    payload = {
        "generated_at": generated_at,
        "last_updated": last_updated,
        "last_pipeline_run": generated_at,
        "main_page": main_page,
        "counts": counts,
        "step_results": {
            # stage_counts as integers
            "downloaded": stage_counts["downloaded"],
            "transcribed": stage_counts["transcribed"],
            "analyzed": stage_counts["analyzed"],
            "insight_created": stage_counts["insight_created"],
            "published": stage_counts["published"],
            "total": stage_counts["total"],
        },
        "episodes": episodes_out,
        "available_from_rss": available_from_rss,
        "stale_episodes": stale_episodes,
        "stale_threshold_days": stale_threshold_days,
        "rss_filter_criteria": rss_filter_criteria,
        "note": "Canonical pipeline_state built from DB rows + curation approvals. Stage completion is deterministic.",
    }

    site_dir.mkdir(parents=True, exist_ok=True)
    out_path = site_dir / "pipeline_state.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  ✓ Exported pipeline_state.json: {len(episodes_out)} tracked · {len(available_from_rss)} rss-only")


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
    _refresh_pipeline_tracker()
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

    # Promote "new on feeds" into stage table as trackable placeholders so nothing is invisible.
    # These rows reflect pre-download state and let Clawbot see them in one unified list.
    tracked_feed_placeholders = []
    for ep in available_from_rss:
        ep_id = f"rss::{_norm(ep.get('podcast', ''))}::{_norm(ep.get('title', ''))}"[:180]
        tracked_feed_placeholders.append({
            "id": ep_id,
            "podcast": ep.get("podcast", ""),
            "title": ep.get("title", ""),
            "published": ep.get("published", ""),
            "stages": {
                "downloaded": False,
                "transcribed": False,
                "analyzed": False,
                "insight_created": False,
                "published": False,
            },
            "stage_reasons": {
                "downloaded": "Discovered on RSS feed; not yet pulled into curation/pipeline state.",
                "transcribed": "Waiting for download first.",
                "analyzed": "Waiting for transcript first.",
                "insight_created": "Depends on analyze step first.",
                "published": "Not on site until export after analysis and insight promotion.",
            },
            "status": "needs_download",
        })

    # Detect stale/stuck tracked episodes for heartbeat and operator visibility.
    stale_threshold_days = 2
    stale_episodes = []
    for ep in in_pipeline:
        st = ep.get("stages") or {}
        if all(st.get(k) for k in ["downloaded", "transcribed", "analyzed", "insight_created", "published"]):
            continue
        age = None
        pub_tuple = parse_published(ep.get("published", ""))
        try:
            from datetime import date
            if pub_tuple and pub_tuple != (0, 0, 0):
                pub_d = date(pub_tuple[0], pub_tuple[1], pub_tuple[2])
                age = (date.today() - pub_d).days
        except Exception:
            age = None
        if age is not None and age >= stale_threshold_days:
            stale_episodes.append({
                "id": ep.get("id", ""),
                "podcast": ep.get("podcast", ""),
                "title": ep.get("title", ""),
                "status": ep.get("status", "unknown"),
                "published": ep.get("published", ""),
                "age_days": age,
                "next_blocker": next(
                    (k for k in ["downloaded", "transcribed", "analyzed", "insight_created", "published"] if not st.get(k)),
                    "unknown",
                ),
            })

    payload = {
        "last_updated": raw.get("last_updated"),
        "last_3_completed": last_3_completed,
        "episodes": in_pipeline + tracked_feed_placeholders,
        "available_from_rss": available_from_rss,
        "stale_episodes": stale_episodes,
        "stale_threshold_days": stale_threshold_days,
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
