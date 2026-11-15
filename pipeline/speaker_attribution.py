#!/usr/bin/env python3
"""
Speaker attribution rules for podcast summaries (Jared, Nov 15 2026).

Whisper transcripts carry NO speaker labels, so the summarizer has to infer who
is talking. These helpers keep that inference honest:

1. A fixed host roster per panel show (All-In, Moonshots). A guest counts only
   when the episode itself introduces one.
2. Clip voices and people read aloud keep their own name ("X, quoted by Y") and
   are never listed as guests.
3. Overton "last detected by" is the person who said the term, not the guest list.
4. Notable quotes, Overton quotes and Deep Dive evidence lines must be verbatim
   in the transcript (fuzzy 0.85, the existing two_pass_analyzer checker). Lines
   that fail are dropped, never reworded, and logged to
   pipeline/state/quote_check_drops.jsonl.
5. No guest names from episode titles on host-panel shows.
6. Hypotheticals stay hypotheticals; no added labels (prompt wording only).

Roster spellings come from the official show notes / feeds (checked Nov 15 2026):
- All-In feed name "All-In with Chamath, Jason, Sacks & Friedberg"; the besties
  are Chamath Palihapitiya, Jason Calacanis, David Sacks, David Friedberg.
- Moonshots (diamandis.com "Voices"): Peter H. Diamandis, Salim Ismail,
  Dave Blundin, Dr. Alexander Wissner-Gross (site spelling "Alex Wissner-Gross"),
  Emad Mostaque (in nearly every recent episode: "The Mates sit down with Emad").
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Rosters
# ---------------------------------------------------------------------------

ALL_IN_HOSTS = ["Jason Calacanis", "Chamath Palihapitiya", "David Sacks", "David Friedberg"]
MOONSHOTS_HOST = "Peter Diamandis"
MOONSHOTS_PANEL = ["Alex Wissner-Gross", "Salim Ismail", "Dave Blundin", "Emad Mostaque"]

# Show key -> (podcast-name matcher, roster, moderator note)
_PANEL_SHOWS = {
    "all-in": {
        "match": re.compile(r"^\s*all[\s-]*in\b", re.I),
        "roster": ALL_IN_HOSTS,
        "moderator": "Jason Calacanis",
    },
    "moonshots": {
        # "Moonshots with Peter Diamandis" only; "The Moonshot Podcast" (Google X) is a different show.
        "match": re.compile(r"^\s*moonshots\b", re.I),
        "roster": [MOONSHOTS_HOST] + MOONSHOTS_PANEL,
        "moderator": "Peter Diamandis",
    },
}

# Extra first-name / nickname cues used when narrowing a roster from show notes.
_ROSTER_ALIASES = {
    "Jason Calacanis": ["calacanis", "jason", "jcal", "j cal", "j-cal"],
    "Chamath Palihapitiya": ["chamath", "palihapitiya"],
    "David Sacks": ["sacks", "sachs", "david sachs", "davidsacks"],
    "David Friedberg": ["friedberg", "freiburg", "freeberg", "david freiburg"],
    "Peter Diamandis": ["diamandis", "peter"],
    "Alex Wissner-Gross": ["wissner-gross", "wissner gross", "alexander wissner", "alex"],
    "Salim Ismail": ["salim", "ismail"],
    "Dave Blundin": ["blundin", "dave"],
    "Emad Mostaque": ["emad", "mostaque"],
}


def panel_show_key(podcast_name: str) -> Optional[str]:
    """'all-in' / 'moonshots' for host-panel shows, else None."""
    name = (podcast_name or "").strip()
    for key, cfg in _PANEL_SHOWS.items():
        if cfg["match"].search(name):
            return key
    return None


def is_host_panel_show(podcast_name: str) -> bool:
    return panel_show_key(podcast_name) is not None


def show_roster(podcast_name: str) -> List[str]:
    key = panel_show_key(podcast_name)
    return list(_PANEL_SHOWS[key]["roster"]) if key else []


def show_moderator(podcast_name: str) -> Optional[str]:
    key = panel_show_key(podcast_name)
    return _PANEL_SHOWS[key]["moderator"] if key else None


def episode_roster(podcast_name: str, show_notes: str = "") -> List[str]:
    """Roster for one episode.

    Moonshots show notes name the panelists who are on that episode (e.g. #311 lists
    Peter, Salim, Alex and Emad, no Dave). When show notes name at least two roster
    members, keep only those (plus the main host). Otherwise use the full roster.
    """
    roster = show_roster(podcast_name)
    if not roster or not (show_notes or "").strip():
        return roster
    if panel_show_key(podcast_name) != "moonshots":
        return roster
    notes = show_notes.lower()
    present = []
    for name in roster:
        surname = name.split()[-1].lower()
        if surname in notes or any(
            len(a) > 5 and a in notes for a in _ROSTER_ALIASES.get(name, [])
        ):
            present.append(name)
    if len(present) < 2:
        return roster
    if roster[0] not in present:
        present.insert(0, roster[0])
    return present


# ---------------------------------------------------------------------------
# Prompt wording (summary_prompt_proposals_2026-11-15.md, changes 1, 2, 4, 6)
# ---------------------------------------------------------------------------

SPEAKER_ATTRIBUTION_RULES = """SPEAKER ATTRIBUTION (the transcript has NO speaker labels):
- Name a speaker ONLY when the transcript gives a cue: the person introduces themself, another speaker
  addresses them by name right before they answer ("Chamath, you're close to this..." means the NEXT
  turn is Chamath, not the asker), or the host's intro says who is about to speak.
