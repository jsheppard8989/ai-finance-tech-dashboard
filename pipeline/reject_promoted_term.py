#!/usr/bin/env python3
"""
Remove an auto-promoted term from Definitions + Overton (and mark suggested_terms rejected).
Used by CLI and process_term_promotion_replies.py when the user replies NO <token>.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db  # type: ignore


def reject_promoted_term(
    conn: sqlite3.Connection,
    term: str,
    notes: str = "Rejected: user declined promoted Overton term",
) -> bool:
    """
    Delete from definitions and overton_terms; mark suggested_terms rejected.
    Returns True if any row was touched.
    """
    term = (term or "").strip()
    if not term:
        return False
    touched = False
    cur = conn.execute("DELETE FROM definitions WHERE term = ?", (term,))
    if cur.rowcount:
        touched = True
    cur = conn.execute("DELETE FROM overton_terms WHERE term = ?", (term,))
    if cur.rowcount:
        touched = True
    cur = conn.execute(
        """
        UPDATE suggested_terms
        SET status = 'rejected',
            reviewed_at = CURRENT_TIMESTAMP,
            review_notes = ?
        WHERE LOWER(TRIM(term)) = LOWER(TRIM(?)) AND status != 'rejected'
        """,
        (notes, term),
    )
    if cur.rowcount:
        touched = True
    return touched


def main() -> None:
    ap = argparse.ArgumentParser(description="Remove a promoted term from Overton + definitions.")
    ap.add_argument("--term", help="Exact term string")
    args = ap.parse_args()
    if not args.term:
        ap.error("--term is required")
    db = get_db()
    with db._get_connection() as conn:
        ok = reject_promoted_term(conn, args.term)
        conn.commit()
    print(f"✓ Rejected and removed: {args.term}" if ok else f"ℹ️ No matching rows for: {args.term}")


if __name__ == "__main__":
    main()
