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

import workspace_paths
from workspace_paths import DB_PATH

class SuggestedTermsManager:
    """Manage suggested terms workflow."""
    
    def __init__(self, db_path=None):
        self.db_path = db_path
        self._ensure_table()
    
    def _get_connection(self):
        conn = sqlite3.connect(getattr(self, 'db_path', None) or DB_PATH)
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
    
    # Real definition syntax only: a quoted term, then a colon or dash, then the definition.
    # Bare whitespace after a closing quote is NOT a definition (that is a quote fragment,
    # e.g. 'raise the "ceiling" of quality' or '"cloud design" announcement').
    DEFINITION_PATTERN = re.compile(
        r'["\u201c]([^"\u201c\u201d\n]{3,50})["\u201d]\s*(?::|\s[-\u2013\u2014]|[-\u2013\u2014])\s*([^.\n]{10,200})'
    )

    # Single words that are never a term on their own.
    GENERIC_WORDS = {
        'floor', 'ceiling', 'design', 'growth', 'market', 'markets', 'model', 'models', 'data',
        'value', 'price', 'cost', 'risk', 'scale', 'money', 'power', 'energy', 'compute',
        'future', 'thing', 'things', 'people', 'company', 'business', 'product', 'platform',
        'moment', 'idea', 'world', 'system', 'trade', 'cycle', 'bubble', 'demand', 'supply',
        'intelligence', 'safety', 'quality', 'taste', 'craft', 'tool', 'tools', 'agent', 'agents',
    }

    @staticmethod
    def normalize_term(term: str) -> str:
        """Strip surrounding punctuation/quotes and collapse whitespace ("super intelligence," -> "super intelligence")."""
        t = re.sub(r'\s+', ' ', term or '').strip()
        t = t.strip(' \t"\'\u201c\u201d\u2018\u2019.,;:!?()[]{}-\u2013\u2014')
        return t.strip()

    def extract_terms_from_content(self, content: str, source_type: str, source_name: str) -> List[Dict]:
        """Extract candidate terms that use real definition syntax ("Term": definition / "Term" - definition).

        One record per distinct term per source (a term defined twice in one summary still counts once).
        """
        terms: List[Dict] = []
        seen = set()
        for match in self.DEFINITION_PATTERN.finditer(content or ''):
            term = self.normalize_term(match.group(1))
            definition = match.group(2).strip()
            if not self._is_valid_term(term):
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append({
                'term': term,
                'definition': definition,
                'source_context': f"{source_name}",
                'excerpt': content[max(0, match.start()-50):min(len(content), match.end()+50)],
            })
        return terms

    def _is_valid_term(self, term: str) -> bool:
        """Check if extracted text is a valid term candidate."""
        term = self.normalize_term(term)
        skip_words = {'the', 'and', 'but', 'for', 'with', 'this', 'that', 'from', 'have', 'been'}
        if term.lower() in skip_words:
            return False
        if len(term) < 5 or len(term) > 60:
            return False
        if term.isupper():
            return False
        if any(c.isdigit() for c in term):
            return False
        # Leftover punctuation inside means a sentence fragment, not a term
        if re.search(r'[,;:!?]', term):
            return False
        words = term.split()
        if len(words) == 1 and term.lower() in self.GENERIC_WORDS:
            return False
        # Single all-lowercase word (e.g. "floor") is a quote fragment, not a coined term
        if len(words) == 1 and term.islower():
            return False
        if len(words) > 6:
            return False
        return True

    def _ensure_sources_table(self, conn) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS suggested_term_sources (
                term_key TEXT NOT NULL,
                source TEXT NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (term_key, source)
            )
        """)

    def scan_content_for_terms(self):
        """Scan recent podcast summaries and newsletters for new terms.

        Re-scanning the same 7-day window every run is safe: a (term, source) pair is only
        counted the first time it is seen, so counts reflect DISTINCT sources.
        """
        print("\n🔍 Scanning content for new terms...")
        new_terms_found = 0
        with self._get_connection() as conn:
            rows = []
            for row in conn.execute("""
                SELECT podcast_name, episode_title, summary
                FROM podcast_episodes
                WHERE summary IS NOT NULL
                  AND episode_date > date('now', '-7 days')
            """).fetchall():
                rows.append((row['summary'] or '', f"{row['podcast_name']} - {row['episode_title']}", 'podcast'))
            try:
                for row in conn.execute("""
                    SELECT subject, content_preview
                    FROM newsletters
                    WHERE is_processed = 1
                      AND received_date > date('now', '-7 days')
                """).fetchall():
                    rows.append((row['content_preview'] or '', row['subject'] or '', 'newsletter'))
            except sqlite3.OperationalError:
                pass
        for content, source, kind in rows:
            for term_data in self.extract_terms_from_content(content, kind, source):
                if self._add_or_update_term(term_data, 'auto_extracted'):
                    new_terms_found += 1
                    print(f"  ✓ Found: {term_data['term']}")
        print(f"\n✓ Found {new_terms_found} new potential terms")
        return new_terms_found

    def _add_or_update_term(self, term_data: Dict, source_type: str) -> bool:
        """Add new term or count a new distinct source. Returns True if the term is new."""
        term = self.normalize_term(term_data['term'])
        if not self._is_valid_term(term):
            return False
        source = (term_data.get('source_context') or '').strip()
        key = term.lower()
        with self._get_connection() as conn:
            self._ensure_sources_table(conn)
            if source:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO suggested_term_sources (term_key, source) VALUES (?, ?)",
                    (key, source),
                )
                if cur.rowcount == 0:
                    conn.commit()
                    return False  # already counted this source on an earlier scan
            existing = conn.execute(
                "SELECT id FROM suggested_terms WHERE LOWER(TRIM(term)) = ?", (key,)
            ).fetchone()
            if existing:
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
            if conn.execute(
                "SELECT id FROM definitions WHERE LOWER(TRIM(term)) = ?", (key,)
            ).fetchone():
                conn.commit()
                return False
            conn.execute("""
                INSERT INTO suggested_terms
                (term, definition, investment_implications, source_type, source_context,
                 mention_count, source_diversity, relevance_score, last_mentioned_date)
                VALUES (?, ?, ?, ?, ?, 1, 1, ?, date('now'))
            """, (
                term,
                term_data.get('definition'),
                None,
                source_type,
                source or None,
                50 if term_data.get('definition') else 30,
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
