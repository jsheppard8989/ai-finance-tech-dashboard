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
    "Chamath Palihapitiya": ["chamath", "palihapitiya", "shamath", "jamath", "chamat"],
    "David Sacks": ["sacks", "sachs", "david sachs", "davidsacks"],
    # Whisper renders Friedberg many ways ("free burger", "free bird" in eps 680).
    "David Friedberg": ["friedberg", "freiburg", "freeberg", "david freiburg", "freeburg", "freberg",
                        "frieberg", "free burger", "free bird", "freebird"],
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
    "a panelist", "panelist", "unidentified", "unknown", "co-host", "cohost", "a clip",
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
    podcast_name: str = "",
    show_notes: str = "",
    turns=None,
    turn_log_path=None,
) -> Tuple[Any, List[Dict[str, Any]]]:
    """Deep Dive episode_evidence: drop lines whose quote is not verbatim in the transcript.

    Accepts a list of lines or a newline-joined string; returns the same shape. On panel shows the
    speaker label must be backed by the transcript; with caption ``turns`` the caption turn decides
    (see turn_label), otherwise the #826 cue check.
    """
    from two_pass_analyzer import quote_in_transcript

    if not transcript or not evidence:
        return evidence, []
    as_list = isinstance(evidence, list)
    lines = [str(x) for x in evidence] if as_list else str(evidence).split("\n")
    kept, drops = [], []
    turn_names: List[Dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        speaker, quote = split_evidence_line(line)
        if quote and not quote_in_transcript(quote, transcript, threshold):
            drops.append({"episode": episode_ref, "field": "deep_dive.episode_evidence",
                          "speaker": speaker, "quote": quote})
            continue
        if podcast_name and speaker and quote and is_host_panel_show(podcast_name):
            roster = episode_roster(podcast_name, show_notes)
            info = {"status": "not_located"}
            if turns is not None:
                new, info = turn_label(speaker, [quote], turns, roster, _norm(transcript))
                if info["status"] != "not_located" and new != speaker:
                    t = info.get("turn")
                    print(f"    ↺ Evidence speaker from caption turn ({info['status']}): {speaker} → {new}", flush=True)
                    if info["status"] == "named":
                        turn_names.append({"episode": episode_ref, "field": "deep_dive.episode_evidence",
                                           "speaker": speaker, "new_speaker": new, "reason": "caption_turn_named",
                                           "turn_start": t.stamp, "evidence": t.evidence, "cue": t.cue[-200:],
                                           "quote": quote[:300]})
                    line = f"{new or 'one host'}: {quote}"
            if info["status"] == "not_located" and not speaker_is_cued(speaker, quote, _norm(transcript), roster):
                print(f"    ↺ Evidence speaker not cued in transcript, now 'one host': {speaker}", flush=True)
                line = f"one host: {quote}"
        kept.append(line)
    if turn_names:
        from caption_turns import log_turn_names
        log_turn_names(turn_names, turn_log_path)
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
    turns=None,
) -> Dict[str, Any]:
    """Roster + guest cleanup and verbatim quote check on a finished analysis (in place).

    ``turns``: optional caption_turns.TurnMap (YouTube '>>' speaker turns) for panel shows.

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
    relabels = enforce_speaker_cues(
        analysis, transcript, podcast_name, show_notes=show_notes, episode_ref=episode_ref,
        log_path=(str(log_path).replace("quote_check_drops", "speaker_cue_relabels") if log_path else None),
        turns=turns,
        turn_log_path=(str(log_path).replace("quote_check_drops", "speaker_turn_names") if log_path else None),
    )
    prose = enforce_named_prose(
        analysis, podcast_name, show_notes=show_notes, episode_ref=episode_ref,
        log_path=(str(log_path).replace("quote_check_drops", "speaker_cue_relabels") if log_path else None),
    )
    return {"dropped_guests": dropped_guests, "dropped_quotes": dropped_quotes,
            "speaker_relabels": relabels, "prose_relabels": prose}


# ---------------------------------------------------------------------------
# Change 1, enforced in code: a named speaker needs a cue near the words
# ---------------------------------------------------------------------------
# The model is asked for a cue, but the Nov 15 re-run showed it fills "cue" with a
# fragment of the quote itself and still guesses (Calacanis's "Microsoft killer" line
# went to Friedberg; Friedberg's "management conversations" line went to Sacks). So on
# panel shows a named label is kept only when the transcript backs it: the person's
# name (or a known nickname / Whisper spelling) appears shortly before the words, i.e.
# they were addressed or introduced. Otherwise the label becomes "one host".

CUE_WINDOW_CHARS = 1200         # roster member: last roster name said before the words, this close
CLIP_CUE_WINDOW_CHARS = 4000    # clip / quoted voice: their own name before playing/reading
_CLAIM_LISTS = ("major_claims", "predictions", "investment_ideas", "contrarian_ideas", "risks")


def _norm(s: str) -> str:
    from two_pass_analyzer import normalize_for_quote_match
    return normalize_for_quote_match(s or "")


def _locate(norm_quote: str, norm_tx: str) -> int:
    """Char offset of the quote in the normalized transcript, or -1."""
    if not norm_quote:
        return -1
    i = norm_tx.find(norm_quote[:80])
    if i >= 0:
        return i
    words = norm_quote.split()
    for start in range(0, max(1, len(words) - 5), 2):
        probe = " ".join(words[start:start + 6])
        if len(probe) < 15:
            continue
        i = norm_tx.find(probe)
        if i >= 0:
            return max(0, i - len(" ".join(words[:start])) - 1)
    return -1


def _roster_tokens(member: str) -> List[str]:
    toks = set(_ROSTER_ALIASES.get(member, []))
    toks.add(member.split()[-1])
    toks.add(member.split()[0])
    return [t for t in {_norm(t) for t in toks} if len(t) >= 3]


# "Alex and I have spoken…", "Sacks said…": talking about someone, not handing them the floor.
_THIRD_PERSON = r" (?:and|said|says|mentioned|told|was|is|has|had|thinks|thought|wrote|tweeted|posted)\b"


def _last_roster_mention(text: str, roster: List[str]):
    """(member, offset) of the last roster name in ``text``, or (None, -1)."""
    best = (None, -1)
    for m in roster:
        for t in _roster_tokens(m):
            for mm in re.finditer(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])(?!" + _THIRD_PERSON + r")", text):
                if mm.start() > best[1]:
                    best = (m, mm.start())
    return best


def _names_outsider(window: str, label: str) -> bool:
    """Clip / quoted voice named in the window (first name, or a Whisper-close surname)."""
    from difflib import SequenceMatcher
    parts = [_norm(p) for p in base_speaker_name(label).split() if p]
    if not parts:
        return False
    words = set(window.split())
    first, last = parts[0], parts[-1]
    if len(first) >= 4 and first in words:
        return True
    if len(last) >= 4:
        for w in words:
            if w == last or (len(last) >= 5 and SequenceMatcher(None, w, last).ratio() >= 0.8):
                return True
    return False


def is_hedged_label(label: str) -> bool:
    """'one host / Alex', 'Salim (inferred)', 'Alex and one host': the model itself is unsure."""
    if is_clip_label(label):
        return False
    return bool(re.search(r"/|\bone host\b|\bpanel|\binferred\b|\bunclear\b|\bprobably\b|\blikely\b|\band\b|\?",
                          label, re.IGNORECASE))


def speaker_is_cued(label: str, quote: str, transcript_norm: str, roster: List[str], cue: str = "") -> bool:
    """True when the transcript itself points at ``label`` for these words.

    Roster member: the last roster name said before the words is this person (they were just
    addressed, or the moderator handed to them) and it is within CUE_WINDOW_CHARS.
    Clip / quoted / outside voice: their own name is said within CLIP_CUE_WINDOW_CHARS before.
    Without speaker labels this cannot see turn changes, so it errs toward "one host".
    """
    if is_generic_speaker(label):
        return True
    if is_hedged_label(label):
        return False
    pos = _locate(_norm(quote), transcript_norm)
    if pos < 0:
        return False
    canon = None if is_clip_label(label) else canonical_roster_name(label, roster)
    if canon:
        lo = max(0, pos - CUE_WINDOW_CHARS)
        member, off = _last_roster_mention(transcript_norm[lo:pos], roster)
        return member == canon
    return _names_outsider(transcript_norm[max(0, pos - CLIP_CUE_WINDOW_CHARS):pos], label)


def _quoted_by_fix(label: str, name: str) -> str:
    """'Paul Christiano (quoted by Alex Wissner-Gross)' read in Peter's turn -> '(quoted by Peter Diamandis)'."""
    return re.sub(r"\(quoted by [^)]*\)", f"(quoted by {name})", label, flags=re.I)


