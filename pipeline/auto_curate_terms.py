#!/usr/bin/env python3
"""
Auto-curate suggested terms using AI analysis.
High-relevance terms auto-promote to Definitions.
Borderline terms flagged for manual review.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db

# Auto-promotion criteria
MIN_RELEVANCE_AUTO = 70  # Auto-promote if relevance >= 70
MIN_SOURCES_AUTO = 2     # And mentioned in 2+ different sources
MIN_MENTIONS_AUTO = 3    # And mentioned 3+ times total

# Manual review criteria (borderline)
MIN_RELEVANCE_REVIEW = 40  # Flag for review if relevance >= 40 but < 70


def analyze_term_quality(term_data):
    """
    Analyze term quality for auto-curation.
    Returns: ('auto_promote', 'manual_review', or 'skip')
    """
    relevance = term_data.get('relevance_score', 0) or 0
    sources = term_data.get('source_diversity', 0) or 0
    mentions = term_data.get('mention_count', 0) or 0
    
    # High quality = auto-promote
    if relevance >= MIN_RELEVANCE_AUTO and sources >= MIN_SOURCES_AUTO and mentions >= MIN_MENTIONS_AUTO:
        return 'auto_promote'
    
    # Borderline = manual review
    if relevance >= MIN_RELEVANCE_REVIEW:
        return 'manual_review'
    
    # Low quality = skip
    return 'skip'


def auto_promote_term(db, term_data):
    """Promote a term to Definitions."""
    with db._get_connection() as conn:
        # Check if already in definitions
        cursor = conn.execute(
            "SELECT id FROM definitions WHERE term = ?",
            (term_data['term'],)
        )
        if cursor.fetchone():
            print(f"  ℹ️  '{term_data['term']}' already in definitions")
            return False
        
        # Add to definitions
        conn.execute("""
            INSERT INTO definitions 
            (term, definition, investment_implications, added_date, vote_count, display_on_main, display_order)
            VALUES (?, ?, ?, date('now'), ?, 1, 0)
        """, (
            term_data['term'],
            term_data.get('definition') or f"Definition for {term_data['term']}",
            term_data.get('investment_implications') or 'AI-curated from transcript analysis',
            term_data.get('mention_count', 1)
        ))
        
        # Update suggested_terms status
        conn.execute("""
            UPDATE suggested_terms 
            SET status = 'approved', 
                reviewed_at = CURRENT_TIMESTAMP, 
                review_notes = 'Auto-approved: high relevance score'
            WHERE id = ?
        """, (term_data['id'],))
        
        print(f"  ✅ AUTO-PROMOTED: '{term_data['term']}' (relevance: {term_data.get('relevance_score', 'N/A')})")
        return True


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
        return {'promoted': 0, 'review': 0, 'skipped': 0}
    
    print(f"\n📊 Analyzing {len(pending_terms)} pending terms...")
    print("-"*60)
    
    promoted = 0
    review_queue = []
    skipped = 0
    
    for term in pending_terms:
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
    
    # Return review info for potential notification
    return {
        'promoted': promoted,
        'review': len(review_queue),
        'skipped': skipped,
        'review_terms': review_queue
    }


if __name__ == "__main__":
    results = main()
    
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
