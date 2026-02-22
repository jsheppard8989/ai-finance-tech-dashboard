#!/usr/bin/env python3
"""
Database manager for AI Finance Tech dashboard.
Handles all SQLite operations and provides clean interface for pipeline scripts.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from contextlib import contextmanager

# Database path
DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

@dataclass
class TickerMention:
    ticker: str
    source_type: str  # 'podcast' or 'newsletter'
    source_name: str
    episode_title: Optional[str] = None
    context: Optional[str] = None
    conviction_score: int = 0
    sentiment: str = 'neutral'
    timeframe: str = 'unspecified'
    is_contrarian: bool = False
    is_disruption_focused: bool = False

@dataclass
class PodcastEpisode:
    podcast_name: str
    episode_title: str
    episode_date: date
    audio_url: Optional[str] = None
    transcript_path: Optional[str] = None
    summary: Optional[str] = None
    key_takeaways: Optional[List[str]] = None
    key_tickers: Optional[List[str]] = None
    investment_thesis: Optional[str] = None
    relevance_score: int = 0

@dataclass
class DailyScore:
    ticker: str
    date: date
    total_score: float
    podcast_mentions: int
    newsletter_mentions: int
    disruption_signals: int
    unique_sources: int
    conviction_level: str
    contrarian_signal: str
    timeframe: str = 'unspecified'
    hidden_plays: Optional[Dict] = None
    rank: int = 0

class DashboardDB:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database with schema if it doesn't exist."""
        if not self.db_path.exists() and SCHEMA_PATH.exists():
            with self._get_connection() as conn:
                with open(SCHEMA_PATH, 'r') as f:
                    conn.executescript(f.read())
                print(f"✓ Initialized database at {self.db_path}")
    
    # === Ticker Mentions ===
    
    def add_ticker_mention(self, mention: TickerMention) -> int:
        """Add a ticker mention and return the ID."""
        # Calculate weighted score at insert time
        base = 20.0 if mention.source_type == 'podcast' else 10.0
        weight = 2.0 if mention.source_type == 'podcast' else (1.5 if mention.is_disruption_focused else 0.5)
        conviction_mult = 1.0 + (mention.conviction_score / 100.0)
        weighted = base * weight * conviction_mult

        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO ticker_mentions 
                (ticker, source_type, source_name, episode_title, context,
                 conviction_score, sentiment, timeframe, is_contrarian, is_disruption_focused,
                 weighted_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mention.ticker, mention.source_type, mention.source_name,
                mention.episode_title, mention.context, mention.conviction_score,
                mention.sentiment, mention.timeframe, mention.is_contrarian,
                mention.is_disruption_focused, weighted
            ))
            return cursor.lastrowid
    
    def get_ticker_mentions(self, ticker: str, days: int = 30) -> List[Dict]:
        """Get all mentions for a ticker in the last N days."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM ticker_mentions 
                WHERE ticker = ? AND mention_date >= date('now', ?)
                ORDER BY mention_date DESC
            """, (ticker, f'-{days} days'))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_top_tickers(self, date_filter: date = None, limit: int = 20) -> List[Dict]:
        """Get top tickers by weighted mentions."""
        if date_filter is None:
            date_filter = date.today()
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    ticker,
                    SUM(weighted_score) as total_score,
                    COUNT(CASE WHEN source_type = 'podcast' THEN 1 END) as podcast_count,
                    COUNT(CASE WHEN source_type = 'newsletter' THEN 1 END) as newsletter_count,
                    COUNT(DISTINCT source_name) as unique_sources,
                    AVG(conviction_score) as avg_conviction
                FROM ticker_mentions
                WHERE date(mention_date) = ?
                GROUP BY ticker
                ORDER BY total_score DESC
                LIMIT ?
            """, (date_filter, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    # === Podcast Episodes ===
    
    def add_podcast_episode(self, episode: PodcastEpisode) -> int:
        """Add a podcast episode and return the ID."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO podcast_episodes 
                (podcast_name, episode_title, episode_date, audio_url, transcript_path,
                 summary, key_takeaways, key_tickers, investment_thesis, relevance_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode.podcast_name, episode.episode_title, episode.episode_date,
                episode.audio_url, episode.transcript_path, episode.summary,
                json.dumps(episode.key_takeaways) if episode.key_takeaways else None,
                json.dumps(episode.key_tickers) if episode.key_tickers else None,
                episode.investment_thesis, episode.relevance_score
            ))
            return cursor.lastrowid
    
    def update_podcast_summary(self, episode_id: int, summary: str, 
                               key_takeaways: List[str], key_tickers: List[str],
                               investment_thesis: str):
        """Update podcast with generated summary."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE podcast_episodes 
                SET summary = ?, key_takeaways = ?, key_tickers = ?,
                    investment_thesis = ?, is_processed = 1
                WHERE id = ?
            """, (summary, json.dumps(key_takeaways), json.dumps(key_tickers),
                  investment_thesis, episode_id))
    
    def get_podcast_summaries_for_site(self) -> List[Dict]:
        """Get all podcast summaries ready for website display."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM v_podcast_summaries
            """)
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                # Parse JSON fields
                for field in ['key_takeaways', 'key_tickers']:
                    if result.get(field):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = []
                results.append(result)
            return results
    
    def mark_episode_added_to_site(self, episode_id: int):
        """Mark episode as added to website."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE podcast_episodes SET added_to_site = 1 WHERE id = ?
            """, (episode_id,))
    
    # === Daily Scores ===
    
    def save_daily_scores(self, scores: List[DailyScore]):
        """Save daily aggregated scores."""
        with self._get_connection() as conn:
            for score in scores:
                conn.execute("""
                    INSERT OR REPLACE INTO daily_scores
                    (ticker, date, total_score, podcast_mentions, newsletter_mentions,
                     disruption_signals, unique_sources, conviction_level,
                     contrarian_signal, timeframe, hidden_plays, rank)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (score.ticker, score.date, score.total_score,
                      score.podcast_mentions, score.newsletter_mentions,
                      score.disruption_signals, score.unique_sources,
                      score.conviction_level, score.contrarian_signal,
                      score.timeframe,
                      json.dumps(score.hidden_plays) if score.hidden_plays else None,
                      score.rank))
    
    def get_daily_scores(self, score_date: date = None) -> List[Dict]:
        """Get daily scores for website."""
        with self._get_connection() as conn:
            if score_date is None:
                # Get the most recent date with scores
                cursor = conn.execute("SELECT MAX(date) FROM daily_scores")
                row = cursor.fetchone()
                score_date = row[0] if row and row[0] else date.today()
            
            cursor = conn.execute("""
                SELECT * FROM daily_scores
                WHERE date = ?
                ORDER BY rank, total_score DESC
            """, (score_date,))
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get('hidden_plays'):
                    try:
                        result['hidden_plays'] = json.loads(result['hidden_plays'])
                    except:
                        pass
                results.append(result)
            return results
    
    # === Export for Website ===
    
    def export_for_website(self, output_dir: Path):
        """Export all data needed for website to JSON files."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Export daily scores (tickers)
        scores = self.get_daily_scores()
        with open(output_dir / 'ticker_scores.json', 'w') as f:
            json.dump(scores, f, indent=2, default=str)
        
        # Export podcast summaries
        podcasts = self.get_podcast_summaries_for_site()
        with open(output_dir / 'podcast_summaries.json', 'w') as f:
            json.dump(podcasts, f, indent=2, default=str)
        
        # Export archive data
        archive = self.export_archive_data()
        with open(output_dir / 'archive.json', 'w') as f:
            json.dump(archive, f, indent=2, default=str)
        
        print(f"✓ Exported website data to {output_dir}")
        return {
            'ticker_scores': len(scores),
            'podcast_summaries': len(podcasts),
            'archive_items': sum(len(v) for v in archive.values())
        }
    
    # === Archive Management ===
    
    def export_archive_data(self) -> Dict:
        """Export all archived/historical content."""
        archive = {
            'insights': [],
            'definitions': [],
            'overton': []
        }
        
        with self._get_connection() as conn:
            # Get all insights (both active and archived)
            cursor = conn.execute("""
                SELECT * FROM latest_insights
                ORDER BY source_date DESC
            """)
            for row in cursor.fetchall():
                insight = dict(row)
                if insight.get('tickers_mentioned'):
                    try:
                        insight['tickers_mentioned'] = json.loads(insight['tickers_mentioned'])
                    except:
                        pass
                archive['insights'].append(insight)
            
            # Get all definitions
            cursor = conn.execute("""
                SELECT * FROM definitions
                ORDER BY added_date DESC
            """)
            archive['definitions'] = [dict(row) for row in cursor.fetchall()]
            
            # Get all Overton terms
            cursor = conn.execute("""
                SELECT * FROM overton_terms
                ORDER BY first_detected_date DESC
            """)
            for row in cursor.fetchall():
                term = dict(row)
                if term.get('source_podcasts'):
                    try:
                        term['source_podcasts'] = json.loads(term['source_podcasts'])
                    except:
                        pass
                archive['overton'].append(term)
        
        return archive
    
    def archive_item(self, item_type: str, item_id: int, reason: str = None):
        """Archive an item (move from main display to archive)."""
        with self._get_connection() as conn:
            if item_type == 'insight':
                conn.execute("""
                    UPDATE latest_insights 
                    SET display_on_main = 0, archived_date = date('now'), archived_reason = ?
                    WHERE id = ?
                """, (reason, item_id))
            elif item_type == 'definition':
                conn.execute("""
                    UPDATE definitions 
                    SET display_on_main = 0, archived_date = date('now'), archived_reason = ?
                    WHERE id = ?
                """, (reason, item_id))
            elif item_type == 'overton':
                conn.execute("""
                    UPDATE overton_terms 
                    SET display_on_main = 0, status = 'archived', archived_date = date('now'), archived_reason = ?
                    WHERE id = ?
                """, (reason, item_id))
    
    def get_main_page_content(self) -> Dict:
        """Get only content that should display on main page."""
        content = {
            'insights': [],
            'definitions': [],
            'overton': []
        }
        
        with self._get_connection() as conn:
            # Get active insights (limited to most recent 5)
            # Join with podcast_episodes to get actual episode release date
            cursor = conn.execute("""
                SELECT li.*, pe.episode_date as episode_release_date
                FROM latest_insights li
                LEFT JOIN podcast_episodes pe ON li.podcast_episode_id = pe.id
                WHERE li.display_on_main = 1
                ORDER BY li.display_order, li.source_date DESC
                LIMIT 8
            """)
            content['insights'] = [dict(row) for row in cursor.fetchall()]
            
            # Get active definitions (limited to most relevant)
            cursor = conn.execute("""
                SELECT * FROM definitions
                WHERE display_on_main = 1
                ORDER BY display_order, vote_count DESC
                LIMIT 10
            """)
            content['definitions'] = [dict(row) for row in cursor.fetchall()]
            
            # Get active Overton terms (limited to emerging)
            cursor = conn.execute("""
                SELECT * FROM overton_terms
                WHERE display_on_main = 1 AND status = 'active'
                ORDER BY mention_count DESC
                LIMIT 8
            """)
            content['overton'] = [dict(row) for row in cursor.fetchall()]
        
        return content
    
    # === Statistics ===
    
    def get_stats(self) -> Dict:
        """Get database statistics."""
        with self._get_connection() as conn:
            stats = {}
            
            # Count by table
            for table in ['ticker_mentions', 'podcast_episodes', 'newsletters', 'daily_scores']:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            
            # Today's mentions
            cursor = conn.execute("""
                SELECT source_type, COUNT(*) as count 
                FROM ticker_mentions 
                WHERE date(mention_date) = date('now')
                GROUP BY source_type
            """)
            stats['today_mentions'] = {row['source_type']: row['count'] for row in cursor.fetchall()}
            
            return stats
    
    # === Deep Dive Content ===
    
    def get_deep_dive_content(self, insight_id: int) -> Optional[Dict]:
        """Get detailed Deep Dive content for a specific insight."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM deep_dive_content
                WHERE insight_id = ?
            """, (insight_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            content = dict(row)
            
            # Parse JSON fields
            for field in ['key_takeaways_detailed', 'ticker_analysis', 'risk_factors', 
                         'contrarian_signals', 'catalysts', 'related_insights']:
                if content.get(field):
                    try:
                        content[field] = json.loads(content[field])
                    except:
                        pass
            
            return content
    
    def get_all_deep_dive_content(self) -> Dict[str, Dict]:
        """Get all Deep Dive content indexed by insight title."""
        deepdives = {}
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT ddc.*, li.title as insight_title, li.source_name, li.source_date
                FROM deep_dive_content ddc
                JOIN latest_insights li ON ddc.insight_id = li.id
            """)
            
            for row in cursor.fetchall():
                content = dict(row)
                
                # Parse JSON fields
                for field in ['key_takeaways_detailed', 'ticker_analysis', 'risk_factors',
                             'contrarian_signals', 'catalysts', 'related_insights']:
                    if content.get(field):
                        try:
                            content[field] = json.loads(content[field])
                        except:
                            pass
                
                # Key by insight_id (integer) — stable, title-change-proof
                deepdives[str(content['insight_id'])] = content
        
        return deepdives
    
    # === Suggested Terms ===
    
    def get_suggested_terms_for_website(self, limit: int = 1) -> List[Dict]:
        """Get top suggested terms to display on website."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM v_priority_suggestions
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_pending_suggestions(self) -> List[Dict]:
        """Get all pending suggestions for admin review."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM suggested_terms
                WHERE status = 'pending'
                ORDER BY relevance_score DESC, mention_count DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

# Convenience function for quick access
def get_db() -> DashboardDB:
    """Get database instance."""
    return DashboardDB()

if __name__ == "__main__":
    # Test the database
    db = get_db()
    stats = db.get_stats()
    print("Database Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Test deep dive content
    deepdives = db.get_all_deep_dive_content()
    print(f"\nDeep Dive entries: {len(deepdives)}")
    for key in deepdives:
        print(f"  - {key}")