def turn_label(label: str, evidence: List[str], turns, roster: List[str], transcript_norm: str = ""):
    """Speaker label from caption turns (follow-up to #826, Nov 15 2026).

    Returns (new_label, info) where info["status"] is:
      "named"   - the words sit in a turn named by a directed question / self-ID / continuation
      "clip"    - the words sit in a clip; a host label becomes "a clip"
      "unnamed" - the words sit in a turn with no solid evidence; a roster label becomes "one host"
      "not_located" - no evidence quote could be placed in one caption turn (caller falls back to
                      the #826 cue check)
    Clip / quoted-by labels are kept when the #826 clip check finds the person named before the words.
    """
    info = {"status": "not_located", "why": "no_evidence"}
    for ev in evidence:
        if not ev:
            continue
        info = turns.speaker_for(ev)
        if info["status"] != "not_located":
            info["quote"] = ev
            break
    st = info["status"]
    if st == "not_located":
        return label, info
    clip_ok = bool(label) and is_clip_label(label) and (
        not transcript_norm or speaker_is_cued(label, info["quote"], transcript_norm, roster))
    if st == "named":
        name = info["name"]
        if clip_ok:
            return (_quoted_by_fix(label, name) if re.search(r"quoted by", label, re.I) else label), info
        return name, info
    if st == "clip":
        if clip_ok:
            return label, info
        return ("a clip" if label else ""), info
    # unnamed turn
    if clip_ok:
        return label, info
    if label and not is_generic_speaker(label):
        return "one host", info
    return label, info


