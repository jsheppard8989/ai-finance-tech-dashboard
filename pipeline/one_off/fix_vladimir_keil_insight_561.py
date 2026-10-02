#!/usr/bin/env python3
"""
Correct Vladimir Keil / Lio spelling for insight 561 (episode 546, pundit 503).

Run from repo root:
  python3 pipeline/one_off/fix_vladimir_keil_insight_561.py
Then re-export site data:
  python3 pipeline/export_data.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

from workspace_paths import DB_PATH, workspace_root

INSIGHT_ID = 561
EPISODE_ID = 546
PUNDIT_ENTITY_ID = 503

BIO = (
    "Vladimir Keil is co-founder and CEO of Lio, "
    "which builds AI agents for enterprise procurement."
)


def fix_episode_text(text: str | None) -> str | None:
    if not text:
        return text
    out = text.replace("Vlad Kyle", "Vladimir Keil")
    out = out.replace("CEO of Leo", "CEO of Lio")
    out = out.replace("Leo agents", "Lio agents")
    out = out.replace("Leo\u2019s", "Lio\u2019s")
    out = out.replace("Leo's", "Lio's")
    return out


def fix_notable_quotes(raw: str | None) -> str | None:
    if not raw:
        return raw
    quotes = json.loads(raw)
    for item in quotes:
        speaker = item.get("speaker") or ""
        if speaker == "Vlad Kyle":
            item["speaker"] = "Vladimir Keil"
    return json.dumps(quotes, ensure_ascii=False)


def fix_key_takeaways(raw: str | None) -> str | None:
    if not raw:
        return raw
    takeaways = json.loads(raw)
    fixed = [fix_episode_text(t) for t in takeaways]
    return json.dumps(fixed, ensure_ascii=False)


def fix_transcript(path: Path) -> bool:
    if not path.is_file():
        print(f"  (skip missing transcript {path})")
        return False
    text = path.read_text(encoding="utf-8")
    new_text = fix_episode_text(text)
    new_text = new_text.replace("Leo co-founder", "Lio co-founder")
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    if not DB_PATH.exists():
        print(f"✗ Database not found at {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    transcript_rel = None
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT summary, notable_quotes FROM latest_insights WHERE id = ?",
            (INSIGHT_ID,),
        )
        row = cur.fetchone()
        if not row:
            print(f"✗ Insight {INSIGHT_ID} not found")
            return 1
        cur.execute(
            """
            UPDATE latest_insights
            SET summary = ?, notable_quotes = ?
            WHERE id = ?
            """,
            (
                fix_episode_text(row["summary"]),
                fix_notable_quotes(row["notable_quotes"]),
                INSIGHT_ID,
            ),
        )
        print(f"✓ latest_insights id={INSIGHT_ID}")

        cur.execute(
            "SELECT summary, key_takeaways, transcript_path FROM podcast_episodes WHERE id = ?",
            (EPISODE_ID,),
        )
        ep = cur.fetchone()
        if not ep:
            print(f"✗ Episode {EPISODE_ID} not found")
            return 1
        transcript_rel = ep["transcript_path"]
        cur.execute(
            """
            UPDATE podcast_episodes
            SET summary = ?, key_takeaways = ?
            WHERE id = ?
            """,
            (
                fix_episode_text(ep["summary"]),
                fix_key_takeaways(ep["key_takeaways"]),
                EPISODE_ID,
            ),
        )
        print(f"✓ podcast_episodes id={EPISODE_ID}")

        cur.execute(
            """
            UPDATE entities
            SET name = ?, slug = ?, bio = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            ("Vladimir Keil", "vladimir-keil", BIO, PUNDIT_ENTITY_ID),
        )
        print(f"✓ entities id={PUNDIT_ENTITY_ID}")

        cur.execute(
            """
            UPDATE overton_terms
            SET last_mentioned_speaker = ?
            WHERE last_mentioned_episode_id = ?
              AND last_mentioned_speaker LIKE '%Vlad Kyle%'
            """,
            ("Seema Amble, Vladimir Keil", EPISODE_ID),
        )
        print(f"✓ overton_terms last_mentioned_speaker ({cur.rowcount} rows)")

        cur.execute(
            "SELECT overview, episode_evidence FROM deep_dive_content WHERE insight_id = ?",
            (INSIGHT_ID,),
        )
        dd = cur.fetchone()
        if dd:
            cur.execute(
                """
                UPDATE deep_dive_content
                SET overview = ?, episode_evidence = ?
                WHERE insight_id = ?
                """,
                (
                    fix_episode_text(dd["overview"]),
                    fix_episode_text(dd["episode_evidence"]),
                    INSIGHT_ID,
                ),
            )
            print(f"✓ deep_dive_content insight_id={INSIGHT_ID}")

        conn.execute(
            """
            INSERT OR REPLACE INTO person_aliases (alias, canonical_name, confidence, source)
            VALUES ('Vlad Kyle', 'Vladimir Keil', 1.0, 'manual')
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO person_aliases (alias, canonical_name, confidence, source)
            VALUES ('vlad-kyle', 'Vladimir Keil', 1.0, 'manual')
            """
        )

        conn.commit()
    finally:
        conn.close()

    if transcript_rel:
        tpath = workspace_root() / transcript_rel
        if fix_transcript(tpath):
            print(f"✓ transcript {tpath.name}")

    print("Done. Run: python3 pipeline/export_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
