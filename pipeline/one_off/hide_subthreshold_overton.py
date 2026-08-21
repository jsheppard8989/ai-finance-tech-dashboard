#!/usr/bin/env python3
"""One-off cleanup: reject Test Concept, hide sub-threshold Overton terms."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_manager import get_db
from term_admin_service import reject_suggested


def hide_below_main_page_threshold(db) -> tuple[int, list[str]]:
    """Set display_on_main=0 for all visible Overton terms not in top-N main export."""
    content = db.get_main_page_content()
    keep = {t["term"] for t in content.get("overton", [])}
    hidden: list[str] = []
    with db._get_connection() as conn:
        rows = conn.execute(
            """
            SELECT term FROM overton_terms
            WHERE status = 'active' AND display_on_main = 1
            """
        ).fetchall()
        for row in rows:
            term = row["term"]
            if term in keep:
                continue
            conn.execute(
                "UPDATE overton_terms SET display_on_main = 0 WHERE term = ?",
                (term,),
            )
            conn.execute(
                "UPDATE definitions SET display_on_main = 0 WHERE LOWER(TRIM(term)) = LOWER(TRIM(?))",
                (term,),
            )
            hidden.append(term)
    return len(hidden), hidden


def main() -> None:
    db = get_db()

    # Reject Test Concept
    with db._get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM suggested_terms WHERE term = 'Test Concept' AND status = 'pending'"
        ).fetchone()
    if row:
        reject_suggested(int(row["id"]), "Rejected: test artifact")
        print("✓ Rejected Test Concept")
    else:
        print("ℹ Test Concept not pending (already handled)")

    n, terms = hide_below_main_page_threshold(db)
    print(f"✓ Hid {n} sub-threshold Overton terms (kept top {13} on main page)")
    if terms[:5]:
        print(f"  e.g. {', '.join(terms[:5])}" + (f" … +{n-5} more" if n > 5 else ""))


if __name__ == "__main__":
    main()
