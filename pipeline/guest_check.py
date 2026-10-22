"""Guest-vs-mention check for Pundits (Oct 22 2026).

A podcast 'guest_primary' appearance only counts as a guest if the person's name
appears in the episode title, the show notes, or the transcript speaker labels.
Otherwise the person was only mentioned and the appearance is not counted.

Names are matched fuzzily (ASR spellings: "Ron Emmanuel" ~ "Rahm Emanuel").
When an episode has neither show notes nor speaker labels there is nothing to
check against beyond the title, so the appearance is treated as unverifiable and
kept (most older Whisper transcripts have no labels and no saved show notes).
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Optional, Set

MATCH_RATIO = 0.75
_TITLES = {"dr", "mr", "mrs", "ms", "jr", "sr", "prof", "professor"}
_LABEL_COLON_RE = re.compile(r"^\[?([A-Z][\w.'\u2019-]*(?: [A-Z][\w.'\u2019-]*){0,3})\]?\s*:")
_LABEL_LINE_RE = re.compile(r"[A-Z][\w.'\u2019-]*(?: [A-Z][\w.'\u2019-]*){1,3}")
_BAD_BIO_RE = re.compile(r"^\s*(referenced|mentioned)\b", re.I)


def _tokens(s: str) -> list:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", s).split() if t not in _TITLES]


def name_in_text(name: str, text: str, ratio: float = MATCH_RATIO) -> bool:
    """True if `name` (fuzzily) appears as a run of words in `text`."""
    nt, tt = _tokens(name), _tokens(text)
    if not nt or not tt:
        return False
    k, target = len(nt), " ".join(nt)
    for i in range(len(tt) - k + 1):
        if difflib.SequenceMatcher(None, target, " ".join(tt[i:i + k])).ratio() >= ratio:
            return True
    return False


def speaker_labels(transcript_text: str) -> Set[str]:
    """Speaker labels: 'Name:' prefixes or a 2-4 word capitalised name alone on a line."""
    out = set()
    for line in (transcript_text or "").splitlines():
        line = line.strip()
        m = _LABEL_COLON_RE.match(line)
        if m:
            label = m.group(1)
        elif 1 < len(line) <= 40 and _LABEL_LINE_RE.fullmatch(line):
            label = line
        else:
            continue
        if len(_tokens(label)) >= 2:
            out.add(label)
    return out


def is_listed_guest(name: str, title: str = "", show_notes: str = "",
                    labels: Optional[Iterable[str]] = None) -> Optional[bool]:
    """True = named in title/show notes/speaker labels; False = only mentioned;
    None = unverifiable (no show notes and fewer than 2 speaker labels, name not in title)."""
    labels = set(labels or ())
    if name_in_text(name, title or ""):
        return True
    if show_notes and name_in_text(name, show_notes):
        return True
    n = len(_tokens(name))
    if any(len(_tokens(l)) == n and name_in_text(name, l) for l in labels):
        return True
    if not (show_notes or "").strip() and len(labels) < 2:
        return None
    return False


def episode_evidence(transcript_path: Optional[str]) -> tuple:
    """(show_notes, speaker_labels) from the transcript file and its .meta.json sidecar."""
    notes, labels = "", set()
    if not transcript_path:
        return notes, labels
    p = Path(transcript_path)
    try:
        meta = p.with_suffix(".meta.json")
        if meta.is_file():
            notes = (json.loads(meta.read_text(encoding="utf-8")) or {}).get("show_notes") or ""
    except Exception:
        notes = ""
    try:
        if p.is_file():
            labels = speaker_labels(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        labels = set()
    return notes, labels


def is_rejected_bio(bio: Optional[str]) -> bool:
    """Bios like 'Referenced via public comments…' / 'Mentioned as…' describe a mention, not a guest."""
    return bool(bio) and bool(_BAD_BIO_RE.match(bio))
