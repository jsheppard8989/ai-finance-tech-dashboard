#!/usr/bin/env python3
"""Term alias resolution and prompt glossary helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

ALIASES_JSON_PATH = Path(__file__).parent / "term_aliases.json"


def load_alias_merges_from_json() -> List[dict]:
    if not ALIASES_JSON_PATH.exists():
        return []
    data = json.loads(ALIASES_JSON_PATH.read_text(encoding="utf-8"))
    return list(data.get("merges") or [])


def build_tracked_terms_glossary(db, *, max_lines: int = 60) -> str:
    """Build CANONICAL GLOSSARY block for the emerging_terms prompt."""
    groups = db.get_term_alias_groups()
    lines: List[str] = []
    for canonical in sorted(groups.keys(), key=str.lower):
        aliases = [a for a in groups[canonical] if a.lower() != canonical.lower()]
        if aliases:
            not_part = ", ".join(aliases[:6])
            lines.append(f"- {canonical} (not: {not_part})")
        else:
            lines.append(f"- {canonical}")

    seen = {c.lower() for c in groups.keys()}
    for row in db.get_top_tracked_terms_for_glossary(limit=max_lines):
        term = (row.get("term") or "").strip()
        if not term or term.lower() in seen:
            continue
        lines.append(f"- {term}")
        seen.add(term.lower())
        if len(lines) >= max_lines:
            break

    if not lines:
        return "- (none yet — use Title Case for new coined phrases)"
    return "\n".join(lines[:max_lines])


def dedupe_emerging_terms(terms: List[dict], db) -> List[dict]:
    """Resolve aliases and keep at most one entry per canonical term (max 5)."""
    out: List[dict] = []
    seen: set[str] = set()
    for et in terms or []:
        raw = (et.get("term") or "").strip()
        if not raw:
            continue
        canonical = db.resolve_term(raw)
        key = canonical.lower()
        if key in seen:
            continue
        seen.add(key)
        merged = dict(et)
        merged["term"] = canonical
        out.append(merged)
        if len(out) >= 5:
            break
    return out


def expand_terms_for_scan(conn) -> List[Tuple[str, str]]:
    """
    Return (match_phrase, canonical_term) pairs for transcript scanning.
    Longer phrases are matched first by the caller.
    """
    pairs: List[Tuple[str, str]] = []
    seen_match: set[str] = set()

    def add(match_phrase: str, canonical: str) -> None:
        m = (match_phrase or "").strip()
        c = (canonical or "").strip()
        if len(m) < 3 or not c:
            return
        key = m.lower()
        if key in seen_match:
            return
        seen_match.add(key)
        pairs.append((m, c))

    rows = conn.execute(
        """
        SELECT term FROM overton_terms WHERE status = 'active'
        UNION
        SELECT term FROM suggested_terms WHERE status IN ('pending', 'approved')
        """
    ).fetchall()
    canonicals: set[str] = set()
    for row in rows:
        t = (row["term"] or "").strip()
        if t:
            canonicals.add(t)

    alias_rows = conn.execute(
        "SELECT canonical_term, alias FROM term_aliases ORDER BY LENGTH(alias) DESC"
    ).fetchall()
    for row in alias_rows:
        add(row["alias"], row["canonical_term"])
        canonicals.add(row["canonical_term"])

    for term in canonicals:
        add(term, term)

    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs
