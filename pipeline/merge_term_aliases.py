#!/usr/bin/env python3
"""
Merge duplicate suggested/overton/definition rows using term_aliases.json.

Run after seeding term_aliases. Consolidates mention counts into the canonical row
and marks duplicate suggested_terms as status='duplicate'.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db_manager import get_db
from term_alias_util import load_alias_merges_from_json


def _pick_survivor(rows, canonical: str):
    """Prefer exact canonical name match, else highest mention_count."""
    exact = [r for r in rows if (r["term"] or "").strip().lower() == canonical.lower()]
    pool = exact or rows
    return max(pool, key=lambda r: (int(r["mention_count"] or 0), int(r["id"])))


def merge_group(conn, canonical: str, aliases: list[str], *, dry_run: bool) -> dict:
    names = [canonical] + list(aliases or [])
    lower_names = [n.lower() for n in names]

    suggested = conn.execute(
        """
        SELECT id, term, status, mention_count, source_diversity,
               definition, investment_implications, speaker_quote,
               first_seen_episode_id, last_seen_episode_id,
               first_seen_speaker, last_seen_speaker
        FROM suggested_terms
        """
    ).fetchall()
    suggested = [r for r in suggested if (r["term"] or "").strip().lower() in lower_names]

    overton = conn.execute(
        """
        SELECT id, term, mention_count, display_on_main, description, investment_implications
        FROM overton_terms
        """
    ).fetchall()
    overton = [r for r in overton if (r["term"] or "").strip().lower() in lower_names]

    needs_rename = (
        len(suggested) == 1
        and (suggested[0]["term"] or "").strip().lower() != canonical.lower()
    )
    if len(suggested) < 2 and len(overton) < 2 and not needs_rename:
        return {"canonical": canonical, "merged": 0, "skipped": True}

    active_suggested = [r for r in suggested if r["status"] != "duplicate"]
    if not active_suggested and suggested:
        active_suggested = [max(suggested, key=lambda r: int(r["mention_count"] or 0))]

    survivor = _pick_survivor(active_suggested or suggested, canonical) if suggested else None
    total_mentions = sum(int(r["mention_count"] or 0) for r in active_suggested) if active_suggested else 0
    if overton and not suggested:
        total_mentions = sum(int(r["mention_count"] or 0) for r in overton)
    max_diversity = max((int(r["source_diversity"] or 0) for r in suggested), default=1)
    display_on_main = any(int(r["display_on_main"] or 0) for r in overton)

    best_def = survivor["definition"] if survivor else None
    best_inv = survivor["investment_implications"] if survivor else None
    best_quote = survivor["speaker_quote"] if survivor else None
    if suggested:
        richest = max(suggested, key=lambda r: int(r["mention_count"] or 0))
        best_def = best_def or richest["definition"]
        best_inv = best_inv or richest["investment_implications"]
        best_quote = best_quote or richest["speaker_quote"]

    if dry_run:
        print(
            f"  [dry-run] {canonical}: {len(suggested)} suggested, {len(overton)} overton "
            f"-> mentions={total_mentions}, display_on_main={display_on_main}"
        )
        return {
            "canonical": canonical,
            "merged": max(0, len(suggested) - 1) + max(0, len(overton) - 1),
            "total_mentions": total_mentions,
            "dry_run": True,
        }

    if survivor:
        conn.execute(
            """
            UPDATE suggested_terms
            SET term = ?,
                mention_count = ?,
                source_diversity = MAX(source_diversity, ?),
                definition = COALESCE(?, definition),
                investment_implications = COALESCE(?, investment_implications),
                speaker_quote = COALESCE(?, speaker_quote),
                status = CASE WHEN status = 'duplicate' THEN 'approved' ELSE status END
            WHERE id = ?
            """,
            (
                canonical,
                total_mentions,
                max_diversity,
                best_def,
                best_inv,
                best_quote,
                survivor["id"],
            ),
        )
        for row in suggested:
            if row["id"] == survivor["id"]:
                continue
            conn.execute(
                """
                UPDATE suggested_terms
                SET status = 'duplicate',
                    review_notes = ?
                WHERE id = ?
                """,
                (f"Merged into canonical term: {canonical}", row["id"]),
            )

    if overton:
        ot_survivor = next(
            (r for r in overton if (r["term"] or "").strip().lower() == canonical.lower()),
            max(overton, key=lambda r: int(r["mention_count"] or 0)),
        )
        conn.execute(
            """
            UPDATE overton_terms
            SET term = ?,
                mention_count = ?,
                display_on_main = MAX(display_on_main, ?),
                description = COALESCE(?, description),
                investment_implications = COALESCE(?, investment_implications)
            WHERE id = ?
            """,
            (
                canonical,
                total_mentions,
                1 if display_on_main else 0,
                best_def or ot_survivor["description"],
                best_inv or ot_survivor["investment_implications"],
                ot_survivor["id"],
            ),
        )
        for row in overton:
            if row["id"] == ot_survivor["id"]:
                continue
            conn.execute("DELETE FROM overton_terms WHERE id = ?", (row["id"],))

    for alias in aliases or []:
        conn.execute(
            """
            UPDATE definitions SET term = ?
            WHERE LOWER(TRIM(term)) = LOWER(?)
            AND NOT EXISTS (SELECT 1 FROM definitions WHERE LOWER(TRIM(term)) = LOWER(?))
            """,
            (canonical, alias.strip(), canonical),
        )
        conn.execute("DELETE FROM definitions WHERE LOWER(TRIM(term)) = LOWER(?)", (alias.strip(),))

    print(f"  merged {canonical}: mentions={total_mentions}, display_on_main={display_on_main}")
    return {"canonical": canonical, "total_mentions": total_mentions}


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge duplicate terms into canonical aliases")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = get_db()
    db.seed_term_aliases_from_json()
    merges = load_alias_merges_from_json()
    if not merges:
        print("No merges in term_aliases.json")
        return 1

    print(f"{'Dry run' if args.dry_run else 'Merging'} {len(merges)} alias groups...")
    with db._get_connection() as conn:
        for group in merges:
            canonical = (group.get("canonical") or "").strip()
            aliases = [a.strip() for a in (group.get("aliases") or []) if a.strip()]
            if not canonical:
                continue
            merge_group(conn, canonical, aliases, dry_run=args.dry_run)

    if not args.dry_run:
        synced = db.sync_all_overton_from_suggested()
        print(f"Synced {synced} overton rows from suggested_terms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