def enforce_speaker_cues(
    extraction: Dict[str, Any],
    transcript: str,
    podcast_name: str,
    *,
    show_notes: str = "",
    episode_ref: str = "",
    log_path=None,
    turns=None,
    turn_log_path=None,
) -> List[Dict[str, Any]]:
    """Panel shows: relabel to 'one host' every quote / claim speaker the transcript does not cue.

    With ``turns`` (a caption_turns.TurnMap from YouTube '>>' markers) the speaker comes from the
    caption turn the words sit in: a named turn gives its name (also to items the model left as
    'one host'), an unnamed turn gives 'one host', a clip turn never gives a host. Items that can't
    be placed in one caption turn fall back to the #826 cue check. Every name assigned this way is
    logged with its evidence to state/speaker_turn_names.jsonl.

    Edits ``extraction`` (pass-1 output or a final analysis) in place; returns the relabels.
    """
    if not is_host_panel_show(podcast_name) or not transcript or not extraction:
        return []
    roster = episode_roster(podcast_name, show_notes)
    tnorm = _norm(transcript)
    changes: List[Dict[str, Any]] = []
    named: List[Dict[str, Any]] = []

    def check(item: Dict[str, Any], field: str, evidence: List[str]):
        label = (item.get("speaker") or "").strip()
        if turns is not None:
            new, info = turn_label(label, evidence, turns, roster, tnorm)
            if info["status"] != "not_located":
                t = info.get("turn")
                if new != label:
                    rec = {"episode": episode_ref, "field": field, "speaker": label, "new_speaker": new,
                           "reason": f"caption_turn_{info['status']}",
                           "turn_start": t.stamp if t else "", "quote": (info.get("quote") or "")[:300]}
                    if info["status"] == "named":
                        rec.update({"evidence": t.evidence, "cue": t.cue[-200:]})
                        named.append(rec)
                    else:
                        changes.append(rec)
                    item["speaker"] = new
                elif info["status"] == "named" and label:
                    named.append({"episode": episode_ref, "field": field, "speaker": label, "new_speaker": new,
                                  "reason": "caption_turn_named_confirms", "turn_start": t.stamp,
                                  "evidence": t.evidence, "cue": t.cue[-200:],
                                  "quote": (info.get("quote") or "")[:300]})
                return
        if not label or is_generic_speaker(label):
            return
        cue = item.get("cue") or ""
        ok = any(speaker_is_cued(label, ev, tnorm, roster, cue) for ev in evidence if ev)
        if not ok:
            changes.append({"episode": episode_ref, "field": field, "speaker": label,
                            "quote": (evidence[0] if evidence else "")[:300]})
            item["speaker"] = "one host"
        else:
            canon = canonical_roster_name(label, roster) if not is_clip_label(label) else None
            if canon:
                item["speaker"] = canon

    for q in extraction.get("high_value_quotes") or []:
        if isinstance(q, dict):
            check(q, "high_value_quotes", [q.get("quote") or ""])
    for q in extraction.get("notable_quotes") or []:
        if isinstance(q, dict):
            check(q, "notable_quotes", [q.get("quote") or ""])
    for ca in extraction.get("companies_and_assets") or []:
        if isinstance(ca, dict):
            for kq in ca.get("key_quotes") or []:
                if isinstance(kq, dict):
                    check(kq, f"companies_and_assets[{ca.get('name', '')}].key_quotes", [kq.get("quote") or ""])
    for key in _CLAIM_LISTS:
        for c in extraction.get(key) or []:
            if not isinstance(c, dict):
                continue
            if not c.get("speaker") and turns is None:
                continue
            ev = []
            for f in ("evidence", "support_from_transcript", "quote", "quotes"):
                v = c.get(f)
                if isinstance(v, str):
                    ev.append(v)
                elif isinstance(v, list):
                    ev.extend(str(x.get("quote") if isinstance(x, dict) else x) for x in v)
            # Claim text is a paraphrase; only verbatim evidence can be located.
            if not c.get("speaker") and not ev:
                continue
            check(c, key, ev)
    for et in extraction.get("emerging_terms") or []:
        if isinstance(et, dict) and (et.get("speaker") or (turns is not None and et.get("speaker_quote"))):
            check(et, f"emerging_terms[{et.get('term', '')}]", [et.get("speaker_quote") or ""])
            if et.get("speaker") in ("one host", "a clip"):
                et["speaker"] = ""

    for c in changes:
        print(f"    ↺ Speaker not cued in transcript, now '{c.get('new_speaker', 'one host')}': {c['field']}: {c['speaker']}", flush=True)
    for c in named:
        if c["reason"] != "caption_turn_named_confirms":
            print(f"    ✓ Caption turn names speaker: {c['field']}: {c['speaker'] or '(none)'} → {c['new_speaker']} "
                  f"({c['evidence']} at {c['turn_start']})", flush=True)
    if changes:
        try:
            if log_path is None:
                from workspace_paths import STATE_DIR
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                log_path = STATE_DIR / "speaker_cue_relabels.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                for c in changes:
                    f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), **c}) + "\n")
        except Exception as exc:
            print(f"    ⚠ Could not write speaker_cue_relabels log: {exc}", flush=True)
    if named:
        from caption_turns import log_turn_names
        log_turn_names(named, turn_log_path)
    return changes


