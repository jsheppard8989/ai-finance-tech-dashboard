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

from workspace_paths import DB_PATH, workspace_root
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Main-page Overton list size (historically 8; +5 for denser board)
OVERTON_MAIN_PAGE_LIMIT = 13
# Same visual scale as pundit Presence bars (decayed score before capping to 100%)
RESONANCE_SCORE_CAP = 4.0


def _sort_pundits_for_site(pundits: List[Dict]) -> List[Dict]:
    """Most recent appearance first; frequency breaks recency ties."""
    ordered = sorted(
        pundits,
        key=lambda p: ((p.get("name") or "").casefold(), p.get("id") or 0),
    )
    ordered.sort(key=lambda p: p.get("mention_score") or 0, reverse=True)
    ordered.sort(key=lambda p: str(p.get("last_seen") or ""), reverse=True)
    return ordered


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


def _transcript_proof_snippet(transcript_path: Optional[str], max_chars: int = 240) -> str:
    """First ~max_chars chars of on-disk transcript (on-hand proof line for pundit cards)."""
    if not transcript_path:
        return ""
    p = Path(transcript_path.strip())
    if not p.is_absolute():
        p = (workspace_root() / p).resolve()
    if not p.is_file():
        return ""
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    txt = " ".join(txt.split())
    return txt[:max_chars].strip()


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
        # Ensure podcast_guests and new semantic tables exist (migration for existing DBs)
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS podcast_guests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE,
                    bio TEXT,
                    known_for TEXT,
                    last_main_idea TEXT,
                    last_episode_id INTEGER,
                    last_episode_title TEXT,
                    last_podcast_name TEXT,
                    last_episode_date DATE,
                    appearance_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (last_episode_id) REFERENCES podcast_episodes(id)
                )
            """)
            # guest_name column for episode-level association
            try:
                conn.execute("ALTER TABLE podcast_episodes ADD COLUMN guest_name TEXT")
            except sqlite3.OperationalError:
                pass

            try:
                conn.execute("ALTER TABLE podcast_episodes ADD COLUMN rss_guid TEXT")
            except sqlite3.OperationalError:
                pass

            suggested_terms_sql = SCHEMA_PATH.parent / "schema_suggested_terms.sql"
            if suggested_terms_sql.exists():
                with open(suggested_terms_sql, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())

            # Semantic layer tables: entities, appearances, ideas
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    slug TEXT UNIQUE,
                    bio TEXT,
                    known_for TEXT,
                    net_worth_usd REAL,
                    net_worth_source TEXT,
                    net_worth_updated_at TIMESTAMP,
                    voice_tone TEXT,
                    voice_style TEXT,
                    voice_delivery_notes TEXT,
                    voice_profile_updated_at TIMESTAMP,
                    source_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(LOWER(name))")
            # Backfill columns for existing DBs
            for col_sql in [
                "ALTER TABLE entities ADD COLUMN net_worth_usd REAL",
                "ALTER TABLE entities ADD COLUMN net_worth_source TEXT",
                "ALTER TABLE entities ADD COLUMN net_worth_updated_at TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN voice_tone TEXT",
                "ALTER TABLE entities ADD COLUMN voice_style TEXT",
                "ALTER TABLE entities ADD COLUMN voice_delivery_notes TEXT",
                "ALTER TABLE entities ADD COLUMN voice_profile_updated_at TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN grokipedia_url TEXT",
                "ALTER TABLE entities ADD COLUMN grokipedia_fetched_at TIMESTAMP",
                "ALTER TABLE entities ADD COLUMN pundit_profile_json TEXT",
            ]:
                try:
                    conn.execute(col_sql)
                except sqlite3.OperationalError:
                    pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS appearances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL CHECK (source_type IN ('podcast','newsletter')),
                    source_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    prominence INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES entities(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_appearances_entity ON appearances(entity_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_appearances_source ON appearances(source_type, source_id)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL CHECK (source_type IN ('podcast','newsletter')),
                    source_id INTEGER NOT NULL,
                    speaker_name TEXT,
                    summary TEXT NOT NULL,
                    thesis TEXT,
                    tickers_json TEXT,
                    sentiment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ideas_source ON ideas(source_type, source_id)")

            # Episode + speaker attribution for emerging → Overton pipeline
            for col_sql in [
                "ALTER TABLE suggested_terms ADD COLUMN first_seen_episode_id INTEGER",
                "ALTER TABLE suggested_terms ADD COLUMN last_seen_episode_id INTEGER",
                "ALTER TABLE suggested_terms ADD COLUMN first_seen_speaker TEXT",
                "ALTER TABLE suggested_terms ADD COLUMN last_seen_speaker TEXT",
                "ALTER TABLE suggested_terms ADD COLUMN speaker_quote TEXT",
            ]:
                try:
                    conn.execute(col_sql)
                except sqlite3.OperationalError:
                    pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS term_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_term TEXT NOT NULL,
                    alias TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_term_aliases_canonical ON term_aliases(canonical_term)"
            )
            self._seed_term_aliases(conn)
            for col_sql in [
                "ALTER TABLE overton_terms ADD COLUMN first_detected_episode_id INTEGER",
                "ALTER TABLE overton_terms ADD COLUMN first_detected_speaker TEXT",
                "ALTER TABLE overton_terms ADD COLUMN last_mentioned_episode_id INTEGER",
                "ALTER TABLE overton_terms ADD COLUMN last_mentioned_speaker TEXT",
            ]:
                try:
                    conn.execute(col_sql)
                except sqlite3.OperationalError:
                    pass

    # === Term Aliases ===

    def _seed_term_aliases(self, conn) -> None:
        """Load term_aliases.json into term_aliases table when empty."""
        count = conn.execute("SELECT COUNT(*) AS n FROM term_aliases").fetchone()["n"]
        if count:
            return
        json_path = Path(__file__).parent / "term_aliases.json"
        if not json_path.exists():
            return
        data = json.loads(json_path.read_text(encoding="utf-8"))
        for group in data.get("merges") or []:
            canonical = (group.get("canonical") or "").strip()
            if not canonical:
                continue
            for alias in group.get("aliases") or []:
                alias_clean = (alias or "").strip()
                if not alias_clean or alias_clean.lower() == canonical.lower():
                    continue
                try:
                    conn.execute(
                        "INSERT INTO term_aliases (canonical_term, alias) VALUES (?, ?)",
                        (canonical, alias_clean),
                    )
                except sqlite3.IntegrityError:
                    pass

    def seed_term_aliases_from_json(self) -> int:
        """Insert any new aliases from term_aliases.json (idempotent). Returns rows added."""
        json_path = Path(__file__).parent / "term_aliases.json"
        if not json_path.exists():
            return 0
        data = json.loads(json_path.read_text(encoding="utf-8"))
        added = 0
        with self._get_connection() as conn:
            for group in data.get("merges") or []:
                canonical = (group.get("canonical") or "").strip()
                if not canonical:
                    continue
                for alias in group.get("aliases") or []:
                    alias_clean = (alias or "").strip()
                    if not alias_clean or alias_clean.lower() == canonical.lower():
                        continue
                    try:
                        conn.execute(
                            "INSERT INTO term_aliases (canonical_term, alias) VALUES (?, ?)",
                            (canonical, alias_clean),
                        )
                        added += 1
                    except sqlite3.IntegrityError:
                        pass
        return added

    def resolve_term(self, raw: str) -> str:
        """Map alias strings to canonical term (case preserved from canonical row)."""
        raw_clean = (raw or "").strip()
        if not raw_clean:
            return raw_clean
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT canonical_term FROM term_aliases
                WHERE LOWER(TRIM(alias)) = LOWER(?)
                """,
                (raw_clean,),
            ).fetchone()
            if row:
                return row["canonical_term"]
            row = conn.execute(
                """
                SELECT canonical_term FROM term_aliases
                WHERE LOWER(TRIM(canonical_term)) = LOWER(?)
                LIMIT 1
                """,
                (raw_clean,),
            ).fetchone()
            if row:
                return row["canonical_term"]
        return raw_clean

    def get_term_alias_groups(self) -> Dict[str, List[str]]:
        """Return canonical_term -> list of alias strings."""
        groups: Dict[str, List[str]] = {}
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT canonical_term, alias FROM term_aliases ORDER BY canonical_term, alias"
            ).fetchall()
        for row in rows:
            canonical = (row["canonical_term"] or "").strip()
            alias = (row["alias"] or "").strip()
            if not canonical:
                continue
            groups.setdefault(canonical, []).append(alias)
        return groups

    def get_top_tracked_terms_for_glossary(self, limit: int = 60) -> List[Dict]:
        """Top Overton terms by mention count for prompt glossary supplementation."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT term, mention_count FROM overton_terms
                WHERE status = 'active'
                ORDER BY mention_count DESC, term ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # === Ticker Aliases ===

    def resolve_ticker(self, raw: str) -> str:
        """
        Resolve a raw mention string to a canonical Yahoo Finance ticker.
        Looks up ticker_aliases table (case-insensitive). Returns the
        canonical ticker if found, otherwise returns the original uppercased.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT ticker FROM ticker_aliases WHERE alias = ?",
                (raw.lower().strip(),)
            ).fetchone()
        if row:
            return row["ticker"]
        return raw.upper().strip()

    def add_ticker_alias(self, alias: str, ticker: str, description: str = "") -> bool:
        """Add a new ticker alias mapping. Returns True if inserted, False if already exists."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO ticker_aliases (alias, ticker, description) VALUES (?, ?, ?)",
                    (alias.lower().strip(), ticker.upper().strip(), description)
                )
            return True
        except sqlite3.IntegrityError:
            return False  # Already exists

    def get_ticker_aliases(self) -> List[Dict]:
        """Return all alias mappings."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT alias, ticker, description FROM ticker_aliases ORDER BY ticker, alias"
            ).fetchall()
        return [dict(r) for r in rows]

    # === Ticker Mentions ===
    
    def add_ticker_mention(self, mention: TickerMention) -> int:
        """Add a ticker mention and return the ID."""
        # Resolve alias → canonical ticker before storing
        mention.ticker = self.resolve_ticker(mention.ticker)

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
    
    def get_all_ticker_scores(self, limit: int = 50) -> List[Dict]:
        """Get all tickers ranked by total weighted score from all mentions."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    ticker,
                    SUM(weighted_score) as total_score,
                    COUNT(*) as raw_mention_count,
                    COUNT(DISTINCT source_type) as unique_sources,
                    SUM(CASE WHEN source_type = 'podcast' THEN 1 ELSE 0 END) as podcast_mentions,
                    SUM(CASE WHEN source_type = 'newsletter' THEN 1 ELSE 0 END) as newsletter_mentions
                FROM ticker_mentions
                WHERE ticker NOT IN ('S&P', 'Nasdaq', 'Russell', 'Semiconductors')
                GROUP BY ticker
                ORDER BY total_score DESC
                LIMIT ?
            """, (limit,))
            
            results = []
            rank = 1
            for row in cursor.fetchall():
                results.append({
                    'ticker': row['ticker'],
                    'total_score': round(row['total_score'], 1),
                    'raw_mention_count': row['raw_mention_count'],
                    'unique_sources': row['unique_sources'],
                    'podcast_mentions': row['podcast_mentions'],
                    'newsletter_mentions': row['newsletter_mentions'],
                    'rank': rank,
                    'score': round(row['total_score'], 1),  # For frontend compatibility
                    'mentions': row['raw_mention_count'],  # For frontend compatibility
                    'conviction_level': 'medium',  # Default, can be enhanced
                    'contrarian_signal': 'neutral',  # Default, can be enhanced
                    'timeframe': 'long_term',  # Default, can be enhanced
                    'contexts': []  # Can be populated with actual contexts if needed
                })
                rank += 1
            return results

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

        # Hard-delete placeholder-ish pundit entities before any export happens.
        # This ensures old/bad entities can't linger in the UI even if they were
        # created before the placeholder filters were added.
        try:
            self.cleanup_placeholder_entities()
        except Exception as e:
            print(f"  ⚠ Placeholder cleanup skipped: {e}")
        try:
            n_ex = self.cleanup_excluded_pundit_entities()
            if n_ex:
                print(f"  ✓ Removed {n_ex} excluded co-host / non-pundit entity row(s)")
        except Exception as e:
            print(f"  ⚠ Excluded pundit cleanup skipped: {e}")
        
        from site_text_sanitize import strip_cjk_public_text

        # Export all tickers ranked by total weighted score from ticker_mentions
        scores = strip_cjk_public_text(self.get_all_ticker_scores())
        with open(output_dir / 'ticker_scores.json', 'w') as f:
            json.dump(scores, f, indent=2, default=str)

        # Export podcast summaries
        podcasts = strip_cjk_public_text(self.get_podcast_summaries_for_site())
        with open(output_dir / 'podcast_summaries.json', 'w') as f:
            json.dump(podcasts, f, indent=2, default=str)

        # Export archive data
        archive = strip_cjk_public_text(self.export_archive_data())
        with open(output_dir / 'archive.json', 'w') as f:
            json.dump(archive, f, indent=2, default=str)

        # Export podcast guests for site (legacy path)
        guests = strip_cjk_public_text(self.get_podcast_guests_for_site(limit=30))
        with open(output_dir / 'podcast_guests.json', 'w') as f:
            json.dump(guests, f, indent=2, default=str)

        # Export pundits from semantic layer: people with guest_primary appearances + last episode / main idea.
        # Full roster goes to pundits.json / data.js; index.html shows top 20 by slice; archive.html lists all.
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    e.id,
                    e.name,
                    e.slug,
                    e.bio,
                    e.known_for,
                    e.net_worth_usd,
                    e.net_worth_source,
                    e.net_worth_updated_at,
                    e.voice_tone,
                    e.voice_style,
                    e.voice_delivery_notes,
                    e.voice_profile_updated_at,
                    e.grokipedia_url,
                    e.grokipedia_fetched_at,
                    e.pundit_profile_json,
                    a.created_at AS last_seen,
                    pe.episode_title AS last_episode_title,
                    pe.podcast_name AS last_podcast_name,
                    pe.episode_date AS last_episode_date,
                    pe.investment_thesis,
                    pe.key_takeaways,
                    pe.transcript_path AS transcript_path,
                    agg.appearance_count
                FROM entities e
                JOIN appearances a ON a.entity_id = e.id AND LOWER(a.role) = 'guest_primary' AND a.source_type = 'podcast'
                JOIN (
                    SELECT entity_id, COUNT(*) AS appearance_count
                    FROM appearances
                    WHERE LOWER(role) = 'guest_primary' AND source_type = 'podcast'
                    GROUP BY entity_id
                ) agg ON agg.entity_id = e.id
                JOIN (
                    SELECT entity_id, MAX(id) AS mid
                    FROM appearances
                    WHERE LOWER(role) = 'guest_primary' AND source_type = 'podcast'
                    GROUP BY entity_id
                ) latest ON latest.entity_id = a.entity_id AND a.id = latest.mid
                LEFT JOIN podcast_episodes pe ON pe.id = a.source_id
                WHERE e.type = 'person'
                ORDER BY a.created_at DESC, agg.appearance_count DESC, e.name COLLATE NOCASE ASC
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]

            from person_name_safety import is_placeholder_person_name
            from pundit_exclusions import is_excluded_pundit_name

            pundits = []
            for row in rows:
                # Filter out known non-pundit co-hosts / recurring hosts
                name = (row.get('name') or '').strip()
                if is_excluded_pundit_name(name):
                    continue
                if is_placeholder_person_name(name):
                    continue

                appearance_count = row.get('appearance_count') or 1
                # Simple exponential decay on appearances based on last_seen timestamp
                decayed_score = appearance_count
                last_seen_raw = row.get('last_seen')
                if last_seen_raw:
                    try:
                        from math import exp, log
                        # Half-life of 30 days
                        half_life_days = 30.0
                        lam = log(2.0) / half_life_days
                        from datetime import datetime as _dt
                        last_dt = _dt.fromisoformat(str(last_seen_raw))
                        days_since = ( _dt.utcnow() - last_dt ).days
                        if days_since > 0:
                            decayed_score = appearance_count * exp(-lam * days_since)
                    except Exception:
                        decayed_score = appearance_count

                p = {
                    'id': row['id'],
                    'name': row['name'],
                    'slug': row['slug'],
                    'bio': row['bio'],
                    'known_for': row['known_for'],
                    'net_worth_usd': row.get('net_worth_usd'),
                    'net_worth_source': row.get('net_worth_source'),
                    'net_worth_updated_at': row.get('net_worth_updated_at'),
                    'voice_tone': row.get('voice_tone'),
                    'voice_style': row.get('voice_style'),
                    'voice_delivery_notes': row.get('voice_delivery_notes'),
                    'voice_profile_updated_at': row.get('voice_profile_updated_at'),
                    'last_seen': row['last_seen'],
                    'last_episode_title': row['last_episode_title'],
                    'last_podcast_name': row['last_podcast_name'],
                    'last_episode_date': row['last_episode_date'],
                    'mention_score': appearance_count,
                    'mention_score_decayed': round(decayed_score, 2),
                }
                # Last main idea: from that episode's investment_thesis or first key_takeaway (AI JSON)
                thesis = (row.get('investment_thesis') or '').strip()
                takeaways = row.get('key_takeaways')
                if isinstance(takeaways, str) and takeaways:
                    try:
                        takeaways = json.loads(takeaways)
                    except Exception:
                        takeaways = []
                if not isinstance(takeaways, list):
                    takeaways = []
                if thesis:
                    p['last_main_idea'] = thesis[:500]
                elif takeaways:
                    p['last_main_idea'] = (takeaways[0] or '')[:500]
                else:
                    p['last_main_idea'] = None

                supporting_takeaway = None
                if len(takeaways) > 1:
                    supporting_takeaway = ((takeaways[1] or "").strip()[:420] or None)

                snip = _transcript_proof_snippet(row.get("transcript_path"))
                if not snip and supporting_takeaway:
                    snip = supporting_takeaway[:240]

                cite_parts = []
                if row.get("last_podcast_name"):
                    cite_parts.append(str(row["last_podcast_name"]))
                if row.get("last_episode_date"):
                    cite_parts.append(str(row["last_episode_date"])[:10])
                if row.get("last_episode_title"):
                    cite_parts.append(str(row["last_episode_title"]))
                p["last_proof_cite"] = " • ".join(cite_parts)[:500] if cite_parts else None
                p["last_proof_snippet"] = snip or None
                p["supporting_takeaway"] = supporting_takeaway

                # Grokipedia-sourced micro-profile (trimmed for browser JSON size)
                raw_prof = row.get("pundit_profile_json")
                p["grokipedia_url"] = row.get("grokipedia_url")
                p["grokipedia_fetched_at"] = row.get("grokipedia_fetched_at")
                p["pundit_profile"] = None
                if raw_prof:
                    try:
                        full = json.loads(raw_prof) if isinstance(raw_prof, str) else raw_prof
                    except Exception:
                        full = None
                    if isinstance(full, dict):
                        sections = full.get("sections") or []
                        slim_sections = []
                        if isinstance(sections, list):
                            for s in sections[:10]:
                                if not isinstance(s, dict):
                                    continue
                                body = (s.get("body") or "")[:520]
                                slim_sections.append(
                                    {"heading": s.get("heading") or "", "body": body}
                                )
                        leads = full.get("lead_paragraphs") or []
                        if not isinstance(leads, list):
                            leads = []
                        p["pundit_profile"] = {
                            "source": full.get("source"),
                            "source_model": full.get("source_model"),
                            "source_url": full.get("source_url"),
                            "page_title": full.get("page_title"),
                            "fetched_at": full.get("fetched_at"),
                            "cliff_notes": (full.get("cliff_notes") or "")[:3200],
                            "derived": full.get("derived") or {},
                            "infobox": full.get("infobox") or {},
                            "lead_paragraphs": [str(x)[:900] for x in leads[:6]],
                            "sections": slim_sections,
                        }
                # Friendly display string for popup.
                nw = p.get('net_worth_usd')
                if isinstance(nw, (int, float)) and nw > 0:
                    if nw >= 1_000_000_000:
                        p['net_worth'] = f"${nw / 1_000_000_000:.2f}B"
                    elif nw >= 1_000_000:
                        p['net_worth'] = f"${nw / 1_000_000:.1f}M"
                    else:
                        p['net_worth'] = f"${nw:,.0f}"
                pundits.append(p)

        pundits = _sort_pundits_for_site(pundits)
        pundits = strip_cjk_public_text(pundits)
        with open(output_dir / 'pundits.json', 'w') as f:
            json.dump(pundits, f, indent=2, default=str)

        print(f"✓ Exported website data to {output_dir}")
        return {
            'ticker_scores': len(scores),
            'podcast_summaries': len(podcasts),
            'archive_items': sum(len(v) for v in archive.values()),
            'podcast_guests': len(guests),
            'pundits': len(pundits),
        }

    def cleanup_placeholder_entities(self) -> int:
        """
        Delete placeholder-ish person entities and their appearances.

        This is a safety net for past data drift (before we added ingestion/enrichment
        filters). It should be conservative but aligned with `person_name_safety`.
        """
        from person_name_safety import is_placeholder_person_name

        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, name
                FROM entities
                WHERE type = 'person'
                """
            )
            bad_ids = []
            for r in cur.fetchall():
                name = (r["name"] or "").strip()
                if is_placeholder_person_name(name):
                    bad_ids.append(int(r["id"]))

            if not bad_ids:
                return 0

            placeholders = ",".join("?" * len(bad_ids))
            conn.execute(
                f"DELETE FROM appearances WHERE entity_id IN ({placeholders})",
                bad_ids,
            )
            conn.execute(
                f"DELETE FROM entities WHERE id IN ({placeholders})",
                bad_ids,
            )
            return len(bad_ids)

    def cleanup_excluded_pundit_entities(self) -> int:
        """
        Delete person entities whose names are on the non-pundit exclusion list
        (co-hosts, ASR manglings, etc.) and their appearances.
        """
        from pundit_exclusions import is_excluded_pundit_name

        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, name
                FROM entities
                WHERE type = 'person'
                """
            )
            bad_ids: list[int] = []
            for r in cur.fetchall():
                name = (r["name"] or "").strip()
                if is_excluded_pundit_name(name):
                    bad_ids.append(int(r["id"]))

            if not bad_ids:
                return 0

            placeholders = ",".join("?" * len(bad_ids))
            conn.execute(
                f"DELETE FROM appearances WHERE entity_id IN ({placeholders})",
                bad_ids,
            )
            conn.execute(
                f"DELETE FROM entities WHERE id IN ({placeholders})",
                bad_ids,
            )
            return len(bad_ids)

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
            
            # Legacy definitions are no longer used for the Overton Window.
            # Keep the key for backward compatibility, but leave it empty.
            archive['definitions'] = []
            
            # Get all Overton terms (canonical source for Overton Window)
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
            # Active insights: only those with a Deep Dive row (modal + cards stay in sync).
            # display_on_main is managed by the pipeline after generate_deepdives.py succeeds.
            cursor = conn.execute("""
                SELECT li.*, pe.episode_date as episode_release_date, pe.guest_name as guest_name, pe.key_tickers as key_tickers
                FROM latest_insights li
                INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                LEFT JOIN podcast_episodes pe ON li.podcast_episode_id = pe.id
                WHERE li.display_on_main = 1
                ORDER BY li.display_order, li.source_date DESC
                LIMIT 8
            """)
            rows = [dict(row) for row in cursor.fetchall()]
            for r in rows:
                raw = r.get('key_tickers')
                if isinstance(raw, str) and raw:
                    try:
                        r['key_tickers'] = json.loads(raw) if raw.strip() else []
                    except Exception:
                        r['key_tickers'] = []
                elif not isinstance(raw, list):
                    r['key_tickers'] = []
            content['insights'] = rows
            
            # Get active definitions (limited to most relevant)
            cursor = conn.execute("""
                SELECT * FROM definitions
                WHERE display_on_main = 1
                ORDER BY display_order, vote_count DESC
                LIMIT 10
            """)
            content['definitions'] = [dict(row) for row in cursor.fetchall()]
            
            # Active Overton terms: rank by Resonance score (mentions × 30-day recency half-life),
            # same family as pundit Presence decay in export_for_website — then take top N.
            cursor = conn.execute("""
                SELECT * FROM overton_terms
                WHERE display_on_main = 1 AND status = 'active'
            """)
            overton_rows = [dict(row) for row in cursor.fetchall()]

            def _episode_brief(eid) -> Tuple[Optional[str], Optional[str], Optional[str]]:
                if not eid:
                    return None, None, None
                cur = conn.execute(
                    """
                    SELECT podcast_name, episode_title, episode_date
                    FROM podcast_episodes WHERE id = ?
                    """,
                    (int(eid),),
                )
                r = cur.fetchone()
                if not r:
                    return None, None, None
                d = r["episode_date"]
                ds = str(d)[:10] if d is not None else None
                return r["podcast_name"], r["episode_title"], ds

            try:
                from datetime import date as _date
                from math import exp as _exp, log as _log

                half_life_days = 30.0
                lam = _log(2.0) / half_life_days
                today = _date.today()

                def _overton_attention_score(term: dict) -> float:
                    mc = int(term.get("mention_count") or 0)
                    last_raw = term.get("last_mentioned_date") or term.get("first_detected_date")
                    days = 0
                    if last_raw:
                        try:
                            if isinstance(last_raw, str):
                                ld = _date.fromisoformat(str(last_raw)[:10])
                            elif hasattr(last_raw, "year"):
                                ld = last_raw
                            else:
                                ld = today
                            days = max(0, (today - ld).days)
                        except Exception:
                            days = 0
                    return float(mc) * _exp(-lam * float(days))

                for t in overton_rows:
                    t["overton_score"] = round(_overton_attention_score(t), 2)
                    sc = float(t.get("overton_score") or 0.0)
                    t["resonance_pct"] = int(
                        max(0, min(100, round(100 * min(1.0, sc / float(RESONANCE_SCORE_CAP)))))
                    )
                    fp, ft, fd = _episode_brief(t.get("first_detected_episode_id"))
                    t["first_detected_podcast"] = fp
                    t["first_detected_episode_title"] = ft
                    t["first_detected_episode_date"] = fd
                    lp, lt, ld = _episode_brief(t.get("last_mentioned_episode_id"))
                    t["last_mentioned_podcast"] = lp
                    t["last_mentioned_episode_title"] = lt
                    t["last_mentioned_episode_date"] = ld
                overton_rows.sort(
                    key=lambda t: (
                        float(t.get("overton_score") or 0),
                        int(t.get("mention_count") or 0),
                    ),
                    reverse=True,
                )
            except Exception:
                for t in overton_rows:
                    t["overton_score"] = float(int(t.get("mention_count") or 0))
                    sc = float(t.get("overton_score") or 0.0)
                    t["resonance_pct"] = int(
                        max(0, min(100, round(100 * min(1.0, sc / float(RESONANCE_SCORE_CAP)))))
                    )
                    fp, ft, fd = _episode_brief(t.get("first_detected_episode_id"))
                    t["first_detected_podcast"] = fp
                    t["first_detected_episode_title"] = ft
                    t["first_detected_episode_date"] = fd
                    lp, lt, ld = _episode_brief(t.get("last_mentioned_episode_id"))
                    t["last_mentioned_podcast"] = lp
                    t["last_mentioned_episode_title"] = lt
                    t["last_mentioned_episode_date"] = ld
                overton_rows.sort(
                    key=lambda t: (float(t.get("overton_score") or 0),),
                    reverse=True,
                )
            content["overton"] = overton_rows[:OVERTON_MAIN_PAGE_LIMIT]
        
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
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM overton_terms")
                stats['overton_terms_total'] = cursor.fetchone()[0]
            except Exception:
                stats['overton_terms_total'] = 0
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM latest_insights")
                stats['latest_insights_total'] = cursor.fetchone()[0]
            except Exception:
                stats['latest_insights_total'] = 0
            
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
                         'contrarian_signals', 'catalysts', 'related_insights', 'falsification_tracks']:
                if content.get(field):
                    try:
                        content[field] = json.loads(content[field])
                    except:
                        pass
            
            return content
    
    def get_all_deep_dive_content(self) -> Dict[str, Dict]:
        """Get all Deep Dive content indexed by insight_id. Includes key_tickers from linked episode (AI JSON) for filtering."""
        deepdives = {}
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT ddc.*, li.title as insight_title, li.source_name, li.source_date, pe.key_tickers
                FROM deep_dive_content ddc
                JOIN latest_insights li ON ddc.insight_id = li.id
                LEFT JOIN podcast_episodes pe ON li.podcast_episode_id = pe.id
            """)
            
            for row in cursor.fetchall():
                content = dict(row)
                
                # Parse JSON fields
                for field in ['key_takeaways_detailed', 'ticker_analysis', 'risk_factors',
                             'contrarian_signals', 'catalysts', 'related_insights', 'falsification_tracks']:
                    if content.get(field):
                        try:
                            content[field] = json.loads(content[field])
                        except:
                            pass
                
                # key_tickers from episode: only show tickers from AI JSON in Deep Dive
                raw = content.get('key_tickers')
                if isinstance(raw, str) and raw:
                    try:
                        content['key_tickers'] = json.loads(raw) if raw.strip() else []
                    except Exception:
                        content['key_tickers'] = []
                elif isinstance(raw, list):
                    content['key_tickers'] = raw
                else:
                    content['key_tickers'] = []
                
                # Key by insight_id (integer) — stable, title-change-proof
                deepdives[str(content['insight_id'])] = content
        
        return deepdives
    
    # === Suggested Terms ===
    
    def get_suggested_terms_for_website(self, limit: int = 4) -> List[Dict]:
        """Get suggested terms for the Emerging Terms box (pending only).

        Uses **recency first** (newest `submitted_date`), then priority score, so the
        box reflects fresh transcript extractions—not only the highest mention_count
        generics. (Promoted terms use status != pending and are excluded here; they
        move to Definitions / Overton via auto_curate_terms.)

        Note: SQLite ignores ORDER BY inside simple views when the outer query has no
        ORDER BY; this query is explicit and deterministic.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    id,
                    term,
                    definition,
                    investment_implications,
                    source_type,
                    mention_count,
                    source_diversity,
                    relevance_score,
                    submitted_date,
                    (mention_count * 10 + source_diversity * 20 + relevance_score)
                        AS priority_score
                FROM suggested_terms
                WHERE status = 'pending'
                ORDER BY datetime(submitted_date) DESC, priority_score DESC
                LIMIT ?
                """,
                (limit,),
            )
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

    def upsert_suggested_term_from_ai(
        self,
        term: str,
        definition: Optional[str] = None,
        investment_implications: Optional[str] = None,
        source_context: Optional[str] = None,
        *,
        episode_id: Optional[int] = None,
        detected_by: Optional[str] = None,
        speaker_quote: Optional[str] = None,
    ) -> bool:
        """Insert or update suggested_terms from AI episode analysis. Returns True if new."""
        term_clean = self.resolve_term((term or "").strip())
        if not term_clean or len(term_clean) < 3:
            return False
        quote = (speaker_quote or "").strip()[:200] or None
        db_episode_id = int(episode_id) if episode_id is not None else None
        speaker = (detected_by or "").strip() or None
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, mention_count, last_seen_episode_id
                FROM suggested_terms WHERE LOWER(TRIM(term)) = LOWER(?)
                """,
                (term_clean,),
            ).fetchone()
            if row:
                same_episode = False
                if db_episode_id is not None and row["last_seen_episode_id"] is not None:
                    try:
                        same_episode = int(row["last_seen_episode_id"]) == int(db_episode_id)
                    except (TypeError, ValueError):
                        same_episode = False

                sets: List[str] = [
                    "definition = COALESCE(?, definition)",
                    "investment_implications = COALESCE(?, investment_implications)",
                    "source_context = COALESCE(?, source_context)",
                    "speaker_quote = COALESCE(?, speaker_quote)",
                ]
                params: list = [definition, investment_implications, source_context, quote]

                if not same_episode:
                    sets.extend([
                        "mention_count = mention_count + 1",
                        "last_mentioned_date = date('now')",
                        "relevance_score = MIN(COALESCE(relevance_score, 50) + 5, 100)",
                    ])
                    if db_episode_id is not None:
                        prev_last = row["last_seen_episode_id"]
                        try:
                            new_episode = prev_last is None or int(prev_last) != int(db_episode_id)
                        except (TypeError, ValueError):
                            new_episode = True
                        if new_episode:
                            sets.append("source_diversity = source_diversity + 1")
                        sets.append("last_seen_episode_id = ?")
                        params.append(db_episode_id)
                    if speaker:
                        sets.append("last_seen_speaker = ?")
                        params.append(speaker)
                elif speaker:
                    sets.append("last_seen_speaker = COALESCE(last_seen_speaker, ?)")
                    params.append(speaker)

                params.append(row["id"])
                conn.execute(
                    f"UPDATE suggested_terms SET {', '.join(sets)} WHERE id = ?",
                    tuple(params),
                )
                self.sync_overton_from_suggested(conn, term_clean)
                return False
            conn.execute(
                """
                INSERT INTO suggested_terms
                (term, definition, investment_implications, source_type, source_context,
                 mention_count, source_diversity, relevance_score, last_mentioned_date, status,
                 first_seen_episode_id, last_seen_episode_id, first_seen_speaker, last_seen_speaker,
                 speaker_quote)
                VALUES (?, ?, ?, 'auto_extracted', ?, 1, 1, 50, date('now'), 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    term_clean,
                    definition,
                    investment_implications,
                    source_context,
                    db_episode_id,
                    db_episode_id,
                    speaker,
                    speaker,
                    quote,
                ),
            )
            return True

    def record_tracked_term_episode_mention(
        self,
        conn,
        term: str,
        *,
        episode_id: int,
        detected_by: Optional[str] = None,
    ) -> bool:
        """
        Increment mention counts when a known term appears in an episode transcript.
        Skips if this episode was already recorded as last_seen for the term.
        """
        term_clean = self.resolve_term((term or "").strip())
        if not term_clean:
            return False
        eid = int(episode_id)
        speaker = (detected_by or "").strip() or None

        row = conn.execute(
            """
            SELECT id, last_seen_episode_id, first_seen_episode_id
            FROM suggested_terms WHERE LOWER(TRIM(term)) = LOWER(?)
            """,
            (term_clean,),
        ).fetchone()
        if row and row["last_seen_episode_id"] is not None:
            try:
                if int(row["last_seen_episode_id"]) == eid:
                    return False
            except (TypeError, ValueError):
                pass

        ot_row = conn.execute(
            """
            SELECT id, last_mentioned_episode_id, first_detected_episode_id, mention_count
            FROM overton_terms
            WHERE LOWER(TRIM(term)) = LOWER(?) AND status = 'active'
            """,
            (term_clean,),
        ).fetchone()
        if not row and ot_row and ot_row["last_mentioned_episode_id"] is not None:
            try:
                if int(ot_row["last_mentioned_episode_id"]) == eid:
                    return False
            except (TypeError, ValueError):
                pass

        if row:
            sets = [
                "mention_count = mention_count + 1",
                "last_mentioned_date = date('now')",
                "last_seen_episode_id = ?",
            ]
            params: list = [eid]
            if row["first_seen_episode_id"] is None:
                sets.append("first_seen_episode_id = ?")
                params.append(eid)
                if speaker:
                    sets.append("first_seen_speaker = ?")
                    params.append(speaker)
            prev_last = row["last_seen_episode_id"]
            try:
                new_episode = prev_last is None or int(prev_last) != eid
            except (TypeError, ValueError):
                new_episode = True
            if new_episode:
                sets.append("source_diversity = source_diversity + 1")
            if speaker:
                sets.append("last_seen_speaker = ?")
                params.append(speaker)
            params.append(row["id"])
            conn.execute(
                f"UPDATE suggested_terms SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            self.sync_overton_from_suggested(conn, term_clean)
            return True

        if ot_row:
            last_d = conn.execute(
                "SELECT date(episode_date) AS d FROM podcast_episodes WHERE id = ?",
                (eid,),
            ).fetchone()
            last_md = str(last_d["d"])[:10] if last_d and last_d["d"] else None
            conn.execute(
                """
                UPDATE overton_terms
                SET mention_count = mention_count + 1,
                    last_mentioned_date = COALESCE(?, date('now')),
                    last_mentioned_episode_id = ?,
                    last_mentioned_speaker = COALESCE(?, last_mentioned_speaker),
                    first_detected_episode_id = COALESCE(first_detected_episode_id, ?),
                    first_detected_speaker = COALESCE(first_detected_speaker, ?)
                WHERE id = ?
                """,
                (last_md, eid, speaker, eid, speaker, ot_row["id"]),
            )
            return True

        return False

    def sync_all_overton_from_suggested(self) -> int:
        """Backfill overton_terms counts/dates from suggested_terms for matching terms."""
        n = 0
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT term FROM suggested_terms
                WHERE status IN ('approved', 'pending')
                """
            ).fetchall()
            for row in rows:
                if self.sync_overton_from_suggested(conn, row["term"]):
                    n += 1
        return n

    def sync_overton_from_suggested(self, conn, term_clean: str) -> bool:
        """Keep overton_terms counts and first/last attribution in sync with suggested_terms."""
        term_clean = (term_clean or "").strip()
        if not term_clean:
            return False
        suggested = conn.execute(
            """
            SELECT term, mention_count, definition, investment_implications,
                   first_seen_episode_id, last_seen_episode_id,
                   first_seen_speaker, last_seen_speaker, submitted_date
            FROM suggested_terms
            WHERE LOWER(TRIM(term)) = LOWER(?)
            """,
            (term_clean,),
        ).fetchone()
        if not suggested:
            return False
        existing = conn.execute(
            "SELECT id FROM overton_terms WHERE LOWER(TRIM(term)) = LOWER(?)",
            (term_clean,),
        ).fetchone()
        if not existing:
            return False

        def _episode_date(eid) -> Optional[str]:
            if eid is None:
                return None
            r = conn.execute(
                "SELECT date(episode_date) AS d FROM podcast_episodes WHERE id = ?",
                (int(eid),),
            ).fetchone()
            if not r or not r["d"]:
                return None
            return str(r["d"])[:10]

        feid = suggested["first_seen_episode_id"]
        leid = suggested["last_seen_episode_id"] or feid
        fspeaker = (suggested["first_seen_speaker"] or "").strip() or None
        lspeaker = (suggested["last_seen_speaker"] or fspeaker or "").strip() or None
        first_d = _episode_date(feid)
        if not first_d:
            sub = suggested["submitted_date"]
            if sub and len(str(sub)) >= 10:
                first_d = str(sub)[:10]
            else:
                first_d = date.today().isoformat()
        last_d = _episode_date(leid) or first_d
        mention_count = int(suggested["mention_count"] or 1)
        description = suggested["definition"] or f"Curated concept: {suggested['term']}"
        investment_implications = suggested["investment_implications"]

        conn.execute(
            """
            UPDATE overton_terms
            SET description = COALESCE(?, description),
                investment_implications = COALESCE(?, investment_implications),
                first_detected_date = COALESCE(?, first_detected_date),
                last_mentioned_date = ?,
                mention_count = MAX(mention_count, ?),
                first_detected_episode_id = COALESCE(first_detected_episode_id, ?),
                first_detected_speaker = COALESCE(first_detected_speaker, ?),
                last_mentioned_episode_id = ?,
                last_mentioned_speaker = COALESCE(?, last_mentioned_speaker)
            WHERE LOWER(TRIM(term)) = LOWER(?)
            """,
            (
                description,
                investment_implications,
                first_d,
                last_d,
                mention_count,
                feid,
                fspeaker,
                leid or feid,
                lspeaker,
                term_clean,
            ),
        )
        return True

    # === Podcast Guests (Interviewees) ===

    def get_podcast_guests_for_site(self, limit: int = 20) -> List[Dict]:
        """Get podcast guests for website 'Voices' / interviewees section."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, name, slug, bio, known_for, last_main_idea,
                       last_episode_title, last_podcast_name, last_episode_date, appearance_count
                FROM podcast_guests
                WHERE last_episode_id IS NOT NULL
                ORDER BY last_episode_date DESC, appearance_count DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def upsert_podcast_guest(self, name: str, last_episode_id: int, last_episode_title: str,
                             last_podcast_name: str, last_episode_date, last_main_idea: str,
                             bio: str = None, known_for: str = None) -> int:
        """Insert or update a podcast guest. Returns guest id."""
        import re
        slug = re.sub(r'[^\w\s-]', '', name).strip().lower().replace(' ', '-')[:80] or 'guest'
        slug = slug or f"guest-{last_episode_id}"
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT id, appearance_count, last_episode_date FROM podcast_guests WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))",
                (name,)
            ).fetchone()
            if existing:
                count = (existing['appearance_count'] or 1) + 1
                cur_date = existing['last_episode_date']
                # Only overwrite last_episode_* if this episode is same or more recent
                if cur_date is None or (last_episode_date and str(last_episode_date) >= str(cur_date)):
                    conn.execute("""
                        UPDATE podcast_guests SET
                            last_episode_id = ?, last_episode_title = ?, last_podcast_name = ?,
                            last_episode_date = ?, last_main_idea = ?, appearance_count = ?,
                            updated_at = ?,
                            bio = COALESCE(?, bio), known_for = COALESCE(?, known_for)
                        WHERE id = ?
                    """, (last_episode_id, last_episode_title, last_podcast_name,
                          last_episode_date, last_main_idea, count, now, bio, known_for, existing['id']))
                else:
                    conn.execute("""
                        UPDATE podcast_guests SET appearance_count = ?, updated_at = ?,
                        bio = COALESCE(?, bio), known_for = COALESCE(?, known_for)
                        WHERE id = ?
                    """, (count, now, bio, known_for, existing['id']))
                return existing['id']
            cursor = conn.execute("""
                INSERT INTO podcast_guests
                (name, slug, bio, known_for, last_main_idea, last_episode_id, last_episode_title,
                 last_podcast_name, last_episode_date, appearance_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (name, slug, bio, known_for, last_main_idea, last_episode_id, last_episode_title,
                  last_podcast_name, last_episode_date, now, now))
            return cursor.lastrowid

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