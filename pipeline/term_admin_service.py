#!/usr/bin/env python3
"""Local term admin — list, suggest, approve, reject, edit (Overton + definitions + pending)."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from approve_promoted_term import approve_promoted_term
from auto_curate_terms import _ensure_overton_term
from db_manager import get_db
from reject_promoted_term import reject_promoted_term


def _row_dict(row) -> Dict[str, Any]:
    return dict(row) if row else {}


def _episode_brief(conn, eid) -> Dict[str, Optional[str]]:
    if not eid:
        return {"podcast": None, "episode_title": None, "episode_date": None}
    r = conn.execute(
        """
        SELECT podcast_name, episode_title, date(episode_date) AS episode_date
        FROM podcast_episodes WHERE id = ?
        """,
        (int(eid),),
    ).fetchone()
    if not r:
        return {"podcast": None, "episode_title": None, "episode_date": None}
    d = r["episode_date"]
    return {
        "podcast": r["podcast_name"],
        "episode_title": r["episode_title"],
        "episode_date": str(d)[:10] if d else None,
    }


def _priority_score(row: Dict[str, Any]) -> int:
    try:
        m = int(row.get("mention_count") or 0)
        s = int(row.get("source_diversity") or 0)
        r = int(row.get("relevance_score") or 0)
    except (TypeError, ValueError):
        m, s, r = 0, 0, 0
    return m * 10 + s * 20 + r


def list_review_queue() -> Dict[str, Any]:
    """Return terms that still need an approve/reject decision for the website."""
    db = get_db()
    with db._get_connection() as conn:
        items: List[Dict[str, Any]] = []

        for row in conn.execute(
            """
            SELECT * FROM suggested_terms
            WHERE status = 'pending'
            ORDER BY mention_count DESC, relevance_score DESC, submitted_date DESC
            """
        ):
            item = _row_dict(row)
            item["kind"] = "suggested"
            item["description"] = item.get("definition")
            item["priority_score"] = _priority_score(item)
            item["first_seen"] = _episode_brief(conn, item.get("first_seen_episode_id"))
            item["last_seen"] = _episode_brief(conn, item.get("last_seen_episode_id"))
            items.append(item)

        for row in conn.execute(
            """
            SELECT o.*, s.review_notes, s.source_diversity, s.relevance_score
            FROM overton_terms AS o
            JOIN suggested_terms AS s
              ON LOWER(TRIM(s.term)) = LOWER(TRIM(o.term))
            WHERE o.status = 'active'
              AND COALESCE(o.display_on_main, 0) = 0
              AND s.status = 'approved'
              AND s.review_notes LIKE '%awaiting YES%'
            ORDER BY o.mention_count DESC, o.last_mentioned_date DESC, o.term ASC
            """
        ):
            item = _row_dict(row)
            item["kind"] = "promoted"
            item["priority_score"] = _priority_score(item)
            item["first_seen"] = _episode_brief(conn, item.get("first_detected_episode_id"))
            item["last_seen"] = _episode_brief(conn, item.get("last_mentioned_episode_id"))
            items.append(item)

    items.sort(
        key=lambda item: (
            int(item.get("priority_score") or 0),
            int(item.get("mention_count") or 0),
        ),
        reverse=True,
    )
    return {"items": items, "count": len(items)}


def list_all_terms() -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        pending: List[Dict[str, Any]] = []
        for row in conn.execute(
            """
            SELECT * FROM suggested_terms
            WHERE status = 'pending'
            ORDER BY mention_count DESC, relevance_score DESC, submitted_date DESC
            """
        ):
            item = _row_dict(row)
            item["priority_score"] = _priority_score(item)
            item["first_seen"] = _episode_brief(conn, item.get("first_seen_episode_id"))
            item["last_seen"] = _episode_brief(conn, item.get("last_seen_episode_id"))
            pending.append(item)

        overton: List[Dict[str, Any]] = []
        for row in conn.execute(
            """
            SELECT * FROM overton_terms
            WHERE status = 'active'
            ORDER BY display_on_main DESC, last_mentioned_date DESC, term ASC
            """
        ):
            item = _row_dict(row)
            item["first_seen"] = _episode_brief(conn, item.get("first_detected_episode_id"))
            item["last_seen"] = _episode_brief(conn, item.get("last_mentioned_episode_id"))
            overton.append(item)

        definitions: List[Dict[str, Any]] = []
        for row in conn.execute(
            """
            SELECT * FROM definitions
            ORDER BY display_on_main DESC, added_date DESC, term ASC
            """
        ):
            definitions.append(_row_dict(row))

        stats = {
            "pending": len(pending),
            "overton_visible": sum(1 for t in overton if t.get("display_on_main")),
            "overton_hidden": sum(1 for t in overton if not t.get("display_on_main")),
            "definitions": len(definitions),
        }

    return {
        "pending": pending,
        "overton": overton,
        "definitions": definitions,
        "stats": stats,
    }


def suggest_term(
    term: str,
    definition: Optional[str] = None,
    investment_implications: Optional[str] = None,
    *,
    source_contact: str = "term_admin",
) -> Dict[str, Any]:
    term_clean = (term or "").strip()
    if len(term_clean) < 3:
        raise ValueError("Term must be at least 3 characters")

    db = get_db()
    with db._get_connection() as conn:
        existing = conn.execute(
            "SELECT id, status FROM suggested_terms WHERE LOWER(TRIM(term)) = LOWER(?)",
            (term_clean,),
        ).fetchone()
        if existing:
            if existing["status"] == "pending":
                raise ValueError(f"Already pending: {term_clean}")
            raise ValueError(f"Term already exists ({existing['status']}): {term_clean}")

        conn.execute(
            """
            INSERT INTO suggested_terms
            (term, definition, investment_implications, source_type, source_contact,
             mention_count, source_diversity, relevance_score, last_mentioned_date, status)
            VALUES (?, ?, ?, 'user_submission', ?, 1, 1, 60, date('now'), 'pending')
            """,
            (
                term_clean,
                (definition or "").strip() or None,
                (investment_implications or "").strip() or None,
                source_contact,
            ),
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"id": new_id, "term": term_clean, "status": "pending"}


def _fetch_suggested(conn, term_id: int) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM suggested_terms WHERE id = ?", (term_id,)).fetchone()
    if not row:
        raise ValueError(f"Suggested term id {term_id} not found")
    return _row_dict(row)


def promote_suggested(
    term_id: int,
    *,
    show_on_main: bool = True,
    reviewed_by: str = "term_admin",
    notes: str = "Approved via term admin UI",
) -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        term_data = _fetch_suggested(conn, term_id)
        term = term_data["term"]

        def_row = conn.execute(
            "SELECT id FROM definitions WHERE LOWER(TRIM(term)) = LOWER(?)",
            (term,),
        ).fetchone()
        if not def_row:
            conn.execute(
                """
                INSERT INTO definitions
                (term, definition, investment_implications, added_date, vote_count, display_on_main, display_order)
                VALUES (?, ?, ?, date('now'), ?, ?, 0)
                """,
                (
                    term,
                    term_data.get("definition") or f"Definition for {term}",
                    term_data.get("investment_implications") or "Curated via term admin",
                    max(int(term_data.get("vote_count") or 0), 1),
                    1 if show_on_main else 0,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE definitions
                SET definition = COALESCE(?, definition),
                    investment_implications = COALESCE(?, investment_implications),
                    display_on_main = ?
                WHERE id = ?
                """,
                (
                    term_data.get("definition"),
                    term_data.get("investment_implications"),
                    1 if show_on_main else 0,
                    def_row["id"],
                ),
            )

        _ensure_overton_term(conn, term_data)
        if show_on_main:
            approve_promoted_term(conn, term, notes=notes)

        conn.execute(
            """
            UPDATE suggested_terms
            SET status = 'approved',
                reviewed_by = ?,
                reviewed_at = CURRENT_TIMESTAMP,
                review_notes = ?
            WHERE id = ?
            """,
            (reviewed_by, notes, term_id),
        )
    return {"term": term, "show_on_main": show_on_main}