# ---------------------------------------------------------------------------
# Named prose (summary / takeaways / thesis) must rest on a cued item
# ---------------------------------------------------------------------------
# Pass 2 writes prose from the extraction but can still put a roster name on a point the
# extraction left as "one host" (re-run: Chamath's 50-150 bp line went to Sacks). On panel
# shows, a sentence that names a roster member keeps the name only if that person has a
# cued quote/claim in the extraction (or a kept notable quote) sharing the point's words.

_STOP = set("""about above after again against also among another because been before being below
between both could does doing down during each even every from further have having here into
itself just like more most much must only other over same says said should since some such than
that their them then there these they this those through under until very were what when where
which while will with would your argues argued frames framed warns warned thinks notes noted
episode host hosts panel""".split())


def _content_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", _norm(text)) if len(w) >= 4 and w not in _STOP}


def _cued_texts_by_member(extraction: Dict[str, Any], analysis: Dict[str, Any], roster: List[str]) -> Dict[str, List[set]]:
    out: Dict[str, List[set]] = {m: [] for m in roster}

    def add(label: str, *texts: str):
        if not label or is_generic_speaker(label) or is_clip_label(label) or is_hedged_label(label):
            return
        m = canonical_roster_name(label, roster)
        if m:
            out[m].append(_content_words(" ".join(t for t in texts if t)))

    for src in (extraction or {}, analysis or {}):
        for q in (src.get("high_value_quotes") or []) + (src.get("notable_quotes") or []):
            if isinstance(q, dict):
                add(q.get("speaker") or "", q.get("quote") or "", q.get("context") or "")
        for ca in src.get("companies_and_assets") or []:
            if isinstance(ca, dict):
                for kq in ca.get("key_quotes") or []:
                    if isinstance(kq, dict):
                        add(kq.get("speaker") or "", kq.get("quote") or "", str(ca.get("name") or ""))
        for key in _CLAIM_LISTS:
            for c in src.get(key) or []:
                if isinstance(c, dict):
                    add(c.get("speaker") or "", *(str(c.get(f) or "") for f in
                                                  ("claim", "prediction", "idea", "risk", "evidence")))
        for et in src.get("emerging_terms") or []:
            if isinstance(et, dict):
                add(et.get("speaker") or "", et.get("term") or "", et.get("speaker_quote") or "")
    return out


