#!/usr/bin/env python3
"""Fix speaker/guest name spellings at the source, before analysis (Oct 2026).

Known names come from:
  * pipeline/summary_overrides.json  -> name_replacements (PR #406 sweep)
  * pipeline/guest_overrides.json    -> fixes (misspelling -> canonical, same word count only)
  * known_name_fixes.json             -> confirmed '| name' respellings from sweep_1013/fixes.md
                                        (that fixes.md is also read live if present / NAME_FIXES_MD)
  * per-episode RSS metadata          -> episode_title + episode_description / show_notes
    written to the transcript sidecar <stem>.meta.json by fetch_latest.py

Order of operations (normalize_text):
  1. exact known misspellings (word-boundary, case-sensitive);
  2. conservative fuzzy match against THIS episode's metadata names only
     (capitalized multiword names, similar word lengths, high similarity, never common words);
  3. close matches that metadata can't confirm are left unchanged and logged to
     pipeline/state/name_review.jsonl.

Export backstop: apply_to_cards() runs only the exact list, skipping direct quotes the same
way export_data._apply_name_replacements does.

CLI:  python3 pipeline/name_normalizer.py --check "Name" [--episode ID]
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
SUMMARY_OVERRIDES = PIPELINE_DIR / "summary_overrides.json"
GUEST_OVERRIDES = PIPELINE_DIR / "guest_overrides.json"
KNOWN_FIXES_JSON = PIPELINE_DIR / "known_name_fixes.json"  # vendored from sweep_1013/fixes.md
SWEEP_FIXES_MD = Path(os.environ.get("NAME_FIXES_MD", "/workspace/cos/sweep_1013/fixes.md"))
REVIEW_LOG = PIPELINE_DIR / "state" / "name_review.jsonl"
TRANSCRIPT_DIR = PIPELINE_DIR.parent / "transcripts"

FIX_THRESHOLD = 0.88     # metadata-confirmed fuzzy fix
REVIEW_THRESHOLD = 0.78  # close but unconfirmed -> log only

COMMON_WORDS = frozenset("""
the a an and or but of in on at to for with from by as is are was were be been this that these those
it its we you he she they our your their his her my me us them i not no yes so if then than there here
what when where who why how all any some more most other such only own same too very can will just
new old big good great first last next year years week day today show episode podcast part live
mr mrs ms dr sir ceo cfo founder host guest president senator governor professor chairman
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday
ai us uk eu fed market markets stock stocks bitcoin oil gold money capital fund bank street
america american china chinese europe european united states house white world global
north south east west new york wall silicon valley
""".split())

_NAME_WORD = r"[A-Z][a-zA-Z'\u2019\-]+"
_NAME_RE = re.compile(rf"\b{_NAME_WORD}(?:[ ]{_NAME_WORD}){{1,2}}\b")


def _wb_pattern(old: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(old) + r"(?![\w])")


def _is_respelling(old: str, new: str) -> bool:
    if not new or "(" in new or len(old.split()) > 4 or len(old.split()) != len(new.split()):
        return False
    return difflib.SequenceMatcher(None, old.lower(), new.lower()).ratio() >= 0.6


def _parse_fixes_md(path: Path) -> list[tuple[str, str]]:
    out = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return out
    for m in re.finditer(r'"([^"\n]+)" -> "([^"\n]+)" \| name\b', text):
        out.append((m.group(1), m.group(2)))
    return out


@lru_cache(maxsize=4)
def _known_cached(fixes_md: str) -> tuple:
    reps: dict[str, str] = {}
    try:
        so = json.loads(SUMMARY_OVERRIDES.read_text(encoding="utf-8"))
        for old, new in so.get("name_replacements", []):
            reps[old] = new
    except Exception:
        pass
    try:
        for old, new in json.loads(KNOWN_FIXES_JSON.read_text(encoding="utf-8")).get("fixes", []):
            reps.setdefault(old, new)
    except Exception:
        pass
    for old, new in _parse_fixes_md(Path(fixes_md)):
        if _is_respelling(old, new):
            reps.setdefault(old, new)
    try:
        go = json.loads(GUEST_OVERRIDES.read_text(encoding="utf-8"))
        for old, new in (go.get("fixes") or {}).items():
            # Only true respellings: same word count, not a trim/expansion ("Berg" -> "Milton Berg").
            if not new or old in new or new in old:
                continue
            if len(old.split()) != len(new.split()):
                continue
            reps.setdefault(old, new)
    except Exception:
        pass
    # Never "fix" a string into itself or a canonical name into something else.
    canon = {v for v in reps.values()}
    reps = {o: n for o, n in reps.items() if o != n and o not in canon}
    ordered = tuple(sorted(reps.items(), key=lambda kv: -len(kv[0])))
    return ordered, frozenset(canon)


def known_replacements() -> list[tuple[str, str]]:
    return list(_known_cached(str(SWEEP_FIXES_MD))[0])


def known_canonical_names() -> frozenset:
    return _known_cached(str(SWEEP_FIXES_MD))[1]


def reload_known():
    _known_cached.cache_clear()


# ---------------------------------------------------------------- metadata names

def _is_common(word: str) -> bool:
    return word.lower().strip("'\u2019-") in COMMON_WORDS


def extract_metadata_names(*texts: str) -> list[str]:
    """Capitalized 2-3 word names from episode title / description / show notes."""
    names, seen = [], set()
    for t in texts:
        if not t:
            continue
        t = re.sub(r"<[^>]+>", " ", t)
        for m in _NAME_RE.finditer(t):
            words = [w for w in m.group(0).split() if not _is_common(w)]
            # keep the longest run of non-common capitalized words (>=2)
            if len(words) < 2:
                continue
            cand = " ".join(words[:3])
            if cand not in seen:
                seen.add(cand)
                names.append(cand)
    return names


def metadata_names_from_sidecar(sidecar: dict) -> list[str]:
    sidecar = sidecar or {}
    return extract_metadata_names(
        sidecar.get("episode_title") or "",
        sidecar.get("episode_description") or "",
        sidecar.get("show_notes") or "",
    )


def load_sidecar(episode: str) -> dict:
    """Episode id = transcript stem (or path to a .meta.json / transcript)."""
    p = Path(episode)
    cands = [p] if p.suffix == ".json" else []
    if p.suffix == ".txt":
        cands.append(p.parent / f"{p.stem}.meta.json")
    cands.append(TRANSCRIPT_DIR / f"{episode}.meta.json")
    for c in cands:
        try:
            if c.exists():
                return json.loads(c.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


# ---------------------------------------------------------------- matching

def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _shape_ok(cand: str, target: str) -> bool:
    cw, tw = cand.split(), target.split()
    if len(cw) != len(tw):
        return False
    if any(_is_common(w) or len(w) < 2 for w in cw):
        return False
    return all(abs(len(a) - len(b)) <= 2 for a, b in zip(cw, tw))


def best_match(cand: str, targets) -> tuple[str | None, float]:
    best, score = None, 0.0
    for t in targets:
        if t == cand or not _shape_ok(cand, t):
            continue
        s = _similar(cand, t)
        if s > score:
            best, score = t, s
    return best, score


_WORD_RE = re.compile(_NAME_WORD)


def _candidate_names(text: str):
    """(start, end, name) for 2-3 word windows of consecutive capitalized, non-common words."""
    out = []
    for m in _NAME_RE.finditer(text):
        words = [(m.start() + w.start(), m.start() + w.end(), w.group(0))
                 for w in _WORD_RE.finditer(m.group(0))]
        runs, cur = [], []
        for w in words:
            if _is_common(w[2]):
                if cur:
                    runs.append(cur)
                cur = []
            else:
                cur.append(w)
        if cur:
            runs.append(cur)
        for run in runs:
            for size in (3, 2):
                for i in range(len(run) - size + 1):
                    a, b = run[i][0], run[i + size - 1][1]
                    out.append((a, b, text[a:b]))
    return out


def apply_exact(text: str, reps=None) -> str:
    if not isinstance(text, str) or not text:
        return text
    for old, new in (reps if reps is not None else known_replacements()):
        if old in text:
            text = _wb_pattern(old).sub(new, text)
    return text


def _log_review(entries: list[dict], log_path: Path | None = None):
    if not entries:
        return
    path = Path(log_path or REVIEW_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def normalize_text(text: str, metadata_names=(), episode_id: str = "", log_path=None,
                   fix_threshold: float = FIX_THRESHOLD, review_threshold: float = REVIEW_THRESHOLD):
    """Return (fixed_text, changes, review_entries). Logs review entries to name_review.jsonl."""
    if not isinstance(text, str) or not text:
        return text, [], []
    changes: list[dict] = []
    for old, new in known_replacements():
        if old in text:
            text, n = _wb_pattern(old).subn(new, text)
            if n:
                changes.append({"original": old, "fixed": new, "count": n, "how": "known"})

    meta = [m for m in dict.fromkeys(metadata_names or []) if m]
    canon = known_canonical_names()
    protected = set(meta) | set(canon)
    review, fuzzy_map, seen = [], {}, set()
    for start, end, cand in _candidate_names(text):
        if cand in seen or cand in protected:
            continue
        seen.add(cand)
        tgt, score = best_match(cand, meta)
        if tgt and score >= fix_threshold:
            fuzzy_map[cand] = (tgt, score)
            continue
        ktgt, kscore = best_match(cand, canon)
        if (ktgt and kscore >= review_threshold) or (tgt and score >= review_threshold):
            use, sc = (tgt, score) if (tgt and score >= kscore) else (ktgt, kscore)
            a, b = max(0, start - 60), min(len(text), end + 60)
            review.append({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "episode_id": str(episode_id), "original": cand, "candidate": use,
                "score": round(sc, 3), "source": "metadata" if use == tgt else "known_list",
                "context": text[a:b].replace("\n", " "),
            })
    for cand, (tgt, score) in fuzzy_map.items():
        text, n = _wb_pattern(cand).subn(tgt, text)
        if n:
            changes.append({"original": cand, "fixed": tgt, "count": n, "how": "metadata", "score": round(score, 3)})
    _log_review(review, log_path)
    return text, changes, review


def normalize_for_analysis(content: str, sidecar: dict, episode_id: str = "", log_path=None):
    """Analyzer hook: returns (fixed_transcript, changes). Never raises."""
    try:
        names = metadata_names_from_sidecar(sidecar)
        fixed, changes, _ = normalize_text(content, names, episode_id=episode_id, log_path=log_path)
        return fixed, changes
    except Exception as e:  # pragma: no cover - never block analysis
        print(f"    ⚠ name_normalizer skipped: {e}")
        return content, []


def apply_to_cards(obj):
    """Export backstop: exact known misspellings only, quote-safe (reuses #406 logic)."""
    import export_data
    return export_data._apply_name_replacements(obj, known_replacements())


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a name against the pipeline name normalizer.")
    ap.add_argument("--check", required=True, help='Name or text, e.g. "Mark Andrewson"')
    ap.add_argument("--episode", help="Transcript stem or path to .meta.json for metadata names")
    ap.add_argument("--log", action="store_true", help="Append near-misses to name_review.jsonl")
    a = ap.parse_args(argv)
    sidecar = load_sidecar(a.episode) if a.episode else {}
    names = metadata_names_from_sidecar(sidecar)
    import tempfile
    log_path = None if a.log else Path(tempfile.mkdtemp()) / "review.jsonl"
    fixed, changes, review = normalize_text(a.check, names, episode_id=a.episode or "", log_path=log_path)
    print(json.dumps({"input": a.check, "output": fixed, "changed": fixed != a.check,
                      "changes": changes, "needs_review": review,
                      "episode_metadata_names": names if a.episode else None}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