def reject_suggested(term_id: int, reason: str = "Rejected via term admin UI") -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        term_data = _fetch_suggested(conn, term_id)
        conn.execute(
            """
            UPDATE suggested_terms
            SET status = 'rejected',
                reviewed_by = 'term_admin',
                reviewed_at = CURRENT_TIMESTAMP,
                review_notes = ?
            WHERE id = ?
            """,
            (reason, term_id),
        )
    return {"term": term_data["term"], "status": "rejected"}


def show_overton_on_site(term: str) -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        ok = approve_promoted_term(conn, term, notes="Shown on main page via term admin UI")
        if not ok:
            raise ValueError(f"No Overton/definition row for: {term}")
    return {"term": term, "display_on_main": 1}


def hide_overton_from_site(term: str) -> Dict[str, Any]:
    term = (term or "").strip()
    db = get_db()
    with db._get_connection() as conn:
        touched = False
        for table in ("overton_terms", "definitions"):
            cur = conn.execute(
                f"UPDATE {table} SET display_on_main = 0 WHERE LOWER(TRIM(term)) = LOWER(?)",
                (term,),
            )
            if cur.rowcount:
                touched = True
        if not touched:
            raise ValueError(f"No row for: {term}")
    return {"term": term, "display_on_main": 0}


def reject_overton(term: str, reason: str = "Rejected via term admin UI") -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        ok = reject_promoted_term(conn, term, notes=reason)
        if not ok:
            raise ValueError(f"No promoted term to remove: {term}")
    return {"term": term, "status": "rejected"}


