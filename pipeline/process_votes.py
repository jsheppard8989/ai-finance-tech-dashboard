#!/usr/bin/env python3
"""
Process website votes and auto-promote/reject suggested terms.
Called by pipeline to sync votes from votes.json to database.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db

VOTE_FILE = Path.home() / ".openclaw/workspace/pipeline/state/votes.json"
THRESHOLD_UP = 10    # Auto-promote at 10 upvotes
THRESHOLD_DOWN = 10  # Auto-reject at 10 downvotes

def load_votes():
    """Load votes from vote file."""
    if not VOTE_FILE.exists():
        return []
    
    with open(VOTE_FILE, 'r') as f:
        try:
            return json.load(f)
        except:
            return []

def process_votes():
    """Process votes and update database."""
    print("="*60)
    print("Processing Website Votes")
    print("="*60)
    
    votes = load_votes()
    if not votes:
        print("No votes to process.")
        return {'promoted': 0, 'rejected': 0, 'processed': 0}
    
    # Tally votes by term
    term_votes = {}
    for vote in votes:
        term = vote.get('term')
        vote_type = vote.get('type')  # 'up' or 'down'
        
        if not term or not vote_type:
            continue
        
        if term not in term_votes:
            term_votes[term] = {'up': 0, 'down': 0}
        
        term_votes[term][vote_type] += 1
    
    print(f"\n📊 Vote Summary:")
    for term, counts in term_votes.items():
        print(f"  {term}: {counts['up']} up, {counts['down']} down")
    
    # Process in database
    db = get_db()
    promoted = 0
    rejected = 0
    
    with db._get_connection() as conn:
        for term, counts in term_votes.items():
            up = counts['up']
            down = counts['down']
            
            # Check if term exists in suggested_terms
            cursor = conn.execute(
                "SELECT id, status FROM suggested_terms WHERE term = ?",
                (term,)
            )
            suggested = cursor.fetchone()
            
            if not suggested:
                # Check if already in definitions
                cursor = conn.execute(
                    "SELECT id FROM definitions WHERE term = ?",
                    (term,)
                )
                if cursor.fetchone():
                    print(f"  ℹ️  '{term}' already in definitions")
                else:
                    print(f"  ⚠️  '{term}' not found in suggested_terms")
                continue
            
            if suggested['status'] != 'pending':
                print(f"  ℹ️  '{term}' already {suggested['status']}")
                continue
            
            suggested_id = suggested['id']
            
            # Auto-promote
            if up >= THRESHOLD_UP:
                print(f"\n✅ PROMOTING: '{term}' ({up} upvotes)")
                
                # Get term details
                cursor = conn.execute(
                    "SELECT * FROM suggested_terms WHERE id = ?",
                    (suggested_id,)
                )
                term_data = dict(cursor.fetchone())
                
                # Add to definitions
                conn.execute("""
                    INSERT INTO definitions 
                    (term, definition, investment_implications, added_date, vote_count, display_on_main, display_order)
                    VALUES (?, ?, ?, date('now'), ?, 1, 0)
                """, (
                    term_data['term'],
                    term_data['definition'] or f"Definition for {term_data['term']}",
                    term_data['investment_implications'] or 'Pending detailed analysis',
                    up
                ))
                
                # Update suggested_terms
                conn.execute("""
                    UPDATE suggested_terms 
                    SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, review_notes = 'Auto-approved: reached upvote threshold'
                    WHERE id = ?
                """, (suggested_id,))
                
                promoted += 1
            
            # Auto-reject
            elif down >= THRESHOLD_DOWN:
                print(f"\n❌ REJECTING: '{term}' ({down} downvotes)")
                
                conn.execute("""
                    UPDATE suggested_terms 
                    SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, review_notes = 'Auto-rejected: reached downvote threshold'
                    WHERE id = ?
                """, (suggested_id,))
                
                rejected += 1
            else:
                # Update vote count but keep pending
                total = up + down
                conn.execute(
                    "UPDATE suggested_terms SET vote_count = ? WHERE id = ?",
                    (total, suggested_id)
                )
                print(f"  ⏳ '{term}' pending ({up} up, {down} down)")
    
    # Clear processed votes
    if promoted > 0 or rejected > 0:
        VOTE_FILE.write_text('[]')
        print(f"\n✓ Cleared processed votes")
    
    results = {'promoted': promoted, 'rejected': rejected, 'processed': len(votes)}
    
    print(f"\n📈 Results:")
    print(f"  Promoted to definitions: {promoted}")
    print(f"  Rejected: {rejected}")
    print(f"  Total votes processed: {len(votes)}")
    
    return results

def get_top_suggestions_for_site(limit=3):
    """Get top suggestions to display on website."""
    db = get_db()
    
    with db._get_connection() as conn:
        cursor = conn.execute("""
            SELECT term, definition, vote_count, mention_count
            FROM suggested_terms
            WHERE status = 'pending'
            ORDER BY (vote_count + mention_count * 5) DESC, relevance_score DESC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]

if __name__ == "__main__":
    results = process_votes()
    
    # Show current top suggestions
    print("\n" + "="*60)
    print("Top Suggestions for Website")
    print("="*60)
    top = get_top_suggestions_for_site(3)
    for t in top:
        print(f"  • {t['term']} (votes: {t['vote_count']}, mentions: {t['mention_count']})")
