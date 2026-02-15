#!/usr/bin/env python3
"""
Suggested Terms Management System
Handles user submissions, auto-extraction from content, and promotion to definitions.
"""

import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"

class SuggestedTermsManager:
    """Manage suggested terms workflow."""
    
    def __init__(self):
        self._ensure_table()
    
    def _get_connection(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _ensure_table(self):
        """Ensure suggested_terms table exists."""
        schema_file = Path(__file__).parent / "schema_suggested_terms.sql"
        if schema_file.exists():
            with open(schema_file, 'r') as f:
                schema = f.read()
            
            with self._get_connection() as conn:
                conn.executescript(schema)
                conn.commit()
    
    def extract_terms_from_content(self, content: str, source_type: str, source_name: str) -> List[Dict]:
        """Extract potential new terms from podcast/newsletter content."""
        terms = []
        
        # Pattern 1: Terms in quotes that might be definitions
        # "Term": definition or "Term" - definition
        quote_pattern = r'"([^"]{3,50})"[:\s-]+([^.]{10,200})'
        for match in re.finditer(quote_pattern, content, re.IGNORECASE):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            if self._is_valid_term(term):
                terms.append({
                    'term': term,
                    'definition': definition,
                    'source_context': f"{source_name}",
                    'excerpt': content[max(0, match.start()-50):min(len(content), match.end()+50)]
                })
        
        # Pattern 2: Capitalized phrases that appear multiple times
        # Look for phrases like "Neuralink Moment", "Sovereign Individual Thesis"
        capitalized_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\b'
        found_phrases = {}
        for match in re.finditer(capitalized_pattern, content):
            phrase = match.group(1)
            if len(phrase) > 10 and self._is_valid_term(phrase):
                found_phrases[phrase] = found_phrases.get(phrase, 0) + 1
        
        # Only keep phrases mentioned multiple times
        for phrase, count in found_phrases.items():
            if count >= 2:
                terms.append({
                    'term': phrase,
                    'definition': None,  # Will need manual definition
                    'source_context': f"{source_name}",
                    'mention_count': count
                })
        
        return terms
    
    def _is_valid_term(self, term: str) -> bool:
        """Check if extracted text is a valid term candidate."""
        # Skip common words
        skip_words = {'The', 'And', 'But', 'For', 'With', 'This', 'That', 'From', 'Have', 'Been'}
        if term in skip_words:
            return False
        
        # Skip if too short or too long
        if len(term) < 5 or len(term) > 60:
            return False
        
        # Skip if all uppercase (likely ticker or acronym)
        if term.isupper():
            return False
        
        # Skip if contains numbers (likely not a conceptual term)
        if any(c.isdigit() for c in term):
            return False
        
        return True
    
    def scan_content_for_terms(self):
        """Scan recent podcast transcripts and newsletters for new terms."""
        print("\n🔍 Scanning content for new terms...")
        
        with self._get_connection() as conn:
            # Get recent transcripts
            cursor = conn.execute("""
                SELECT podcast_name, episode_title, summary, transcript_path
                FROM podcast_episodes
                WHERE summary IS NOT NULL
                  AND episode_date > date('now', '-7 days')
            """)
            
            new_terms_found = 0
            
            for row in cursor.fetchall():
                content = row['summary'] or ''
                source = f"{row['podcast_name']} - {row['episode_title']}"
                
                terms = self.extract_terms_from_content(content, 'podcast', source)
                for term_data in terms:
                    if self._add_or_update_term(term_data, 'auto_extracted'):
                        new_terms_found += 1
                        print(f"  ✓ Found: {term_data['term']}")
            
            # Get recent newsletters
            cursor = conn.execute("""
                SELECT subject, content_preview
                FROM newsletters
                WHERE is_processed = 1
                  AND received_date > date('now', '-7 days')
            """)
            
            for row in cursor.fetchall():
                content = row['content_preview'] or ''
                source = row['subject']
                
                terms = self.extract_terms_from_content(content, 'newsletter', source)
                for term_data in terms:
                    if self._add_or_update_term(term_data, 'auto_extracted'):
                        new_terms_found += 1
                        print(f"  ✓ Found: {term_data['term']}")
            
            print(f"\n✓ Found {new_terms_found} new potential terms")
            return new_terms_found
    
    def _add_or_update_term(self, term_data: Dict, source_type: str) -> bool:
        """Add new term or update existing. Returns True if new."""
        with self._get_connection() as conn:
            # Check if already exists in suggested_terms
            cursor = conn.execute(
                "SELECT id, mention_count FROM suggested_terms WHERE term = ?",
                (term_data['term'],)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Update mention count
                conn.execute("""
                    UPDATE suggested_terms 
                    SET mention_count = mention_count + 1,
                        source_diversity = source_diversity + 1,
                        last_mentioned_date = date('now'),
                        relevance_score = MIN(relevance_score + 5, 100)
                    WHERE id = ?
                """, (existing['id'],))
                conn.commit()
                return False
            
            # Check if already in definitions
            cursor = conn.execute(
                "SELECT id FROM definitions WHERE term = ?",
                (term_data['term'],)
            )
            if cursor.fetchone():
                return False
            
            # Insert new term
            conn.execute("""
                INSERT INTO suggested_terms 
                (term, definition, investment_implications, source_type, source_context, 
                 mention_count, source_diversity, relevance_score, last_mentioned_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, date('now'))
            """, (
                term_data['term'],
                term_data.get('definition'),
                None,  # Will be added when approved
                source_type,
                term_data.get('source_context'),
                term_data.get('mention_count', 1),
                1,
                50 if term_data.get('definition') else 30  # Higher score if has definition
            ))
            conn.commit()
            return True
    
    def get_top_suggestions(self, limit: int = 5) -> List[Dict]:
        """Get top pending suggestions by priority score."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM v_priority_suggestions
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    def approve_term(self, term_id: int, reviewed_by: str = 'system', notes: str = '') -> bool:
        """Approve a suggested term and add it to definitions."""
        with self._get_connection() as conn:
            # Get term details
            cursor = conn.execute(
                "SELECT * FROM suggested_terms WHERE id = ?",
                (term_id,)
            )
            term = cursor.fetchone()
            
            if not term:
                print(f"✗ Term ID {term_id} not found")
                return False
            
            # Add to definitions
            conn.execute("""
                INSERT INTO definitions 
                (term, definition, investment_implications, added_date, vote_count, display_on_main)
                VALUES (?, ?, ?, date('now'), ?, 1)
            """, (
                term['term'],
                term['definition'] or f"Definition for {term['term']} - pending detailed writeup",
                term['investment_implications'] or 'Pending analysis',
                max(term['vote_count'], 1)
            ))
            
            # Update suggested_terms status
            conn.execute("""
                UPDATE suggested_terms 
                SET status = 'approved',
                    reviewed_by = ?,
                    reviewed_at = CURRENT_TIMESTAMP,
                    review_notes = ?
                WHERE id = ?
            """, (reviewed_by, notes, term_id))
            
            conn.commit()
            print(f"✓ Approved and added to definitions: {term['term']}")
            return True
    
    def auto_approve_high_priority(self, threshold: int = 80) -> int:
        """Auto-approve terms with very high priority scores."""
        print(f"\n🤖 Auto-approving terms with score >= {threshold}...")
        
        approved = 0
        suggestions = self.get_top_suggestions(limit=10)
        
        for sugg in suggestions:
            if sugg['priority_score'] >= threshold and sugg.get('definition'):
                if self.approve_term(sugg['id'], 'auto_pipeline', 'High priority auto-approval'):
                    approved += 1
        
        print(f"✓ Auto-approved {approved} terms")
        return approved
    
    def get_next_suggestion_for_display(self) -> Optional[Dict]:
        """Get the top suggestion to display on the website."""
        suggestions = self.get_top_suggestions(limit=1)
        return suggestions[0] if suggestions else None
    
    def reject_term(self, term_id: int, reason: str, reviewed_by: str = 'system') -> bool:
        """Reject a suggested term."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE suggested_terms 
                SET status = 'rejected',
                    reviewed_by = ?,
                    reviewed_at = CURRENT_TIMESTAMP,
                    review_notes = ?
                WHERE id = ?
            """, (reviewed_by, reason, term_id))
            conn.commit()
            return True
    
    def get_stats(self) -> Dict:
        """Get statistics about suggested terms."""
        with self._get_connection() as conn:
            stats = {}
            
            # Count by status
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count 
                FROM suggested_terms 
                GROUP BY status
            """)
            stats['by_status'] = {row['status']: row['count'] for row in cursor.fetchall()}
            
            # Total pending
            cursor = conn.execute("""
                SELECT COUNT(*) as count FROM suggested_terms WHERE status = 'pending'
            """)
            stats['pending'] = cursor.fetchone()['count']
            
            # Top pending by score
            cursor = conn.execute("""
                SELECT term, relevance_score + mention_count * 10 as score
                FROM suggested_terms
                WHERE status = 'pending'
                ORDER BY score DESC
                LIMIT 5
            """)
            stats['top_pending'] = [dict(row) for row in cursor.fetchall()]
            
            return stats

def main():
    """Run suggested terms workflow."""
    print("="*60)
    print("Suggested Terms Management")
    print(f"Started: {datetime.now()}")
    print("="*60)
    
    manager = SuggestedTermsManager()
    
    # Step 1: Scan content for new terms
    new_found = manager.scan_content_for_terms()
    
    # Step 2: Auto-approve high priority terms
    auto_approved = manager.auto_approve_high_priority(threshold=70)
    
    # Step 3: Show stats
    stats = manager.get_stats()
    print(f"\n📊 Suggested Terms Stats:")
    print(f"  Pending: {stats['pending']}")
    print(f"  By status: {stats['by_status']}")
    
    if stats['top_pending']:
        print(f"\n  Top pending suggestions:")
        for term in stats['top_pending']:
            print(f"    - {term['term']} (score: {term['score']})")
    
    # Step 4: Get next suggestion for website display
    next_sugg = manager.get_next_suggestion_for_display()
    if next_sugg:
        print(f"\n📌 Next suggestion for website: {next_sugg['term']}")
    
    print(f"\nFinished: {datetime.now()}")

if __name__ == "__main__":
    main()