def update_suggested(
    term_id: int,
    *,
    definition: Optional[str] = None,
    investment_implications: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        _fetch_suggested(conn, term_id)
        conn.execute(
            """
            UPDATE suggested_terms
            SET definition = COALESCE(?, definition),
                investment_implications = COALESCE(?, investment_implications)
            WHERE id = ?
            """,
            (
                definition.strip() if definition else None,
                investment_implications.strip() if investment_implications else None,
                term_id,
            ),
        )
        row = _fetch_suggested(conn, term_id)
    return row


def update_overton(
    overton_id: int,
    *,
    description: Optional[str] = None,
    investment_implications: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        row = conn.execute("SELECT * FROM overton_terms WHERE id = ?", (overton_id,)).fetchone()
        if not row:
            raise ValueError(f"Overton id {overton_id} not found")
        term = row["term"]
        conn.execute(
            """
            UPDATE overton_terms
            SET description = COALESCE(?, description),
                investment_implications = COALESCE(?, investment_implications)
            WHERE id = ?
            """,
            (
                description.strip() if description else None,
                investment_implications.strip() if investment_implications else None,
                overton_id,
            ),
        )
        conn.execute(
            """
            UPDATE definitions
            SET definition = COALESCE(?, definition),
                investment_implications = COALESCE(?, investment_implications)
            WHERE LOWER(TRIM(term)) = LOWER(?)
            """,
            (
                description.strip() if description else None,
                investment_implications.strip() if investment_implications else None,
                term,
            ),
        )
        updated = conn.execute("SELECT * FROM overton_terms WHERE id = ?", (overton_id,)).fetchone()
    return _row_dict(updated)


def update_definition(
    definition_id: int,
    *,
    definition: Optional[str] = None,
    investment_implications: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_db()
    with db._get_connection() as conn:
        row = conn.execute("SELECT * FROM definitions WHERE id = ?", (definition_id,)).fetchone()
        if not row:
            raise ValueError(f"Definition id {definition_id} not found")
        conn.execute(
            """
            UPDATE definitions
            SET definition = COALESCE(?, definition),
                investment_implications = COALESCE(?, investment_implications)
            WHERE id = ?
            """,
            (
                definition.strip() if definition else None,
                investment_implications.strip() if investment_implications else None,
                definition_id,
            ),
        )
        term = row["term"]
        conn.execute(
            """
            UPDATE overton_terms
            SET description = COALESCE(?, description),
                investment_implications = COALESCE(?, investment_implications)
            WHERE LOWER(TRIM(term)) = LOWER(?)
            """,
            (
                definition.strip() if definition else None,
                investment_implications.strip() if investment_implications else None,
                term,
            ),
        )
        updated = conn.execute("SELECT * FROM definitions WHERE id = ?", (definition_id,)).fetchone()
    return _row_dict(updated)
