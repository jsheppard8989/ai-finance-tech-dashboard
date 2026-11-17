#!/usr/bin/env python3
"""
Speaker turns from YouTube auto-captions (G, Nov 15 2026 follow-up to PR #826).

Whisper transcripts have no speaker labels, so #826's cue check often has to fall back to
"one host". YouTube's auto-captions for the same episode mark every change of speaker with
">>". This module turns those captions into speaker turns and names a turn ONLY on solid
evidence from the episode itself:

1. directed question / hand-off: the turn right before it addresses one roster member
   ("Chamath, what do you think?", "Alex, I'll go to you first", "Salim?") and the next turn
   is that person's answer;
2. self-identification at the start of the turn ("I'm Salim Ismail ...", "this is Peter");
3. continuation: the same speaker carries on after a one-word interjection
   ("...which means the >> Yeah. >> margin compresses", or "... >> Sure. >> As I was saying").

Everything else stays unnamed ("one host"). A wrong name is worse than no name. Only names on
the show's fixed host roster (speaker_attribution.episode_roster) are ever assigned, so a clip
voice can never become a host, and the episode's DB guest/speaker list is never consulted.
A turn that follows a clip cue ("take a listen", "let's watch") is marked as a clip and is
never given a host name.

Turn names are then used by speaker_attribution to label quotes and claims: a quote is located
in the caption turns (word 3-gram alignment, captions and Whisper differ slightly) and takes
that turn's name. Each name assigned is logged with its evidence to
pipeline/state/speaker_turn_names.jsonl.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# VTT parsing
# ---------------------------------------------------------------------------

_TS = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d+)")


def _secs(ts: str) -> float:
    m = _TS.search(ts or "")
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / (10 ** len(ms))


def parse_youtube_vtt(vtt_text: str) -> List[Tuple[float, str]]:
    """YouTube auto-caption VTT -> [(start_seconds, new caption text)], de-duplicated.

    Auto-captions "roll": each cue repeats the previous line and adds a new one carrying
    inline word timestamps (<00:00:01.920><c> word</c>). Only those new lines are kept.
    Plain (non-rolling) VTT files are handled too: if no cue has inline timestamps, every
    cue line is kept once, in order.
    """
    text = (vtt_text or "").replace("\r\n", "\n")
    rolling = "<c>" in text or re.search(r"<\d\d:\d\d:\d\d\.\d+>", text) is not None
    out: List[Tuple[float, str]] = []
    last = None
    start = None
    # Line by line: a cue's first line can be a lone space, which a blank-line split would
    # treat as the end of the cue (that dropped the opening words of the first cue).
    for ln in text.split("\n"):
        if "-->" in ln:
            start = _secs(ln.split("-->")[0])
            continue
        if start is None or not ln.strip():
            continue
        if rolling and not ("<c>" in ln or re.search(r"<\d\d:\d\d:\d\d\.\d+>", ln)):
            continue
        txt = html.unescape(re.sub(r"<[^>]+>", "", ln)).strip()
        if not txt or (not rolling and txt == last):
            continue
        out.append((start, txt))
        last = txt
    return out


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    index: int
    start: float
    text: str
    name: Optional[str] = None
    evidence: str = ""          # directed_question | self_identification | continuation
    cue: str = ""               # the caption words that are the evidence
    clip: bool = False
    clip_cue: str = ""
    name_words: int = 0         # the name covers this many words from the turn start

    @property
    def stamp(self) -> str:
        s = int(self.start)
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def split_turns(lines: Sequence[Tuple[float, str]]) -> List[Turn]:
    """Join caption lines and split at '>>' (YouTube's change-of-speaker marker)."""
    turns: List[Turn] = []
    cur_text: List[str] = []
    cur_start = lines[0][0] if lines else 0.0
    for start, txt in lines:
        parts = txt.split(">>")
        for j, p in enumerate(parts):
            if j > 0:  # a marker: close the current turn
                body = " ".join(cur_text).strip()
                if body:
                    turns.append(Turn(len(turns), cur_start, body))
                cur_text, cur_start = [], start
            if p.strip():
                cur_text.append(p.strip())
    body = " ".join(cur_text).strip()
    if body:
        turns.append(Turn(len(turns), cur_start, body))
    return turns


def count_markers(vtt_text: str) -> int:
    return sum(t.count(">>") for _, t in parse_youtube_vtt(vtt_text))


# ---------------------------------------------------------------------------
# Name matching (roster only)
# ---------------------------------------------------------------------------

# Spellings seen in YouTube auto-captions (Nov 15 2026: eps 679 / 680), on top of the
# Whisper spellings in speaker_attribution._ROSTER_ALIASES.
CAPTION_ALIASES: Dict[str, List[str]] = {
    "Chamath Palihapitiya": ["chimath", "chamat", "shamath", "jamath"],
    "David Sacks": ["sax", "saxs", "sachs", "saks"],
    "David Friedberg": ["freedberg", "freeberg", "freidberg"],
    "Jason Calacanis": ["jcal", "j-cal", "j cal"],
    "Emad Mostaque": ["imad", "emad", "iman", "ahmad", "imod"],
    "Salim Ismail": ["saleem", "selim", "salim"],
    "Alex Wissner-Gross": ["alex"],
    "Peter Diamandis": ["peter"],
    "Dave Blundin": ["dave"],
}


def _name_tokens(roster: Sequence[str]) -> Dict[str, List[str]]:
    """member -> lower-case tokens that name them; tokens shared by two members are dropped."""
    from speaker_attribution import _ROSTER_ALIASES
    raw: Dict[str, set] = {}
    for m in roster:
        toks = set(a.lower() for a in _ROSTER_ALIASES.get(m, []))
        toks |= set(a.lower() for a in CAPTION_ALIASES.get(m, []))
        toks.add(m.split()[-1].lower())
        toks.add(m.split()[0].lower())
        raw[m] = {t for t in toks if len(t) >= 3}
    counts: Dict[str, int] = defaultdict(int)
    for toks in raw.values():
        for t in toks:
            counts[t] += 1
    return {m: sorted((t for t in toks if counts[t] == 1), key=len, reverse=True) for m, toks in raw.items()}


def _member_alt(tokens: List[str]) -> str:
    return "(?:" + "|".join(re.escape(t) for t in tokens) + ")"


# Hand-off / directed-question shapes. NAME is filled per roster member.
_HANDOFF_BEFORE = (
    r"(?:what do you think|what(?:'s| is) your take|your take|your thoughts|any thoughts|thoughts|"
    r"what say you|over to you|go ahead|you first|jump in|weigh in|respond to that|react to that|take it away|"
    r"you're up|how about you|what about you|your view|what do you make of (?:it|this|that))"
)
_HANDOFF_VERB = (
    r"(?:go to|going to go to|over to|turn to|start with|hand it to|kick it to|throw it to|pass it to|toss it to|"
    r"hear from|bring in|go with|come to|coming to)"
)
# Words that open a sentence before a vocative name ("So, Alex, ...", "You know, Alex, ...").
_DISCOURSE = r"(?:so|okay|ok|all right|alright|well|now|yeah|yes|right|and|but|you know|i mean|look|listen|hey|gentlemen|uh|um|agreed)"
# After "Name," these open a REPLY to the previous speaker, not a hand-off.
_REPLY_OPENERS = re.compile(
    r"^\W*(?:i agree|i disagree|i think|i hear|i love|i like|that's|thats|you're right|youre right|exactly|"
    r"great point|good point|totally|thank|thanks|amen|i mean|fair|true|correct|well said|no\b|yes\b|yeah\b|"
    r"you're absolutely|you nailed|you said|as you said|to your point)", re.I)
# Signals that the speaker is handing someone the floor.
_HANDOFF_SIGNAL = re.compile(
    r"\?|\b(?:what do you think|your take|your thoughts|any thoughts|you guys think|what say you|over to you|"
    r"to you first|you first|go ahead|close us out|kick us off|start us off|take it away|you're up|weigh in|"
    r"jump in|i'd love to hear|love to hear|want to hear|what's your|what is your|what are your|how do you|"
    r"do you think|do you buy|what would you|would you|you get first|first crack|first choice)\b", re.I)
_SECOND_PERSON = re.compile(r"\b(?:you|your|you're|you've|you'd)\b", re.I)
_THIRD_PERSON_AFTER = r"(?:'s|’s|\s+(?:and|said|says|mentioned|told|was|is|has|had|thinks|thought|wrote|tweeted|posted|just|did|does|would|will|can|makes|made))\b"
_PREP_BEFORE = re.compile(
    r"(?:\b(?:with|to|about|from|like|and|than|for|of|at|by|as|said|says|that|thanks|thank you|agree with|"
    r"me and|i and|ask|asked|told|tell|amen|sorry)\s*,?\s*)$", re.I)

MAX_WORDS_AFTER_ADDRESS = 15        # address this close to the end of the turn: the next turn answers
MAX_WORDS_AFTER_QUESTION = 60       # ...or the name, then a question to them, then at most
MAX_WORDS_AFTER_QUESTION_MARK = 20  # this many words before the turn ends
MAX_WORDS_ONE_SENTENCE = 30         # ...or one unfinished sentence to them ("Ahmad, it sounds like your concern is")


def _strip_tags(text: str) -> str:
    return re.sub(r"\[(?:laughter|music|applause|__)\]", " ", text or "", flags=re.I).strip()


def _gate(after: str, allow_bare: bool = True) -> bool:
    """``after`` = the turn's words after the addressed name. True when that reads as handing them the
    floor right at the end of the turn (so the NEXT turn is their answer), not as an answer already
    included in this turn (a missed '>>')."""
    after = _strip_tags(after).lstrip(" ,")
    if not after or re.fullmatch(r"[.?!\s]*", after):
        return allow_bare                               # "Agreed. Salim." / "Sacks?"
    if not after.startswith("?") and _REPLY_OPENERS.match(after):
        return False                                    # "Sacks, I agree ..." is a reply
    words = after.split()
    n = len(words)
    signal = bool(_HANDOFF_SIGNAL.search(after))
    if n <= MAX_WORDS_AFTER_ADDRESS and signal:
        return True
    # name ... question?  then a short tail
    for k, w in enumerate(words):
        if w.endswith("?"):
            if k <= MAX_WORDS_AFTER_QUESTION and n - 1 - k <= MAX_WORDS_AFTER_QUESTION_MARK:
                return True
            break
    # a run of questions to them that ends the turn ("Alex, I'm going to you first. Is this ...? Or ...?
    # What are your thoughts here?") - no answer sentence after the last question
    sentences = [x for x in re.split(r"(?<=[.?!])\s+", after.strip()) if x.strip()]
    if n <= MAX_WORDS_AFTER_QUESTION and sentences and (
            sentences[-1].rstrip().endswith("?") or _HANDOFF_SIGNAL.search(sentences[-1])):
        return True
    # one sentence, still addressed to them, that the next '>>' cuts off or ends
    body = after.rstrip(" .?!")
    if n <= MAX_WORDS_ONE_SENTENCE and not re.search(r"[.!?]\s", body) and (signal or _SECOND_PERSON.search(body)):
        return True
    return False


def _next_to_other_member(t: str, start: int, end: int, member: str, alts: Dict[str, str]) -> bool:
    """True if another roster member's name sits right beside this one ("Sacks, Chamath," / "Alex and Salim")."""
    for m, alt in alts.items():
        if m == member:
            continue
        nb = r"(?<![a-z0-9'])" + alt + r"(?![a-z0-9'-])"
        if re.search(nb + r"\s*(?:,|and|&|or)\s*$", t[max(0, start - 30):start]):
            return True
        if re.match(r"\s*(?:,|and|&|or)\s*" + nb, t[end:end + 30]):
            return True
    return False


def _addressed_in(tail: str, tokens_by_member: Dict[str, List[str]],
                  all_tokens: Optional[Dict[str, List[str]]] = None) -> List[Tuple[str, str, int]]:
    """Roster members handed the floor at the end of ``tail`` -> [(member, cue words, words after the name)]."""
    t = _strip_tags(tail).lower()
    raw = _strip_tags(tail)
    hits: List[Tuple[str, str, int]] = []
    all_alts = {m: _member_alt(tk) for m, tk in (all_tokens or tokens_by_member).items() if tk}
    for m, toks in tokens_by_member.items():
        if not toks:
            continue
        N = _member_alt(toks)
        nb = r"(?<![a-z0-9'])" + N + r"(?![a-z0-9'-])"
        pats = [
            # vocative at the start of a sentence: "So, Alex, I'm going to you first." / "Salim?" / "Agreed. Salim."
            r"(?:^|[.?!]\s*|\b" + _DISCOURSE + r"\s*,?\s+)" + nb + r"\s*(?:[,?]|[.!]?\s*$)",
            # (A mid-sentence vocative, "a fifth question to yours, Sax, which is why now?", is NOT used:
            # on ep 680 Friedberg answered that one.)
            # "what do you think, Sacks" / "any thoughts there, Chamath"
            r"\b" + _HANDOFF_BEFORE + r"(?:\s+\w+){0,2}\s*,?\s*" + nb + r"(?!" + _THIRD_PERSON_AFTER + r")",
            # "I'll go to Alex" / "let's hear from Emad"
            r"\b" + _HANDOFF_VERB + r"\s+(?:you\s*,?\s*)?" + nb + r"(?!" + _THIRD_PERSON_AFTER + r")",
            # "... Sacks?" at the very end of the turn
            nb + r"\s*\?\s*$",
        ]
        best = None
        for pi, p in enumerate(pats):
            for mm in re.finditer(p, t):
                name_m = None
                for nm in re.finditer(nb, t[mm.start():mm.end()]):
                    name_m = nm
                if name_m is None:
                    continue
                name_start = mm.start() + name_m.start()
                name_end = mm.start() + name_m.end()
                if _PREP_BEFORE.search(t[:name_start]):
                    continue
                # "Sacks, Chamath, what do you guys think?": two people asked, so nobody can be named.
                if _next_to_other_member(t, name_start, name_end, m, all_alts):
                    continue
                after = raw[name_end:]
                # A bare name at the end counts only as its own sentence ("Agreed. Salim."), never
                # mid-sentence ("It certainly would be hilarious, Peter, >> if Jensen ...").
                if not _gate(after, allow_bare=(pi in (0, 3))):
                    continue
                if best is None or name_start > best[0]:
                    best = (name_start, raw[max(0, name_start - 60):].strip(), len(after.split()))
        if best:
            hits.append((m, best[1], best[2]))
    return hits


def _handoff_ok(tail: str, n_after: int) -> bool:
    """Kept for callers: the gate already ran in _addressed_in."""
    return True


_CLIP_CUES = re.compile(
    r"\b(?:take a (?:quick )?(?:listen|look)|let's (?:take a )?(?:listen|watch|look|play|hear)|let's roll|roll (?:the|that) "
    r"(?:clip|tape|video)|play (?:the|that|this) (?:clip|video|tape)|here's the clip|watch this|listen to this|"
    r"quick look at this video|look at (?:this|a quick) video|check out this clip|take a look here|here he is|"
    r"here she is|let's go to the (?:clip|tape)|show a (?:short )?clip|this video)\b",
    re.I,
)
_SELF_ID = re.compile(r"^(?:\W*\w+\W+){0,6}?(?:i'm|i am|this is|my name is|it's)\s+", re.I)
_BACKCHANNEL = {
    "yeah", "yes", "yep", "right", "sure", "exactly", "totally", "true", "mhm", "mm", "uh", "um", "okay", "ok",
    "wow", "absolutely", "correct", "100", "agreed", "agree", "definitely", "indeed", "yup", "no", "huh", "oh",
    "ha", "haha", "laughter", "[laughter]", "great", "good", "nice", "interesting", "totally.", "100%",
}
_CONTINUE_START = re.compile(r"^\W*(?:as i was saying|anyway,? as i was saying|to finish (?:my|the) (?:point|thought)|"
                             r"let me finish|my point (?:was|is)|the point i was making)\b", re.I)


def _is_backchannel(text: str) -> bool:
    words = [w.strip(".,!?;:\"'").lower() for w in text.split()]
    words = [w for w in words if w]
    return 0 < len(words) <= 3 and all(w in _BACKCHANNEL for w in words)


def _tail(text: str, n_words: int = 60) -> str:
    w = text.split()
    return " ".join(w[-n_words:])


CLIP_HOST_TAIL_MIN_WORDS = 150   # a clip turn this long also holds the host talking after the clip
MAX_NAMED_WORDS = 600   # never carry a name further than this into one caption turn


def _name_cut(text: str, toks: Dict[str, List[str]], exclude: str) -> int:
    """How many words of a named turn the name covers.

    Auto-captions sometimes miss a '>>'. Two signs of a missed change stop the name early:
    - a sentence that hands the floor to another roster member with more talk after it;
    - a sentence that starts lower-case after a full stop ("...in a massive way. just taking a
      broader view..."): the caption punctuation restarting mid-line, which in eps 679/680 lined
      up with real speaker changes (31:19, 32:44 on All-In; 15:52, 64:45 on Moonshots).
    """
    words = text.split()
    sentences = [x for x in re.split(r"(?<=[.?!])\s+", text) if x]
    others = {m: t for m, t in toks.items() if m != exclude}
    pos = 0
    for k, sent in enumerate(sentences):
        n = len(sent.split())
        if k > 0 and pos >= 3 and re.match(r"[a-z]", sent) and not re.match(r"i\b|i'", sent):
            return min(pos, MAX_NAMED_WORDS)
        pos += n
        if len(words) - pos > MAX_WORDS_AFTER_ADDRESS and _addressed_in(sent, others, toks):
            return min(pos, MAX_NAMED_WORDS)
    return min(len(words), MAX_NAMED_WORDS)


def assign_turn_names(turns: List[Turn], roster: Sequence[str]) -> List[Turn]:
    """Name turns in place from directed questions, self-identification and continuations."""
    toks = _name_tokens(roster)
    for i, t in enumerate(turns):
        prev = turns[i - 1] if i > 0 else None
        # Clip: the previous turn ends by playing a clip.
        if prev is not None:
            cm = None
            for cm in _CLIP_CUES.finditer(_tail(prev.text, 30)):
                pass
            if cm is not None:
                t.clip, t.clip_cue = True, cm.group(0)
                continue
        candidates: List[Tuple[str, str, str]] = []
        # 1. Directed question / hand-off at the end of the previous turn.
        split_sentence = bool(prev is not None and prev.text.rstrip()[-1:] not in ".?!" and t.text[:1].islower())
        # A clip turn can only hand off when it is long enough to hold host talk after the clip
        # (captions often miss the '>>' where the host comes back: ep 679 7:43 Fox clip -> "So, Alex,
        # I'm going to you first ... What are your thoughts"; 58:07 Hassabis clip -> "Salim, your thoughts?").
        prev_can_hand_off = prev is not None and (not prev.clip or len(prev.text.split()) >= CLIP_HOST_TAIL_MIN_WORDS)
        if prev_can_hand_off and not split_sentence:
            tail = _strip_tags(_tail(prev.text, 100))
            addressed = _addressed_in(tail, toks)
            names = {m for m, _, _ in addressed}
            if len(names) == 1:
                m, cue, n_after = addressed[-1]
                if m != prev.name and _handoff_ok(tail, n_after):
                    candidates.append((m, "directed_question", cue))
        # 2. Self-identification at the start of this turn.
        head = " ".join(t.text.split()[:14]).lower()
        sm = _SELF_ID.match(head)
        if sm:
            rest = head[sm.end():]
            for m, mt in toks.items():
                if mt and re.match(_member_alt(mt) + r"(?![a-z0-9'])(?!'s)", rest):
                    candidates.append((m, "self_identification", " ".join(t.text.split()[:14])))
        # 3. Continuation across a one-word interjection.
        if i >= 2 and turns[i - 2].name and not turns[i - 2].clip and _is_backchannel(prev.text):
            before = turns[i - 2].text.rstrip()
            mid_sentence = before and before[-1] not in ".?!\"" and t.text[:1].islower()
            if mid_sentence or _CONTINUE_START.match(t.text):
                candidates.append((turns[i - 2].name, "continuation",
                                   f"{_tail(before, 8)} >> {prev.text} >> {' '.join(t.text.split()[:8])}"))
        names = {c[0] for c in candidates}
        if len(names) != 1:
            continue
        name, ev, cue = candidates[0]
        # Guard: a turn that hands the floor to this same person is not that person talking
        # (e.g. "Alex, I mean Salim, they were..." after a missed marker).
        if _addressed_in(t.text, {name: toks.get(name, [])}):
            continue
        t.name, t.evidence, t.cue = name, ev, cue
        t.name_words = _name_cut(t.text, toks, name)
    return turns


# ---------------------------------------------------------------------------
# Locating a (Whisper) quote in the caption turns
# ---------------------------------------------------------------------------

def _norm_words(text: str) -> List[str]:
    s = (text or "").lower()
    s = re.sub(r"[‘’“”\"']", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return s.split()


@dataclass
class TurnMap:
    turns: List[Turn]
    roster: List[str]
    source: str = ""
    words: List[str] = field(default_factory=list)
    word_turn: List[int] = field(default_factory=list)
    _tri: Dict[Tuple[str, str, str], List[int]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.words:
            for t in self.turns:
                for w in _norm_words(t.text):
                    self.words.append(w)
                    self.word_turn.append(t.index)
        self._first_word: Dict[int, int] = {}
        for k, ti in enumerate(self.word_turn):
            self._first_word.setdefault(ti, k)
        tri: Dict[Tuple[str, str, str], List[int]] = defaultdict(list)
        for i in range(len(self.words) - 2):
            tri[(self.words[i], self.words[i + 1], self.words[i + 2])].append(i)
        self._tri = dict(tri)

    @property
    def named(self) -> List[Turn]:
        return [t for t in self.turns if t.name]

    def locate(self, quote: str, min_share: float = 0.85) -> Tuple[Optional[Turn], str]:
        """(turn, why). turn is None when the quote can't be placed in ONE caption turn."""
        d = self.locate_detail(quote, min_share)
        return d["turn"], d["why"]

    def speaker_for(self, quote: str) -> Dict:
        """Who said ``quote`` according to the caption turns.

        {"status": "named", "name", "turn"} - inside the named part of a named turn
        {"status": "clip", "turn"}          - inside a turn that follows a clip cue
        {"status": "unnamed", "turn"}       - inside a turn with no solid evidence
        {"status": "not_located", "why"}    - can't place it in one turn (caller falls back)
        """
        d = self.locate_detail(quote)
        t = d["turn"]
        if t is None:
            return {"status": "not_located", "why": d["why"]}
        if t.clip:
            return {"status": "clip", "turn": t}
        if t.name and d["word_in_turn"] + d["n_words"] <= t.name_words + 3:
            return {"status": "named", "name": t.name, "turn": t}
        return {"status": "unnamed", "turn": t}

    def locate_detail(self, quote: str, min_share: float = 0.85) -> Dict:
        out = {"turn": None, "why": "", "word_in_turn": 0, "n_words": 0}
        q = _norm_words(quote)
        if len(q) < 5:
            return {**out, "why": "too_short"}
        votes: Dict[int, int] = defaultdict(int)
        for i in range(len(q) - 2):
            for p in self._tri.get((q[i], q[i + 1], q[i + 2]), ())[:50]:
                votes[p - i] += 1
        if not votes:
            return {**out, "why": "not_found"}
        # Group nearby offsets (captions and Whisper drop/insert a few words).
        scored = []
        for off in votes:
            scored.append((sum(votes.get(off + d, 0) for d in range(-4, 5)), off))
        scored.sort(reverse=True)
        best_score, best_off = scored[0]
        need = max(2, int(0.3 * (len(q) - 2)))
        if best_score < need:
            return {**out, "why": "weak_match"}
        # A second, far-away placement nearly as good = repeated phrase; don't guess. One exception:
        # the words occur in exactly one clip turn and elsewhere in host turns (a host reading the quote
        # out before or after the clip plays, ep 679 39:08 / 40:20 Christiano). The words are the clip's,
        # so place them there: the label can then only be the clip voice or "a clip", never a host.
        rivals = [off for sc, off in scored[1:] if abs(off - best_off) > 30 and sc >= 0.8 * best_score]
        if rivals:
            placements = [best_off] + rivals
            spans = [self._span_turn(o, len(q)) for o in placements]
            if any(sp is None for sp in spans) or len({sp[0] for sp in spans}) > 1:
                clip_offs = [o for o, sp in zip(placements, spans) if sp is not None and self.turns[sp[0]].clip]
                if len(clip_offs) == 1 and all(sp is not None for sp in spans):
                    best_off = clip_offs[0]
                else:
                    return {**out, "why": "ambiguous_match"}
        hit = self._span_turn(best_off, len(q), min_share)
        if hit is None:
            return {**out, "why": "spans_turns"}
        ti = hit[0]
        first = self._first_word.get(ti, 0)
        return {"turn": self.turns[ti], "why": "ok", "word_in_turn": max(0, best_off - first),
                "n_words": len(q)}

    def _span_turn(self, off: int, n: int, min_share: float = 0.85):
        lo, hi = max(0, off), min(len(self.words), off + n)
        if hi <= lo:
            return None
        counts: Dict[int, int] = defaultdict(int)
        for k in range(lo, hi):
            counts[self.word_turn[k]] += 1
        ti, c = max(counts.items(), key=lambda kv: kv[1])
        if c / (hi - lo) < min_share:
            return None
        return ti, c / (hi - lo)


def build_turn_map(vtt_text: str, roster: Sequence[str], source: str = "") -> Optional[TurnMap]:
    lines = parse_youtube_vtt(vtt_text)
    if not lines or not any(">>" in t for _, t in lines):
        return None
    turns = assign_turn_names(split_turns(lines), list(roster))
    return TurnMap(turns=turns, roster=list(roster), source=source)


def caption_overlap(tm: TurnMap, transcript: str, samples: int = 40) -> float:
    """Share of sampled transcript passages found in the captions (guards against a wrong video)."""
    w = _norm_words(transcript)
    if len(w) < 200:
        return 0.0
    step = max(1, (len(w) - 12) // samples)
    hits = tot = 0
    for i in range(0, len(w) - 12, step):
        tot += 1
        t, _ = tm.locate(" ".join(w[i:i + 12]), min_share=0.0)
        if t is not None:
            hits += 1
    return hits / tot if tot else 0.0


# ---------------------------------------------------------------------------
# Finding / fetching the captions for a transcript
# ---------------------------------------------------------------------------

CAPTION_SUFFIX = ".yt.vtt"
MIN_CAPTION_OVERLAP = 0.5


def caption_path_for(transcript_path: Path) -> Path:
    p = Path(transcript_path)
    return p.with_name(p.stem + CAPTION_SUFFIX)


def _yt_dlp() -> Optional[str]:
    exe = os.environ.get("YT_DLP_BIN") or shutil.which("yt-dlp")
    return exe if exe and Path(exe).exists() else None


def _warn_caption_turns(reason: str) -> None:
    """One greppable line when caption speaker turns can't be used (Nov 16 2026, Tony: #834 follow-up)."""
    print(f"    WARN caption turns: {reason}", flush=True)


def fetch_youtube_captions(transcript_path: Path, podcast_name: str, episode_title: str,
                           video_id: str = "", timeout: int = 90) -> Optional[Path]:
    """Download English auto-captions next to the transcript (<stem>.yt.vtt). Returns the path or None.

    Uses the sidecar's youtube_video_id when given, else the top YouTube search hit whose title
    matches the episode title (ratio >= 0.6). Needs yt-dlp; never raises. The caller still checks
    that the captions match the transcript text (caption_overlap) before trusting them.
    """
    dest = caption_path_for(transcript_path)
    if dest.exists():
        return dest
    if os.environ.get("YT_CAPTIONS", "1") == "0":
        _warn_caption_turns("captions disabled (YT_CAPTIONS=0)")
        return None
    exe = _yt_dlp()
    if not exe:
        _warn_caption_turns("yt-dlp missing (set YT_DLP_BIN or install yt-dlp)")
        return None
    try:
        vid = (video_id or "").strip()
        if not vid:
            q = f"ytsearch5:{podcast_name.split(' with ')[0]} {episode_title}"
            r = subprocess.run([exe, "--flat-playlist", "--print", "%(id)s\t%(title)s", q],
                               capture_output=True, text=True, timeout=timeout)
            best = (0.0, "")
            for line in r.stdout.splitlines():
                if "\t" not in line:
                    continue
                i, title = line.split("\t", 1)
                ratio = SequenceMatcher(None, title.lower(), episode_title.lower()).ratio()
                if ratio > best[0]:
                    best = (ratio, i)
            if best[0] < 0.6:
                _warn_caption_turns(f"no captions: no YouTube video matches the episode title "
                                    f"(best title match {best[0]:.0%}) for {episode_title[:80]!r}")
                return None
            vid = best[1]
        tmp = dest.with_name(dest.stem + ".tmp")
        r = subprocess.run([exe, "--skip-download", "--write-auto-subs", "--sub-langs", "en-orig,en",
                        "--sub-format", "vtt", "-o", str(tmp) + ".%(ext)s",
                        f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True, timeout=timeout)
        for cand in (Path(str(tmp) + ".en-orig.vtt"), Path(str(tmp) + ".en.vtt")):
            if cand.exists():
                cand.replace(dest)
                break
        for leftover in dest.parent.glob(tmp.name + ".*"):
            leftover.unlink(missing_ok=True)
        if dest.exists():
            return dest
        if r.returncode != 0:
            err = (r.stderr or "").strip().splitlines()
            _warn_caption_turns(f"fetch failed: yt-dlp exit {r.returncode} for video {vid}"
                                + (f": {err[-1][:160]}" if err else ""))
        else:
            _warn_caption_turns(f"no captions: no English captions for video {vid}")
        return None
    except Exception as exc:  # captions are optional
        _warn_caption_turns(f"fetch failed: {exc}")
        return None


def load_turn_map_for_transcript(
    transcript_path: Path,
    transcript_text: str,
    podcast_name: str,
    *,
    show_notes: str = "",
    episode_title: str = "",
    video_id: str = "",
    fetch: bool = True,
) -> Optional[TurnMap]:
    """Turn map for a panel-show episode, or None (non-panel show, no captions, wrong video)."""
    from speaker_attribution import episode_roster, is_host_panel_show
    if not is_host_panel_show(podcast_name):
        return None
    path = caption_path_for(transcript_path)
    if not path.exists() and fetch:
        path = fetch_youtube_captions(transcript_path, podcast_name, episode_title, video_id) or path
        if not path.exists():
            return None  # fetch_youtube_captions already printed the WARN line
    if not path.exists():
        _warn_caption_turns(f"no captions: {path.name} not found (fetch off)")
        return None
    try:
        tm = build_turn_map(path.read_text(encoding="utf-8", errors="ignore"),
                            episode_roster(podcast_name, show_notes), source=str(path))
    except Exception as exc:
        _warn_caption_turns(f"caption file unreadable: {exc}")
        return None
    if tm is None:
        print("    ⚠ Captions have no '>>' speaker markers; speaker turns not used", flush=True)
        return None
    ov = caption_overlap(tm, transcript_text)
    if ov < MIN_CAPTION_OVERLAP:
        print(f"    ⚠ Captions don't match this transcript ({ov:.0%} overlap); speaker turns not used", flush=True)
        return None
    print(f"    ✓ Caption speaker turns: {len(tm.turns)} turns, {len(tm.named)} named "
          f"({ov:.0%} text overlap, {path.name})", flush=True)
    return tm


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_turn_names(entries: List[Dict], log_path=None) -> None:
    if not entries:
        return
    try:
        if log_path is None:
            from workspace_paths import STATE_DIR
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            log_path = STATE_DIR / "speaker_turn_names.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), **e}) + "\n")
    except Exception as exc:  # logging must never break the pipeline
        print(f"    ⚠ Could not write speaker_turn_names log: {exc}", flush=True)