- When a host asks a named co-host a question, the answer belongs to THAT co-host.
- The person who reads the opening news rundown, the stats, or the list of numbers is the moderator.
  On All-In that is Jason Calacanis unless the text says otherwise.
- The person who ASKS a question is not the person who answers it.
- If two speakers disagree, keep each view with its own speaker. Never merge or swap sides.
- If you have no cue, write "one host" / "a panelist" / "the hosts". A wrong name is worse than no name.
- For every named claim in key_takeaways and every notable quote, add "cue": the short transcript words
  that identify the speaker. (This field is for checking only and is not published.)
"""

CLIP_RULES = """CLIPS AND QUOTED PEOPLE:
- When a host plays a clip ("let's watch", "take a listen") or reads someone else's words ("quote",
  "he said", "he posted"), the words belong to the ORIGINAL person. Write "Paul Christiano (quoted by
  Peter Diamandis)" or "Demis Hassabis (clip)". Never credit them to the host.
- A host relaying someone else's view is not presenting their own view. Write "X raises Y's warning",
  not "X argues".
- "guests" = only people who speak live in the conversation. Never list clip voices, people quoted,
  or people only mentioned (e.g. Will Marshall, Paul Christiano, Demis Hassabis on Moonshots #311).
- A guest is present only when the episode itself introduces them live (e.g. "joining us today is...",
  "welcome to the show, X"). Never take a guest from the episode title. For each guest, give
  "intro_cue": the transcript words that introduce them.
"""

QUOTE_CHECK_RULES = """Quotes are machine-checked against the transcript. Copy the words exactly as they appear (filler words
may be dropped only at the start or end). A quote that is not found is deleted. If you cannot copy a
line exactly, leave it out. Never smooth, merge, or re-word a quote.
"""

HYPOTHETICAL_RULES = """- Numbers, dates and time frames must be the ones the speaker said. Do not turn a range into a new
  range or round it.
- If the speaker frames something as a hypothetical ("let's assume", "say", "if", "imagine"), either
  say it was a hypothetical or leave it out. Never present it as their forecast.
- Do not add labels the speaker did not use ("calling it a systemic vulnerability", "telemetry" when
  they said "a switch"). Describe what they said in their own terms.
"""

EMERGING_TERM_SPEAKER_FIELD = (
    "Full name of the person who said speaker_quote (same cue rules; clip voices as 'Name (clip)'; "
    "'' if unsure)"
)


def roster_block(podcast_name: str, show_notes: str = "") -> str:
    """Prompt block naming the fixed host roster for a panel show ('' for other shows)."""
    roster = episode_roster(podcast_name, show_notes)
    if not roster:
        return ""
    mod = show_moderator(podcast_name)
    lines = [
        "SHOW ROSTER (fixed; these are the regular hosts of this show, spelled exactly):",
        *[f"- {n}" for n in roster],
        f"Moderator: {mod}." if mod else "",
        "Only special episodes have a guest. Treat someone as a guest ONLY if the episode introduces them live.",
        "Everyone else whose words appear is a clip voice or a person quoted, not a guest.",
    ]
    return "\n".join(l for l in lines if l) + "\n"


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------

_CLIP_MARK = re.compile(r"\((?:clip|quoted by [^)]*|[^)]*clip[^)]*)\)", re.I)
_GENERIC_SPEAKERS = {
    "", "host", "hosts", "the hosts", "one host", "a host", "guest", "speaker",
    "a panelist", "panelist", "unidentified", "unknown", "co-host", "cohost",
}


def base_speaker_name(label: str) -> str:
    """'Paul Christiano (quoted by Peter Diamandis)' -> 'Paul Christiano'."""
    s = _CLIP_MARK.sub("", label or "")
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"\s+", " ", s).strip(" ,;:-")


def is_clip_label(label: str) -> bool:
    return bool(_CLIP_MARK.search(label or ""))


def is_generic_speaker(label: str) -> bool:
    return base_speaker_name(label).lower() in _GENERIC_SPEAKERS


def _surname(name: str) -> str:
    parts = base_speaker_name(name).split()
    return parts[-1].lower() if parts else ""


def _same_person(a: str, b: str) -> bool:
    a0, b0 = base_speaker_name(a).lower(), base_speaker_name(b).lower()
    if not a0 or not b0:
        return False
    return a0 == b0 or (_surname(a0) == _surname(b0) and _surname(a0) != "")


def canonical_roster_name(name: str, roster: List[str]) -> Optional[str]:
    """Map 'Chamath', 'Sacks', 'Alex' or 'Dr. Alexander Wissner-Gross' to the roster spelling."""
    for r in roster:
        if _same_person(name, r):
            return r
    base = base_speaker_name(name).lower()
    if not base:
        return None
    hits = [r for r in roster if base in _ROSTER_ALIASES.get(r, [])]
    if len(hits) == 1:
        return hits[0]
    first = base.split()[0]
    hits = [r for r in roster if r.split()[0].lower() == first]
    if len(hits) == 1 and len(base.split()) == 1:
        return hits[0]
    return None


# ---------------------------------------------------------------------------
# Guests (changes 2 and 5)
# ---------------------------------------------------------------------------

def clean_guests_and_hosts(
    analysis: Dict[str, Any],
    podcast_name: str,
    transcript: str = "",
    show_notes: str = "",
) -> List[Dict[str, Any]]:
    """Apply the roster to an analysis dict in place. Returns dropped guest records.

    Panel shows only:
    - hosts := the episode roster (fixed, official spellings).
    - roster members listed as guests move to hosts.
    - clip voices / quoted people and guests without an intro cue found in the
      transcript are dropped from guests.
    """
    key = panel_show_key(podcast_name)
    if not key:
        return []
    roster = episode_roster(podcast_name, show_notes)
    dropped: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    for g in analysis.get("guests") or []:
        if not isinstance(g, dict):
            continue
        name = (g.get("name") or "").strip()
        if not name:
            continue
        if canonical_roster_name(name, roster) or canonical_roster_name(name, show_roster(podcast_name)):
            continue  # a regular, not a guest
        if is_clip_label(name) or (g.get("role") or "").lower() in ("clip", "quoted", "mentioned"):
            dropped.append({"name": name, "reason": "clip_or_quoted"})
            continue
        cue = (g.get("intro_cue") or "").strip()
        if not cue:
            dropped.append({"name": name, "reason": "no_intro_cue"})
            continue
        if transcript and not _cue_in_transcript(cue, name, transcript):
            dropped.append({"name": name, "reason": "intro_cue_not_in_transcript"})
            continue
        kept.append(g)
    analysis["guests"] = kept
    analysis["hosts"] = [{"name": n, "role": "host"} for n in roster]
    return dropped


def _cue_in_transcript(cue: str, name: str, transcript: str) -> bool:
    from two_pass_analyzer import quote_in_transcript, normalize_for_quote_match

    norm_t = normalize_for_quote_match(transcript)
    if _surname(name) and _surname(name) not in norm_t and base_speaker_name(name).split()[0].lower() not in norm_t:
        return False
    return quote_in_transcript(cue, transcript, 0.85)


def title_guest_allowed(name: str, podcast_name: str, evidence_text: str = "", analyzer_guests=None) -> bool:
    """Change 5: a title-derived guest name is never used on panel shows; elsewhere
    only when the episode's own summary/takeaways or the analyzer's guests back it."""
    if not name:
        return False
    if is_host_panel_show(podcast_name):
        return False
    for g in analyzer_guests or []:
        gname = g.get("name") if isinstance(g, dict) else str(g)
        if gname and _same_person(gname, name):
            return True
    ev = (evidence_text or "").lower()
    full = base_speaker_name(name).lower()
    return bool(ev) and full in ev


# ---------------------------------------------------------------------------
# Overton speaker (change 3)
# ---------------------------------------------------------------------------

def emerging_term_speaker(
    et: Dict[str, Any],
    analysis: Dict[str, Any],
    podcast_name: str = "",
) -> Optional[str]:
    """Who said this term: et['speaker'] when given; never the episode guest list on
    panel shows. Returns None when unknown (the page shows a blank)."""
    raw = (et.get("speaker") or "").strip()
    if raw and not is_generic_speaker(raw):
        roster = show_roster(podcast_name)
        canon = canonical_roster_name(raw, roster) if roster else None
        if canon and not is_clip_label(raw):
            return canon
        return raw[:120]
    if is_host_panel_show(podcast_name):
        return None
    # Interview shows: one live guest is a safe default; otherwise leave blank.
    guests = [
        (g.get("name") or "").strip()
        for g in (analysis.get("guests") or [])
        if isinstance(g, dict) and (g.get("name") or "").strip() and not is_clip_label(g.get("name") or "")
    ]
    if len(guests) == 1:
        return guests[0]
    return None


def mention_scan_speakers(analysis: Dict[str, Any], podcast_name: str = "") -> Dict[str, Optional[str]]:
    """term (lower) -> speaker for terms this episode's analysis attributed."""
    out: Dict[str, Optional[str]] = {}
    for et in analysis.get("emerging_terms") or []:
        if isinstance(et, dict) and (et.get("term") or "").strip():
            out[(et.get("term") or "").strip().lower()] = emerging_term_speaker(et, analysis, podcast_name)
    return out


# ---------------------------------------------------------------------------
# Verbatim quote check (change 4)
# ---------------------------------------------------------------------------

QUOTE_MATCH_THRESHOLD = 0.85


def _log_drops(drops: List[Dict[str, Any]], log_path=None) -> None:
    if not drops:
        return
    for d in drops:
        print(f"    ✂ Quote check dropped {d['field']}: {d['speaker'] or '?'}: {d['quote'][:90]!r}", flush=True)
    try:
        if log_path is None:
            from workspace_paths import STATE_DIR
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            log_path = STATE_DIR / "quote_check_drops.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            for d in drops:
                f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), **d}) + "\n")
    except Exception as exc:  # logging must never break the pipeline
        print(f"    ⚠ Could not write quote_check_drops log: {exc}", flush=True)


