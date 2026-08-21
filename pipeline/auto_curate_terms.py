#!/usr/bin/env python3
"""
Auto-curate suggested terms using AI analysis.
High-relevance terms auto-promote to Definitions.
Borderline terms flagged for manual review.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db
from manage_suggested_terms import SuggestedTermsManager
from workspace_paths import STATE_DIR

# Priority score (must match db_manager.get_suggested_terms_for_website):
#   mention_count * 10 + source_diversity * 20 + relevance_score
# Used for ordering only; promotion requires meets_recurrence_gate() below.
PRIORITY_SCORE_PROMOTE_THRESHOLD = 66.7

# Minimum signal before a pending term can enter Overton (2+ mentions, 2+ episodes).
MIN_MENTIONS_FOR_PROMOTE = 2

# Auto-promotion criteria (used when priority score is NOT above threshold)
MIN_RELEVANCE_AUTO = 70  # Auto-promote if relevance >= 70
MIN_SOURCES_AUTO = 2     # And mentioned in 2+ different sources
MIN_MENTIONS_AUTO = 3    # And mentioned 3+ times total
# Hard threshold: if a term is mentioned this many times across podcasts/newsletters,
# it should always be promoted into Digital Definitions.
PROMOTE_MENTIONS_THRESHOLD = 6

# Manual review criteria (borderline)
MIN_RELEVANCE_REVIEW = 40  # Flag for review if relevance >= 40 but < 70


def compute_priority_score(term_data: dict) -> int:
    """Same formula as suggested_terms priority_score."""
    try:
        m = int(term_data.get("mention_count") or 0)
        s = int(term_data.get("source_diversity") or 0)
        r = int(term_data.get("relevance_score") or 0)
    except (TypeError, ValueError):
        m, s, r = 0, 0, 0
    return m * 10 + s * 20 + r


def meets_recurrence_gate(term_data: dict) -> bool:
    """Require 2+ mentions across at least two distinct episodes."""
    try:
        mentions = int(term_data.get("mention_count") or 0)
    except (TypeError, ValueError):
        mentions = 0
    if mentions < MIN_MENTIONS_FOR_PROMOTE:
        return False
    first_ep = term_data.get("first_seen_episode_id")
    last_ep = term_data.get("last_seen_episode_id")
    if first_ep is None or last_ep is None:
        return False
    try:
        return int(first_ep) != int(last_ep)
    except (TypeError, ValueError):
        return False


def analyze_term_quality(term_data):
    """
    Analyze term quality for auto-curation.
    Returns: ('auto_promote', 'manual_review', or 'skip')
    """
    if not meets_recurrence_gate(term_data):
        return 'skip'

    relevance = term_data.get('relevance_score', 0) or 0
    sources = term_data.get('source_diversity', 0) or 0
    mentions = term_data.get('mention_count', 0) or 0
    
    # Hard rule: once a term has been mentioned enough times, always promote it.
    if mentions >= PROMOTE_MENTIONS_THRESHOLD:
        return 'auto_promote'
    
    # Otherwise, use relevance + source diversity rules for early promotion
    if relevance >= MIN_RELEVANCE_AUTO and sources >= MIN_SOURCES_AUTO and mentions >= MIN_MENTIONS_AUTO:
        return 'auto_promote'
    
    # Borderline = manual review
    if relevance >= MIN_RELEVANCE_REVIEW:
        return 'manual_review'
    
    # Low quality = skip
    return 'skip'


def _looks_like_person_name(term: str) -> bool:
    """
    Heuristic: detect personal names like 'Michael Howell' and avoid
    promoting them into Definitions/Overton (those should stay out of
    the Overton Window).
    """
    if not term:
        return False
    parts = str(term).strip().split()
    if len(parts) != 2:
        return False
    first, last = parts[0], parts[1]
    return (
        first[0].isupper()
        and last[0].isupper()
        and first[1:].islower()
        and last[1:].islower()
    )


def auto_promote_term(db, term_data):
    """Promote a term to Definitions and to Overton Window (overton_terms)."""
    term = term_data.get('term', '')

    # Hard rule: do not promote personal names into Definitions/Overton.
    if _looks_like_person_name(term):
        with db._get_connection() as conn:
            conn.execute(
                """
                UPDATE suggested_terms
                SET status = 'rejected',
                    reviewed_at = CURRENT_TIMESTAMP,
                    review_notes = 'Rejected: looks like a personal name (excluded from Overton Window)'
                WHERE id = ?
                """,
                (term_data['id'],),
            )
        print(f"  ⏭️  SKIPPED (person name): '{term}'")
        return False

    with db._get_connection() as conn:
        # Check if already in definitions
        cursor = conn.execute(
            "SELECT id FROM definitions WHERE term = ?",
            (term_data['term'],)
        )
        if cursor.fetchone():
            print(f"  ℹ️  '{term_data['term']}' already in definitions")
            # Still ensure it's in overton_terms for the Overton Window
            _ensure_overton_term(conn, term_data)
            return False

        # Add to definitions
        conn.execute("""
            INSERT INTO definitions 
            (term, definition, investment_implications, added_date, vote_count, display_on_main, display_order)
            VALUES (?, ?, ?, date('now'), ?, 0, 0)
        """, (
            term_data['term'],
            term_data.get('definition') or f"Definition for {term_data['term']}",
            term_data.get('investment_implications') or 'AI-curated from transcript analysis',
            term_data.get('mention_count', 1)
        ))

        # Add to overton_terms so it appears in the Overton Window on the site
        _ensure_overton_term(conn, term_data)

        # Update suggested_terms status
        conn.execute("""
            UPDATE suggested_terms 
            SET status = 'approved', 
                reviewed_at = CURRENT_TIMESTAMP, 
                review_notes = 'Auto-approved: recurring term (2+ episodes); awaiting YES for main page'
            WHERE id = ?
        """, (term_data['id'],))

        print(
            f"  ✅ AUTO-PROMOTED (hidden until YES): '{term_data['term']}' → Definitions + Overton "
            f"(mentions: {term_data.get('mention_count', 'N/A')}, relevance: {term_data.get('relevance_score', 'N/A')})"
        )
        try:
            from term_promotion_notify import notify_promoted_term

            notify_promoted_term(term_data)
        except Exception as exc:
            print(f"  ⚠ Could not send promotion iMessage: {exc}")
        return True


def _episode_date_str(conn, eid) -> Optional[str]:
    if not eid:
        return None
    r = conn.execute(
        "SELECT date(episode_date) AS d FROM podcast_episodes WHERE id = ?",
        (int(eid),),
    ).fetchone()
    if not r or not r["d"]:
        return None
    return str(r["d"])[:10]


def _first_detected_date_for_overton(conn, term_data: dict) -> str:
    d = _episode_date_str(conn, term_data.get("first_seen_episode_id"))
    if d:
        return d
    sub = term_data.get("submitted_date")
    if sub and len(str(sub)) >= 10:
        s = str(sub)
        if s[4:5] == "-" and s[7:8] == "-":
            return s[:10]
    return date.today().isoformat()


def _last_mentioned_date_for_overton(conn, term_data: dict, first_d: str) -> str:
    d = _episode_date_str(conn, term_data.get("last_seen_episode_id"))
    if d:
        return d
    d2 = _episode_date_str(conn, term_data.get("first_seen_episode_id"))
    if d2:
        return d2
    return first_d


def _ensure_overton_term(conn, term_data):
    """Insert or update overton_terms so the term appears in the Overton Window."""
    term = term_data['term']
    description = term_data.get('definition') or f"Curated concept: {term}"
    investment_implications = term_data.get('investment_implications')
    mention_count = term_data.get('mention_count', 1)
    feid = term_data.get("first_seen_episode_id")
    fspeaker = (term_data.get("first_seen_speaker") or "").strip() or None
    leid = term_data.get("last_seen_episode_id")
    lspeaker = (term_data.get("last_seen_speaker") or "").strip() or None
    cursor = conn.execute("SELECT id FROM overton_terms WHERE term = ?", (term,))
    if cursor.fetchone():
        last_md = _last_mentioned_date_for_overton(conn, term_data, date.today().isoformat())
        conn.execute(
            """
            UPDATE overton_terms
            SET description = COALESCE(?, description),
                investment_implications = COALESCE(?, investment_implications),
                last_mentioned_date = ?,
                mention_count = MAX(mention_count, ?),
                status = 'active',
                last_mentioned_episode_id = COALESCE(?, last_mentioned_episode_id),
                last_mentioned_speaker = COALESCE(?, last_mentioned_speaker),
                first_detected_episode_id = COALESCE(first_detected_episode_id, ?),
                first_detected_speaker = COALESCE(first_detected_speaker, ?)
            WHERE term = ?
            """,
            (
                description,
                investment_implications,
                last_md,
                mention_count,
                leid or feid,
                lspeaker or fspeaker,
                feid,
                fspeaker,
                term,
            ),
        )
    else:
        first_d = _first_detected_date_for_overton(conn, term_data)
        last_d = _last_mentioned_date_for_overton(conn, term_data, first_d)
        conn.execute(
            """
            INSERT INTO overton_terms
            (term, description, first_detected_date, last_mentioned_date, mention_count,
             status, investment_implications, display_on_main,
             first_detected_episode_id, first_detected_speaker,
             last_mentioned_episode_id, last_mentioned_speaker)
            VALUES (?, ?, ?, ?, ?, 'active', ?, 0, ?, ?, ?, ?)
            """,
            (
                term,
                description,
                first_d,
                last_d,
                mention_count,
                investment_implications,
                feid,
                fspeaker,
                leid or feid,
                lspeaker or fspeaker,
            ),
        )


def get_borderline_terms_for_review(db):
    """Get terms that need manual review."""
    with db._get_connection() as conn:
        cursor = conn.execute("""
            SELECT * FROM suggested_terms
            WHERE status = 'pending'
            AND relevance_score >= ?
            AND relevance_score < ?
            ORDER BY relevance_score DESC, mention_count DESC
            LIMIT 5
        """, (MIN_RELEVANCE_REVIEW, MIN_RELEVANCE_AUTO))
        
        return [dict(row) for row in cursor.fetchall()]


def main():
    """Run auto-curation on suggested terms."""
    print("="*60)
    print("Auto-Curating Suggested Terms")
    print("="*60)
    
    # First, scan recent content so mention counts and candidates stay fresh
    try:
        manager = SuggestedTermsManager()
        new_found = manager.scan_content_for_terms()
        print(f"\nFound {new_found} new potential terms from recent content.")
    except Exception as e:
        print(f"\n⚠ Could not scan content for new terms: {e}")
    
    db = get_db()
    
    # Get pending suggested terms
    with db._get_connection() as conn:
        cursor = conn.execute("""
            SELECT * FROM suggested_terms
            WHERE status = 'pending'
            ORDER BY relevance_score DESC, mention_count DESC
        """)
        pending_terms = [dict(row) for row in cursor.fetchall()]
    
    if not pending_terms:
        print("\nNo pending terms to curate.")
        return {
            "promoted": 0,
            "review": 0,
            "skipped": 0,
            "review_terms": [],
            "pending_before": 0,
            "pending_after": 0,
            "run_iso": datetime.now().isoformat(),
        }
    
    print(f"\n📊 Analyzing {len(pending_terms)} pending terms...")
    print("-"*60)
    
    promoted = 0
    review_queue = []
    skipped = 0
    
    for term in pending_terms:
        if not meets_recurrence_gate(term):
            skipped += 1
            print(
                f"  ⏳ WAITING: '{term['term']}' "
                f"(mentions: {term.get('mention_count', 0)}, "
                f"episodes: {term.get('first_seen_episode_id')} → {term.get('last_seen_episode_id')})"
            )
            continue

        ps = compute_priority_score(term)
        if ps > PRIORITY_SCORE_PROMOTE_THRESHOLD:
            print(
                f"  🎯 PRIORITY PROMOTE (score {ps} > {PRIORITY_SCORE_PROMOTE_THRESHOLD}): '{term['term']}'"
            )
            if auto_promote_term(db, term):
                promoted += 1
            continue

        action = analyze_term_quality(term)

        if action == 'auto_promote':
            if auto_promote_term(db, term):
                promoted += 1
        elif action == 'manual_review':
            review_queue.append(term)
        else:
            skipped += 1
            print(f"  ⏭️  SKIPPED: '{term['term']}' (relevance too low: {term.get('relevance_score', 'N/A')})")
    
    # Generate review summary
    print("\n" + "="*60)
    print("CURATION SUMMARY")
    print("="*60)
    print(f"  Auto-promoted: {promoted}")
    print(f"  Flagged for review: {len(review_queue)}")
    print(f"  Skipped (low relevance): {skipped}")
    
    with db._get_connection() as conn:
        after_row = conn.execute(
            "SELECT COUNT(*) AS n FROM suggested_terms WHERE status = 'pending'"
        ).fetchone()
    pending_after = int(after_row["n"]) if after_row and after_row["n"] is not None else 0

    # Return review info for potential notification
    return {
        "promoted": promoted,
        "review": len(review_queue),
        "skipped": skipped,
        "review_terms": review_queue,
        "pending_before": len(pending_terms),
        "pending_after": pending_after,
        "run_iso": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    results = main()
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        slim = {k: v for k, v in results.items() if k != "review_terms"}
        (STATE_DIR / "term_curation_last_run.json").write_text(
            json.dumps(slim, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"  ⚠ Could not write term curation state: {e}")
    
    # Print review terms for potential iMessage notification
    if results['review_terms']:
        print("\n" + "="*60)
        print("TERMS FOR MANUAL REVIEW")
        print("="*60)
        for term in results['review_terms']:
            print(f"\n• {term['term']}")
            print(f"  Relevance: {term.get('relevance_score', 'N/A')}")
            print(f"  Mentions: {term.get('mention_count', 0)} in {term.get('source_diversity', 0)} source(s)")
            print(f"  Definition: {term.get('definition', 'N/A')[:100]}...")
