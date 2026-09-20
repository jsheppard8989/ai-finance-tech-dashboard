#!/usr/bin/env python3
"""Tests for stale_episodes detection in export_data pipeline_state."""

import json
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest


def _init_test_db(db_path: Path) -> None:
    """Initialize a test database with the required tables."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE podcast_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            podcast_name TEXT NOT NULL,
            episode_title TEXT NOT NULL,
            episode_date DATE,
            audio_url TEXT,
            transcript_path TEXT,
            is_processed BOOLEAN DEFAULT 0,
            added_to_site BOOLEAN DEFAULT 0,
            rss_guid TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE latest_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source_type TEXT,
            source_name TEXT NOT NULL,
            source_date DATE,
            podcast_episode_id INTEGER,
            display_on_main BOOLEAN DEFAULT 1,
            archived_date DATE,
            FOREIGN KEY (podcast_episode_id) REFERENCES podcast_episodes(id)
        );

        CREATE TABLE deep_dive_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_id INTEGER NOT NULL,
            podcast_episode_id INTEGER,
            overview TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (insight_id) REFERENCES latest_insights(id),
            FOREIGN KEY (podcast_episode_id) REFERENCES podcast_episodes(id)
        );
        """
    )
    conn.commit()
    conn.close()


def _insert_episode(
    conn,
    podcast_name: str,
    episode_title: str,
    episode_date: date,
    *,
    audio_url: str = "http://example.com/audio.mp3",
    transcript_path: str = "/path/to/transcript.txt",
    is_processed: bool = True,
    added_to_site: bool = False,
    rss_guid: str = None,
) -> int:
    """Insert a podcast episode and return its ID."""
    cur = conn.execute(
        """
        INSERT INTO podcast_episodes
        (podcast_name, episode_title, episode_date, audio_url, transcript_path,
         is_processed, added_to_site, rss_guid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            podcast_name,
            episode_title,
            episode_date.isoformat(),
            audio_url,
            transcript_path,
            1 if is_processed else 0,
            1 if added_to_site else 0,
            rss_guid,
        ),
    )
    conn.commit()
    return cur.lastrowid


def _insert_insight(conn, episode_id: int, title: str, source_date: str = None) -> int:
    """Insert a latest_insights row linked to an episode."""
    cur = conn.execute(
        """
        INSERT INTO latest_insights (title, source_type, source_name, source_date, podcast_episode_id)
        VALUES (?, 'podcast', 'Test Podcast', ?, ?)
        """,
        (title, source_date, episode_id),
    )
    conn.commit()
    return cur.lastrowid


def _insert_deepdive(conn, insight_id: int, episode_id: int) -> int:
    """Insert a deep_dive_content row linked to an insight."""
    cur = conn.execute(
        """
        INSERT INTO deep_dive_content (insight_id, podcast_episode_id, overview)
        VALUES (?, ?, 'Test overview')
        """,
        (insight_id, episode_id),
    )
    conn.commit()
    return cur.lastrowid


class TestStaleEpisodesDetection:
    """Test that stale_episodes correctly identifies incomplete recent episodes."""

    def test_episode_with_insight_and_deepdive_but_not_on_site_is_NOT_stale(self, tmp_path):
        """Episode with insight+deepdive but added_to_site=0 is off-main overflow, NOT stale.
        
        These episodes lost the main-10 race (sync_main_insights_with_deepdives keeps
        a rolling top-8 + pins). They are complete from a pipeline perspective — just
        not displayed on the main page. They should NOT appear in stale_episodes.
        """
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Episode from 5 days ago, fully processed but not on site (off-main overflow)
        ep_date = date.today() - timedelta(days=5)
        ep_id = _insert_episode(
            conn,
            "Dwarkesh Podcast",
            "Ajeya Cotra - AI Timelines",
            ep_date,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-450",
        )
        insight_id = _insert_insight(conn, ep_id, "Ajeya Cotra on AI Timelines")
        _insert_deepdive(conn, insight_id, ep_id)

        # Run the stale detection query — should NOT include off-main overflow
        stale_threshold_days = 2
        stale_lookback_days = 14
        cur = conn.execute(
            """
            SELECT 
                pe.id,
                pe.rss_guid,
                pe.podcast_name,
                pe.episode_title,
                pe.episode_date,
                pe.is_processed,
                pe.added_to_site,
                (SELECT COUNT(*) FROM latest_insights li WHERE li.podcast_episode_id = pe.id) AS insight_count,
                (SELECT COUNT(*) FROM deep_dive_content ddc 
                 JOIN latest_insights li2 ON ddc.insight_id = li2.id 
                 WHERE li2.podcast_episode_id = pe.id) AS deepdive_count
            FROM podcast_episodes pe
            WHERE date(COALESCE(pe.episode_date, date(pe.created_at))) >= date('now', ?)
              AND julianday('now') - julianday(COALESCE(pe.episode_date, date(pe.created_at))) >= ?
              AND (
                  NOT EXISTS (SELECT 1 FROM latest_insights li WHERE li.podcast_episode_id = pe.id)
                  OR NOT EXISTS (
                      SELECT 1 FROM deep_dive_content ddc
                      JOIN latest_insights li2 ON ddc.insight_id = li2.id
                      WHERE li2.podcast_episode_id = pe.id
                  )
              )
            """,
            (f"-{stale_lookback_days} days", stale_threshold_days),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        assert len(rows) == 0, f"Off-main overflow (insight+DD, added_to_site=0) should NOT be stale, got {len(rows)}"

    def test_episode_with_insight_but_no_deepdive_is_stale(self, tmp_path):
        """Episode has insight but no deep dive - should be stale (true pipeline debt)."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        ep_date = date.today() - timedelta(days=4)
        ep_id = _insert_episode(
            conn,
            "Macro Voices",
            "Episode 548 - Market Analysis",
            ep_date,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-453",
        )
        _insert_insight(conn, ep_id, "Macro Voices Market Analysis")
        # No deep dive — this is true pipeline debt

        stale_threshold_days = 2
        stale_lookback_days = 14
        cur = conn.execute(
            """
            SELECT pe.id, pe.episode_title,
                (SELECT COUNT(*) FROM latest_insights li WHERE li.podcast_episode_id = pe.id) AS insight_count,
                (SELECT COUNT(*) FROM deep_dive_content ddc 
                 JOIN latest_insights li2 ON ddc.insight_id = li2.id 
                 WHERE li2.podcast_episode_id = pe.id) AS deepdive_count
            FROM podcast_episodes pe
            WHERE date(COALESCE(pe.episode_date, date(pe.created_at))) >= date('now', ?)
              AND julianday('now') - julianday(COALESCE(pe.episode_date, date(pe.created_at))) >= ?
              AND (
                  NOT EXISTS (SELECT 1 FROM latest_insights li WHERE li.podcast_episode_id = pe.id)
                  OR NOT EXISTS (
                      SELECT 1 FROM deep_dive_content ddc
                      JOIN latest_insights li2 ON ddc.insight_id = li2.id
                      WHERE li2.podcast_episode_id = pe.id
                  )
              )
            """,
            (f"-{stale_lookback_days} days", stale_threshold_days),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        assert len(rows) == 1, "Episode with insight but no deep dive should be stale"
        assert rows[0]["insight_count"] == 1
        assert rows[0]["deepdive_count"] == 0

    def test_fully_published_episode_is_not_stale(self, tmp_path):
        """Episode with insight, deepdive, and added_to_site=1 should NOT be stale."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        ep_date = date.today() - timedelta(days=3)
        ep_id = _insert_episode(
            conn,
            "Fully Published Podcast",
            "Complete Episode",
            ep_date,
            is_processed=True,
            added_to_site=True,  # On site!
            rss_guid="guid-complete",
        )
        insight_id = _insert_insight(conn, ep_id, "Complete Episode Insight")
        _insert_deepdive(conn, insight_id, ep_id)

        stale_threshold_days = 2
        stale_lookback_days = 14
        cur = conn.execute(
            """
            SELECT pe.id
            FROM podcast_episodes pe
            WHERE date(COALESCE(pe.episode_date, date(pe.created_at))) >= date('now', ?)
              AND julianday('now') - julianday(COALESCE(pe.episode_date, date(pe.created_at))) >= ?
              AND (
                  NOT EXISTS (SELECT 1 FROM latest_insights li WHERE li.podcast_episode_id = pe.id)
                  OR NOT EXISTS (
                      SELECT 1 FROM deep_dive_content ddc
                      JOIN latest_insights li2 ON ddc.insight_id = li2.id
                      WHERE li2.podcast_episode_id = pe.id
                  )
              )
            """,
            (f"-{stale_lookback_days} days", stale_threshold_days),
        )
        rows = cur.fetchall()
        conn.close()

        assert len(rows) == 0, "Fully published episode should not appear as stale"

    def test_recent_episode_under_threshold_is_not_stale(self, tmp_path):
        """Episode from yesterday (age < 2 days) should not be stale yet."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Episode from yesterday — no insight/DD yet, but too fresh to be stale
        ep_date = date.today() - timedelta(days=1)
        _insert_episode(
            conn,
            "Recent Podcast",
            "Fresh Episode",
            ep_date,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-fresh",
        )

        stale_threshold_days = 2
        stale_lookback_days = 14
        cur = conn.execute(
            """
            SELECT pe.id
            FROM podcast_episodes pe
            WHERE date(COALESCE(pe.episode_date, date(pe.created_at))) >= date('now', ?)
              AND julianday('now') - julianday(COALESCE(pe.episode_date, date(pe.created_at))) >= ?
              AND (
                  NOT EXISTS (SELECT 1 FROM latest_insights li WHERE li.podcast_episode_id = pe.id)
                  OR NOT EXISTS (
                      SELECT 1 FROM deep_dive_content ddc
                      JOIN latest_insights li2 ON ddc.insight_id = li2.id
                      WHERE li2.podcast_episode_id = pe.id
                  )
              )
            """,
            (f"-{stale_lookback_days} days", stale_threshold_days),
        )
        rows = cur.fetchall()
        conn.close()

        assert len(rows) == 0, "Episode under age threshold should not be stale"

    def test_old_episode_outside_lookback_is_not_stale(self, tmp_path):
        """Episode older than 14 days should not appear in stale list."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Episode from 20 days ago (outside 14-day lookback) — no insight/DD
        ep_date = date.today() - timedelta(days=20)
        _insert_episode(
            conn,
            "Old Podcast",
            "Ancient Episode",
            ep_date,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-old",
        )

        stale_threshold_days = 2
        stale_lookback_days = 14
        cur = conn.execute(
            """
            SELECT pe.id
            FROM podcast_episodes pe
            WHERE date(COALESCE(pe.episode_date, date(pe.created_at))) >= date('now', ?)
              AND julianday('now') - julianday(COALESCE(pe.episode_date, date(pe.created_at))) >= ?
              AND (
                  NOT EXISTS (SELECT 1 FROM latest_insights li WHERE li.podcast_episode_id = pe.id)
                  OR NOT EXISTS (
                      SELECT 1 FROM deep_dive_content ddc
                      JOIN latest_insights li2 ON ddc.insight_id = li2.id
                      WHERE li2.podcast_episode_id = pe.id
                  )
              )
            """,
            (f"-{stale_lookback_days} days", stale_threshold_days),
        )
        rows = cur.fetchall()
        conn.close()

        assert len(rows) == 0, "Episode outside lookback window should not appear"

    def test_episode_without_insight_is_stale(self, tmp_path):
        """Episode that is analyzed but has no insight row should be stale."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        ep_date = date.today() - timedelta(days=5)
        _insert_episode(
            conn,
            "No Insight Podcast",
            "Missing Insight Episode",
            ep_date,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-no-insight",
        )
        # No insight row created

        stale_threshold_days = 2
        stale_lookback_days = 14
        cur = conn.execute(
            """
            SELECT pe.id, pe.episode_title,
                (SELECT COUNT(*) FROM latest_insights li WHERE li.podcast_episode_id = pe.id) AS insight_count
            FROM podcast_episodes pe
            WHERE date(COALESCE(pe.episode_date, date(pe.created_at))) >= date('now', ?)
              AND julianday('now') - julianday(COALESCE(pe.episode_date, date(pe.created_at))) >= ?
              AND NOT EXISTS (SELECT 1 FROM latest_insights li WHERE li.podcast_episode_id = pe.id)
            """,
            (f"-{stale_lookback_days} days", stale_threshold_days),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        assert len(rows) == 1
        assert rows[0]["insight_count"] == 0


class TestSyncMainInsightsWithDeepDives:
    """Test sync_main_insights_with_deepdives correctly decouples added_to_site from display_on_main."""

    def test_off_main_episode_with_deepdive_gets_added_to_site(self, tmp_path):
        """Episode with insight+deepdive but off main-10 should have added_to_site=1.
        
        This is the core fix: added_to_site should be 1 when episode has a non-archived
        insight AND a deep_dive_content row, regardless of whether it's on the main page.
        """
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Create 12 episodes to exceed max_on_main (10)
        ep_ids = []
        insight_ids = []
        for i in range(12):
            ep_date = date.today() - timedelta(days=i)
            ep_id = _insert_episode(
                conn,
                f"Podcast {i}",
                f"Episode {i}",
                ep_date,
                is_processed=True,
                added_to_site=False,
                rss_guid=f"guid-{i}",
            )
            ep_ids.append(ep_id)
            # Insert insight with source_date so we can control ordering
            insight_id = _insert_insight(conn, ep_id, f"Insight {i}", ep_date.isoformat())
            insight_ids.append(insight_id)
            # Insert deep dive for each
            _insert_deepdive(conn, insight_id, ep_id)

        # Run the sync SQL logic directly (mimicking sync_main_insights_with_deepdives)
        max_on_main = 10

        # Clear display_on_main
        conn.execute("UPDATE latest_insights SET display_on_main = 0 WHERE archived_date IS NULL")

        # Set display_on_main for top 10 by source_date DESC
        conn.execute(
            """
            UPDATE latest_insights SET display_on_main = 1
            WHERE id IN (
                SELECT li.id FROM latest_insights li
                INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                WHERE li.archived_date IS NULL
                ORDER BY li.source_date DESC, li.id DESC
                LIMIT ?
            )
            """,
            (max_on_main,),
        )

        # Set added_to_site=1 for ANY episode with insight+deepdive (not just main-10)
        conn.execute(
            """
            UPDATE podcast_episodes
            SET added_to_site = CASE
                WHEN id IN (
                    SELECT li.podcast_episode_id
                    FROM latest_insights li
                    INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                    WHERE li.archived_date IS NULL
                      AND li.podcast_episode_id IS NOT NULL
                ) THEN 1 ELSE 0 END
            WHERE id IN (
                SELECT DISTINCT podcast_episode_id FROM latest_insights
                WHERE podcast_episode_id IS NOT NULL
            )
            """
        )
        conn.commit()

        # Verify: all 12 should have added_to_site=1 (they all have insight+deepdive)
        cur = conn.execute("SELECT id, added_to_site FROM podcast_episodes ORDER BY id")
        rows = [dict(r) for r in cur.fetchall()]
        assert len(rows) == 12
        for row in rows:
            assert row["added_to_site"] == 1, f"Episode {row['id']} should have added_to_site=1"

        # Verify: only 10 should have display_on_main=1
        cur = conn.execute("SELECT COUNT(*) as c FROM latest_insights WHERE display_on_main = 1")
        main_count = cur.fetchone()["c"]
        assert main_count == 10, f"Main page should have exactly 10 insights, got {main_count}"

        # Verify: 2 should be off-main but still site-published
        cur = conn.execute(
            """
            SELECT COUNT(*) as c FROM podcast_episodes pe
            INNER JOIN latest_insights li ON li.podcast_episode_id = pe.id
            WHERE pe.added_to_site = 1 AND li.display_on_main = 0
            """
        )
        off_main_published = cur.fetchone()["c"]
        assert off_main_published == 2, f"Should have 2 off-main but site-published, got {off_main_published}"

        conn.close()

    def test_episode_with_insight_but_no_deepdive_not_added_to_site(self, tmp_path):
        """Episode with insight but NO deep dive should have added_to_site=0."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Episode with insight but no deep dive
        ep_date = date.today() - timedelta(days=1)
        ep_id = _insert_episode(
            conn,
            "No DeepDive Podcast",
            "Missing DeepDive Episode",
            ep_date,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-no-dd",
        )
        _insert_insight(conn, ep_id, "Insight Without DeepDive", ep_date.isoformat())
        # No deep dive inserted!

        # Episode with insight AND deep dive
        ep_date2 = date.today() - timedelta(days=2)
        ep_id2 = _insert_episode(
            conn,
            "With DeepDive Podcast",
            "Has DeepDive Episode",
            ep_date2,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-has-dd",
        )
        insight_id2 = _insert_insight(conn, ep_id2, "Insight With DeepDive", ep_date2.isoformat())
        _insert_deepdive(conn, insight_id2, ep_id2)

        # Run the sync SQL logic
        conn.execute("UPDATE latest_insights SET display_on_main = 0 WHERE archived_date IS NULL")
        conn.execute(
            """
            UPDATE latest_insights SET display_on_main = 1
            WHERE id IN (
                SELECT li.id FROM latest_insights li
                INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                WHERE li.archived_date IS NULL
                ORDER BY li.source_date DESC, li.id DESC
                LIMIT 10
            )
            """
        )
        conn.execute(
            """
            UPDATE podcast_episodes
            SET added_to_site = CASE
                WHEN id IN (
                    SELECT li.podcast_episode_id
                    FROM latest_insights li
                    INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                    WHERE li.archived_date IS NULL
                      AND li.podcast_episode_id IS NOT NULL
                ) THEN 1 ELSE 0 END
            WHERE id IN (
                SELECT DISTINCT podcast_episode_id FROM latest_insights
                WHERE podcast_episode_id IS NOT NULL
            )
            """
        )
        conn.commit()

        # Verify: episode without deep dive should have added_to_site=0
        cur = conn.execute("SELECT added_to_site FROM podcast_episodes WHERE id = ?", (ep_id,))
        assert cur.fetchone()["added_to_site"] == 0, "Episode without deep dive should NOT be added_to_site"

        # Verify: episode with deep dive should have added_to_site=1
        cur = conn.execute("SELECT added_to_site FROM podcast_episodes WHERE id = ?", (ep_id2,))
        assert cur.fetchone()["added_to_site"] == 1, "Episode with deep dive should be added_to_site"

        conn.close()

    def test_archived_insight_episode_not_added_to_site(self, tmp_path):
        """Episode whose insight is archived should have added_to_site=0."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Episode with archived insight + deep dive
        ep_date = date.today() - timedelta(days=5)
        ep_id = _insert_episode(
            conn,
            "Archived Podcast",
            "Archived Episode",
            ep_date,
            is_processed=True,
            added_to_site=False,
            rss_guid="guid-archived",
        )
        insight_id = _insert_insight(conn, ep_id, "Archived Insight", ep_date.isoformat())
        _insert_deepdive(conn, insight_id, ep_id)
        # Mark insight as archived
        conn.execute("UPDATE latest_insights SET archived_date = ? WHERE id = ?", (date.today().isoformat(), insight_id))
        conn.commit()

        # Run the sync SQL logic
        conn.execute("UPDATE latest_insights SET display_on_main = 0 WHERE archived_date IS NULL")
        conn.execute(
            """
            UPDATE latest_insights SET display_on_main = 1
            WHERE id IN (
                SELECT li.id FROM latest_insights li
                INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                WHERE li.archived_date IS NULL
                ORDER BY li.source_date DESC, li.id DESC
                LIMIT 10
            )
            """
        )
        conn.execute(
            """
            UPDATE podcast_episodes
            SET added_to_site = CASE
                WHEN id IN (
                    SELECT li.podcast_episode_id
                    FROM latest_insights li
                    INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                    WHERE li.archived_date IS NULL
                      AND li.podcast_episode_id IS NOT NULL
                ) THEN 1 ELSE 0 END
            WHERE id IN (
                SELECT DISTINCT podcast_episode_id FROM latest_insights
                WHERE podcast_episode_id IS NOT NULL
            )
            """
        )
        conn.commit()

        # Verify: archived insight's episode should have added_to_site=0
        cur = conn.execute("SELECT added_to_site FROM podcast_episodes WHERE id = ?", (ep_id,))
        assert cur.fetchone()["added_to_site"] == 0, "Episode with archived insight should NOT be added_to_site"

        conn.close()

    def test_main_page_capped_at_max_on_main(self, tmp_path):
        """Main page (display_on_main=1) should never exceed max_on_main (10)."""
        db_path = tmp_path / "test.db"
        _init_test_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Create 15 episodes with insights and deep dives
        for i in range(15):
            ep_date = date.today() - timedelta(days=i)
            ep_id = _insert_episode(
                conn,
                f"Podcast {i}",
                f"Episode {i}",
                ep_date,
                is_processed=True,
                added_to_site=False,
                rss_guid=f"guid-main-{i}",
            )
            insight_id = _insert_insight(conn, ep_id, f"Insight {i}", ep_date.isoformat())
            _insert_deepdive(conn, insight_id, ep_id)

        max_on_main = 10

        # Run the sync SQL logic
        conn.execute("UPDATE latest_insights SET display_on_main = 0 WHERE archived_date IS NULL")
        conn.execute(
            """
            UPDATE latest_insights SET display_on_main = 1
            WHERE id IN (
                SELECT li.id FROM latest_insights li
                INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                WHERE li.archived_date IS NULL
                ORDER BY li.source_date DESC, li.id DESC
                LIMIT ?
            )
            """,
            (max_on_main,),
        )
        conn.execute(
            """
            UPDATE podcast_episodes
            SET added_to_site = CASE
                WHEN id IN (
                    SELECT li.podcast_episode_id
                    FROM latest_insights li
                    INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
                    WHERE li.archived_date IS NULL
                      AND li.podcast_episode_id IS NOT NULL
                ) THEN 1 ELSE 0 END
            WHERE id IN (
                SELECT DISTINCT podcast_episode_id FROM latest_insights
                WHERE podcast_episode_id IS NOT NULL
            )
            """
        )
        conn.commit()

        # Verify: exactly 10 on main
        cur = conn.execute("SELECT COUNT(*) as c FROM latest_insights WHERE display_on_main = 1")
        main_count = cur.fetchone()["c"]
        assert main_count == 10, f"Main page should have exactly 10, got {main_count}"

        # Verify: all 15 site-published
        cur = conn.execute("SELECT COUNT(*) as c FROM podcast_episodes WHERE added_to_site = 1")
        published_count = cur.fetchone()["c"]
        assert published_count == 15, f"All 15 should be site-published, got {published_count}"

        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