def verify_analysis_quotes(
    analysis: Dict[str, Any],
    transcript: str,
    *,
    episode_ref: str = "",
    threshold: float = QUOTE_MATCH_THRESHOLD,
    log_path=None,
) -> List[Dict[str, Any]]:
    """Drop notable_quotes and emerging_terms[].speaker_quote that are not verbatim in the transcript.

    Edits ``analysis`` in place (quotes are dropped, never reworded) and logs each drop.
    Returns the list of drops.
    """
    from two_pass_analyzer import quote_in_transcript

    drops: List[Dict[str, Any]] = []
    if not transcript:
        return drops

    kept = []
    for q in analysis.get("notable_quotes") or []:
        text = (q.get("quote") if isinstance(q, dict) else str(q or "")) or ""
        if text and not quote_in_transcript(text, transcript, threshold):
            drops.append({
                "episode": episode_ref, "field": "notable_quotes",
                "speaker": (q.get("speaker") if isinstance(q, dict) else "") or "", "quote": text,
            })
            continue
        kept.append(q)
    analysis["notable_quotes"] = kept

    for et in analysis.get("emerging_terms") or []:
        if not isinstance(et, dict):
            continue
        sq = (et.get("speaker_quote") or "").strip()
        if sq and not quote_in_transcript(sq, transcript, threshold):
            drops.append({
                "episode": episode_ref, "field": f"emerging_terms[{et.get('term', '')}].speaker_quote",
                "speaker": et.get("speaker") or "", "quote": sq,
            })
            et["speaker_quote"] = ""

    _log_drops(drops, log_path)
    return drops


