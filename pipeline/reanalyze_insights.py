#!/usr/bin/env python3
"""Rewrite existing insight cards from the raw transcript.

Updates podcast_episodes summary / thesis / quotes and the matching
latest_insights row. Does not insert a new episode, does not touch skipped
ids, and does not call Moonshot/Kimi.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from analyze_transcript import (  # noqa: E402
    _fold_to_ascii,
    analyze_transcript_with_ai,
    get_ai_client,
)
from site_text_sanitize import strip_reader_advice  # noqa: E402
from transcript_window import normalize_notable_quotes  # noqa: E402
from workspace_paths import DB_PATH  # noqa: E402

SUMMARY_CAP = 8000
_ADVICE_RE = re.compile(r"investors should", re.I)


def _ensure_quote_columns(conn: sqlite3.Connection) -> None:
    for stmt in (
        "ALTER TABLE podcast_episodes ADD COLUMN notable_quotes TEXT",
        "ALTER TABLE latest_insights ADD COLUMN notable_quotes TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass


def _known_names(title: str, guest: str) -> list[str]:
    """Two-word names from the episode title. Never glue the next company on."""
    skip = {
        "The", "A", "An", "And", "Of", "For", "In", "On", "To", "With", "How",
        "Why", "What", "After", "Before", "World", "Show", "Podcast", "Part",
        "Episode", "Live", "State", "Markets", "Market", "Code", "Next", "Era",
        "Life", "Building", "Team", "Speed", "Case", "Against", "Pause", "Private",
        "Credit", "Boom", "Over", "Redemption", "Requests", "Exceed", "Liquidity",
        "Autonomous", "Weapons", "Ancient", "Real", "Time", "Worlds", "Engineering",
        "Personal", "Agent", "Race", "Here", "Global", "Geopolitical", "Puzzle",
        "Decoding", "Software", "Better", "Write", "Can", "Isn", "Do", "You",
        "Secure", "Agents", "Healthcare", "Broken", "Incentives", "Disease", "Early",
        "Potential", "Trillion", "Buildout", "AI", "US", "MacroVoices", "Anthropic",
        "Anduril", "Spotify", "Runway", "Harvey", "Marlton", "Moonshots", "Humanoids",
        "Build", "Won", "Wont",
    }
    names = []
    segments = re.split(r"\s*[|,&]\s*|\s+[—–-]\s+", title or "")
    for seg in segments:
        tokens = re.findall(r"[A-Z][A-Za-z'.’-]{1,}", seg)
        buf = []
        for tok in tokens:
            bare = tok.replace("’", "'").replace("'", "")
            if tok in skip or bare in skip or tok.isupper() or tok.endswith(("'s", "’s")):
                buf = []
                continue
            buf.append(tok)
            if len(buf) == 2:
                names.append(buf[0] + " " + buf[1])
                buf = []
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    guest = " ".join((guest or "").split())
    if guest and guest.lower() not in {"unknown", "guest"}:
        from difflib import SequenceMatcher
        near = any(
            SequenceMatcher(None, guest.lower(), n.lower()).ratio() >= 0.72
            for n in out
        )
        if not near:
            out.append(guest)
    return out


def _apply_spellings(text: str, known: list[str]) -> str:
    from difflib import SequenceMatcher

    if not text:
        return text
    updated = text
    for name in known:
        if name.lower() in updated.lower():
            continue
        # Replace a close full-string window of the same token count.
        n_tokens = len(name.split())
        words = re.findall(r"\b[\w.'’-]+\b", updated)
        # walk windows
        spans = list(re.finditer(r"\b[\w.'’-]+(?:\s+[\w.'’-]+){%d}\b" % (n_tokens - 1), updated))
        for m in spans:
            chunk = m.group(0)
            if SequenceMatcher(None, chunk.lower(), name.lower()).ratio() >= 0.86:
                updated = updated[: m.start()] + name + updated[m.end() :]
                break
    return updated


def _recap_ok(summary: str, thesis: str, quotes: list) -> str:
    if not summary or len(summary.strip()) < 500:
        return "recap shorter than 500 characters"
    if summary.count("\n\n") < 1 and summary.count(". ") < 4:
        return "recap is not multiple paragraphs"
    if not thesis or len(thesis.split()) > 45:
        return "thesis missing or longer than 45 words"
    if _ADVICE_RE.search(thesis) or _ADVICE_RE.search(summary):
        return "contains Investors should"
    if len(quotes) < 2:
        return "fewer than 2 named quotes"
    return ""


def reanalyze_one(conn: sqlite3.Connection, insight_id: int, client_info) -> str:
    row = conn.execute(
        """
        SELECT li.id, li.title, li.podcast_episode_id,
               pe.transcript_path, pe.podcast_name, pe.episode_title, pe.guest_name
        FROM latest_insights li
        JOIN podcast_episodes pe ON pe.id = li.podcast_episode_id
        WHERE li.id = ?
        """,
        (insight_id,),
    ).fetchone()
    if not row:
        return "insight or episode missing"
    path = Path(row["transcript_path"] or "")
    if not path.is_file():
        return f"transcript missing: {path}"
    raw = path.read_text(encoding="utf-8", errors="ignore")
    known = _known_names(row["episode_title"] or row["title"] or "", row["guest_name"] or "")
    hint_lines = [f"Episode title: {row['episode_title'] or row['title']}"]
    if row["guest_name"]:
        hint_lines.append(f"Guest on file: {row['guest_name']}")
    for name in known:
        hint_lines.append(f"- {name}")
    if insight_id == 541:
        hint_lines.append("Host: Max Wiethe of Other People's Money. The transcript mishears him as Max Weethy. Do not call him Jack Farley.")
        hint_lines.append("Guest: James Elbaor of Marlton. Not Elbauer.")
        hint_lines.append("Blackstone's private credit interval fund is BCRED, not B Cred.")
    if insight_id == 533:
        hint_lines.append("Guest: Eddy Lazzarin. The transcript mishears him as Eddie Lazaran.")
    hint = "\n".join(hint_lines)

    from term_alias_util import build_tracked_terms_glossary
    from db_manager import get_db

    glossary = ""
    try:
        glossary = build_tracked_terms_glossary(get_db())
    except Exception:
        glossary = ""

    last_reason = "no attempt"
    analysis = None
    for attempt in range(1, 4):
        extra = hint
        if attempt > 1:
            extra += f"\n\nPREVIOUS ATTEMPT REJECTED: {last_reason}. Fix that and keep the JSON schema."
        analysis = analyze_transcript_with_ai(
            client_info,
            raw,
            row["podcast_name"] or "",
            content_from_digest=False,
            tracked_terms_glossary=glossary,
            name_hint=extra,
        )
        if not analysis:
            last_reason = "model returned no JSON"
            continue
        analysis = _fold_to_ascii(analysis)
        summary = _apply_spellings(str(analysis.get("summary") or "").strip(), known)
        thesis = strip_reader_advice(str(analysis.get("investment_thesis") or "").strip())
        thesis = _apply_spellings(thesis, known)
        quotes = normalize_notable_quotes(analysis.get("notable_quotes"), known)
        norm_raw = re.sub(r"\s+", " ", raw).lower()
        verbatim = []
        for q in quotes:
            nq = re.sub(r"\s+", " ", q["quote"]).lower().strip(" \"'")
            if len(nq) >= 12 and nq in norm_raw:
                verbatim.append(q)
        quotes = verbatim
        fixes = (
            ("Max Weethy", "Max Wiethe"),
            ("James Elbauer", "James Elbaor"),
            ("Eddie Lazaran", "Eddy Lazzarin"),
            ("Androle", "Anduril"),
            ("B Cred", "BCRED"),
            ("Cloud Code", "Claude Code"),
            ("Anisha Charya", "Anish Acharya"),
            ("Neco Health", "Neko Health"),
        )
        def _fix(s):
            for a, b in fixes:
                s = s.replace(a, b)
            return s
        summary = _fix(summary)
        thesis = _fix(thesis)
        for q in quotes:
            q["speaker"] = _fix(q["speaker"])
            q["quote"] = _fix(q["quote"])
        # Also scrub advice sentences out of the recap.
        paras = []
        for para in re.split(r"\n\s*\n", summary):
            kept = []
            for sent in re.split(r"(?<=[.!?])\s+", para.strip()):
                if sent and not _ADVICE_RE.search(sent):
                    kept.append(sent)
            if kept:
                paras.append(" ".join(kept))
        summary = "\n\n".join(paras).strip()
        last_reason = _recap_ok(summary, thesis, quotes)
        if last_reason:
            print(f"    attempt {attempt} rejected: {last_reason} (summary {len(summary)} chars)", flush=True)
            print("    summary head:", summary[:240].replace("\n", " | "), flush=True)
            continue
        takeaways = analysis.get("key_takeaways") or []
        if not isinstance(takeaways, list):
            takeaways = []
        conn.execute(
            """
            UPDATE podcast_episodes
               SET summary = ?, investment_thesis = ?, key_takeaways = ?, notable_quotes = ?
             WHERE id = ?
            """,
            (
                summary[:SUMMARY_CAP],
                thesis[:500],
                json.dumps(takeaways),
                json.dumps(quotes),
                row["podcast_episode_id"],
            ),
        )
        conn.execute(
            """
            UPDATE latest_insights
               SET summary = ?, key_takeaway = ?, notable_quotes = ?
             WHERE id = ?
            """,
            (summary[:SUMMARY_CAP], thesis[:500], json.dumps(quotes), insight_id),
        )
        guest_now = (row["guest_name"] or "").strip()
        if guest_now:
            from difflib import SequenceMatcher
            for name in known:
                ratio = SequenceMatcher(None, guest_now.lower(), name.lower()).ratio()
                if 0.84 <= ratio < 1.0:
                    conn.execute(
                        "UPDATE podcast_episodes SET guest_name=? WHERE id=?",
                        (name, row["podcast_episode_id"]),
                    )
                    print(f"    guest spelling: {guest_now} -> {name}", flush=True)
                    break
        if insight_id == 533:
            conn.execute(
                "UPDATE podcast_episodes SET guest_name=? WHERE id=?",
                ("Eddy Lazzarin", row["podcast_episode_id"]),
            )
        if insight_id == 541:
            conn.execute(
                "UPDATE latest_insights SET source_name=? WHERE id=?",
                ("Other People's Money with Max Wiethe", insight_id),
            )
            conn.execute(
                "UPDATE podcast_episodes SET podcast_name=? WHERE id=?",
                ("Other People's Money with Max Wiethe", row["podcast_episode_id"]),
            )
        conn.commit()
        print(f"    thesis: {thesis}", flush=True)
        print(f"    quotes: {quotes[0]['speaker']}: {quotes[0]['quote'][:80]}", flush=True)
        return ""
    return last_reason


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in __import__("os").environ:
            __import__("os").environ[k] = v


def reanalyze_insight_ids(ids: list[int]) -> int:
    _load_dotenv()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _ensure_quote_columns(conn)
    client = get_ai_client()
    if not client:
        print("No AI client")
        return 1
    kind = client[0]
    if kind == "moonshot":
        print("Refusing to call Moonshot/Kimi")
        return 1
    print(f"Provider: {kind} (Kimi not called)", flush=True)
    failed = []
    for iid in ids:
        print(f"\n=== insight {iid} ===", flush=True)
        err = reanalyze_one(conn, iid, client)
        if err:
            print(f"  FAILED {iid}: {err}", flush=True)
            failed.append((iid, err))
        else:
            print(f"  rewritten {iid}", flush=True)
    conn.close()
    if failed:
        print("FAILURES", failed)
        return 1
    return 0


if __name__ == "__main__":
    raw = sys.argv[1:]
    if not raw:
        print("usage: reanalyze_insights.py 551,548,...")
        raise SystemExit(2)
    blob = ",".join(raw)
    ids = [int(x.strip()) for x in blob.split(",") if x.strip()]
    raise SystemExit(reanalyze_insight_ids(ids))
