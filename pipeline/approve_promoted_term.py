#!/usr/bin/env python3
"""
Show an auto-promoted term on the main Overton list (display_on_main = 1).
Used when the user replies YES <token> to the promotion iMessage.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db  # type: ignore


def approve_promoted_term(
    conn: sqlite3.Connection,
    term: str,
    notes: str = "Approved: user confirmed Overton term for main page",
) -> bool:
    """Set display_on_main = 1 on matching overton_terms and definitions rows."""
    term = (term or "").strip()
    if not term:
        return False
    touched = False
    for table in ("overton_terms", "definitions"):
        cur = conn.execute(
            f"UPDATE {table} SET display_on_main = 1 WHERE LOWER(TRIM(term)) = LOWER(TRIM(?))",
            (term,),
        )
        if cur.rowcount:
            touched = True
    conn.execute(
        """
        UPDATE suggested_terms
        SET review_notes = COALESCE(review_notes || ' | ', '') || ?
        WHERE LOWER(TRIM(term)) = LOWER(TRIM(?)) AND status = 'approved'
        """,
        (notes, term),
    )
    return touched


def main() -> None:
    ap = argparse.ArgumentParser(description="Approve a promoted term for the main Overton list.")
    ap.add_argument("--term", help="Exact term string")
    args = ap.parse_args()
    if not args.term:
        ap.error("--term is required")
    db = get_db()
    with db._get_connection() as conn:
        ok = approve_promoted_term(conn, args.term)
        conn.commit()
    print(f"✓ Approved for main page: {args.term}" if ok else f"ℹ️ No matching rows for: {args.term}")


if __name__ == "__main__":
    main()