def _member_name_regex(member: str) -> "re.Pattern":
    names = {member, member.split()[-1]} | {a for a in _ROSTER_ALIASES.get(member, []) if len(a) >= 4}
    if member == "David Sacks" or member == "David Friedberg":
        names.discard("David")
    alts = sorted((re.escape(n) for n in names), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(alts) + r")(?:['’]s)?(?![A-Za-z])", re.IGNORECASE)


def enforce_named_prose(
    analysis: Dict[str, Any],
    podcast_name: str,
    *,
    extraction: Optional[Dict[str, Any]] = None,
    show_notes: str = "",
    min_overlap: int = 2,
    episode_ref: str = "",
    log_path=None,
) -> List[Dict[str, Any]]:
    """Replace a roster name in summary/key_takeaways/investment_thesis with 'one host' when no
    cued extraction item from that person supports the sentence. Edits in place; returns changes."""
    if not analysis or not is_host_panel_show(podcast_name):
        return []
    roster = episode_roster(podcast_name, show_notes)
    if extraction is None:
        try:
            extraction = json.loads(analysis.get("_extraction_json") or "{}")
        except Exception:
            extraction = {}
    cued = _cued_texts_by_member(extraction, analysis, roster)
    patterns = {m: _member_name_regex(m) for m in roster}
    changes: List[Dict[str, Any]] = []

    def fix_sentence(sent: str, field: str) -> str:
        words = _content_words(sent)
        for m, pat in patterns.items():
            if not pat.search(sent):
                continue
            # A clip / quoted-by label ("Dario Amodei (quoted by Jason Calacanis)") is the clip rule's job.
            if re.search(r"quoted by|\(clip\)", sent, re.IGNORECASE):
                continue
            support = max((len(words & w) for w in cued.get(m, [])), default=0)
            if support >= min_overlap:
                continue
            new = pat.sub("one host", sent)
            new = re.sub(r"\b([Oo])ne host\b(?:\s*(?:,|and)\s*one host\b)+",
                         lambda mm: "Two hosts" if mm.group(1) == "O" else "two hosts", new)
            if new[:8] == "one host" or new[:9] == "two hosts":
                new = new[:1].upper() + new[1:]    # "David Sacks and Jason ..." -> "Two hosts ...", not "two hosts"
            changes.append({"episode": episode_ref, "field": field, "speaker": m, "before": sent[:300]})
            sent = new
        return sent

    def fix_text(text: str, field: str) -> str:
        if not text:
            return text
        parts = re.split(r"(?<=[.!?])(\s+)", text)
        out = []
        for p in parts:
            if not p.isspace():
                p = fix_sentence(p, field)
                if p.startswith("one host"):
                    p = "One host" + p[8:]
            out.append(p)
        return "".join(out)

    if isinstance(analysis.get("summary"), str):
        analysis["summary"] = fix_text(analysis["summary"], "summary")
    if isinstance(analysis.get("investment_thesis"), str):
        analysis["investment_thesis"] = fix_text(analysis["investment_thesis"], "investment_thesis")
    kts = analysis.get("key_takeaways")
    if isinstance(kts, list):
        analysis["key_takeaways"] = [fix_text(k, f"key_takeaways[{i}]") if isinstance(k, str) else k
                                     for i, k in enumerate(kts)]
    for c in changes:
        print(f"    ↺ Named sentence not backed by a cued quote, name → 'one host': {c['field']}: {c['speaker']}", flush=True)
    if changes:
        try:
            if log_path is None:
                from workspace_paths import STATE_DIR
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                log_path = STATE_DIR / "speaker_cue_relabels.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                for c in changes:
                    f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), **c}) + "\n")
        except Exception as exc:
            print(f"    ⚠ Could not write speaker_cue_relabels log: {exc}", flush=True)
    return changes