_EVIDENCE_LINE = re.compile(r'^\s*[-*•]?\s*(?P<speaker>[^:"\u201c]{2,120}?)\s*:\s*(?P<quote>.+?)\s*$')


def split_evidence_line(line: str) -> Tuple[str, str]:
    m = _EVIDENCE_LINE.match(line or "")
    if not m:
        return "", (line or "").strip()
    quote = m.group("quote").strip().strip('"\u201c\u201d').strip()
    return m.group("speaker").strip(), quote


def verify_evidence_lines(
    evidence: Any,
    transcript: str,
    *,
    episode_ref: str = "",
    threshold: float = QUOTE_MATCH_THRESHOLD,
    log_path=None,
) -> Tuple[Any, List[Dict[str, Any]]]:
    """Deep Dive episode_evidence: drop lines whose quote is not verbatim in the transcript.

    Accepts a list of lines or a newline-joined string; returns the same shape.
    """
    from two_pass_analyzer import quote_in_transcript

    if not transcript or not evidence:
        return evidence, []
    as_list = isinstance(evidence, list)
    lines = [str(x) for x in evidence] if as_list else str(evidence).split("\n")
    kept, drops = [], []
    for line in lines:
        if not line.strip():
            continue
        speaker, quote = split_evidence_line(line)
        if quote and not quote_in_transcript(quote, transcript, threshold):
            drops.append({"episode": episode_ref, "field": "deep_dive.episode_evidence",
                          "speaker": speaker, "quote": quote})
            continue
        kept.append(line)
    _log_drops(drops, log_path)
    return (kept if as_list else "\n".join(kept)), drops


# ---------------------------------------------------------------------------
# One call for the live pipeline
# ---------------------------------------------------------------------------

def apply_attribution_rules(
    analysis: Dict[str, Any],
    transcript: str,
    podcast_name: str,
    *,
    show_notes: str = "",
    episode_ref: str = "",
    log_path=None,
) -> Dict[str, Any]:
    """Roster + guest cleanup and verbatim quote check on a finished analysis (in place).

    Returns a small report: {"dropped_guests": [...], "dropped_quotes": [...]}.
    """
    if not analysis:
        return {"dropped_guests": [], "dropped_quotes": []}
    dropped_guests = clean_guests_and_hosts(analysis, podcast_name, transcript, show_notes)
    for g in dropped_guests:
        print(f"    ✂ Guest dropped ({g['reason']}): {g['name']}", flush=True)
    dropped_quotes = verify_analysis_quotes(
        analysis, transcript, episode_ref=episode_ref, log_path=log_path
    )
    return {"dropped_guests": dropped_guests, "dropped_quotes": dropped_quotes}
