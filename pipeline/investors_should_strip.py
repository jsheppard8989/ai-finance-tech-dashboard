"""Oct 31 2026 (sweep_1031 R41 rev2): strip trailing 'Investors should...' filler sentences from Deep Dive
prose at export time, only for the exact sentences listed per card in r41_investors_should_rules.json.

Safety (per card, all-or-nothing): never blank a non-list field, never blank a ticker positioning (renders N/A),
never empty key_takeaways_detailed (the card's only takeaway), never touch a sentence inside an open quote,
and never touch quote fields. Idempotent."""
import json
import re
from pathlib import Path

RULES_PATH = Path(__file__).parent / "r41_investors_should_rules.json"
FIELDS = ("key_takeaway", "key_takeaways", "key_takeaways_detailed", "summary", "overview",
          "takeaway", "positioning_guidance", "investment_implications")
LEAD = "Investors should"
SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z“"\'(])')


def _norm(s):
    return " ".join(str(s).split())


def in_open_quote(prefix):
    if prefix.count("“") > prefix.count("”"):
        return True
    if prefix.count('"') % 2 == 1:
        return True
    m = None
    for m in re.finditer(r"(?:^|\s)'(?=[A-Z])", prefix):
        pass
    return bool(m and not re.search(r"[.!?,;:]'(\s|$)", prefix[m.end():]))


def strip_tail(text, allowed, canon=_norm):
    """Remove trailing 'Investors should' sentences whose (canonical) text is in `allowed`."""
    if not isinstance(text, str) or LEAD not in text:
        return text
    sents = SENT_SPLIT.split(text.strip())
    n = len(sents)
    while n and sents[n - 1].lstrip().startswith(LEAD):
        if in_open_quote(" ".join(sents[:n - 1])):
            break
        tail = " ".join(sents[n - 1:])
        if canon(tail) in allowed:
            return " ".join(sents[:n - 1]).strip()
        n -= 1
    return text


def load_rules(path=RULES_PATH):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("deep_dives", {})
    except Exception:
        return {}


def _card_edit(dd, allowed, canon):
    out = json.loads(json.dumps(dd))
    changed = False
    for f in FIELDS:
        v = out.get(f)
        if isinstance(v, str):
            nv = strip_tail(v, allowed, canon)
            if nv != v:
                if not nv.strip():
                    return None
                out[f], changed = nv, True
        elif isinstance(v, list):
            nl = []
            for it in v:
                ni = strip_tail(it, allowed, canon) if isinstance(it, str) else it
                changed |= ni != it
                if not (isinstance(ni, str) and not ni.strip()):
                    nl.append(ni)
            if v and not nl:
                return None
            out[f] = nl
    for t, ta in (out.get("ticker_analysis") or {}).items():
        if isinstance(ta, dict) and isinstance(ta.get("positioning"), str):
            nv = strip_tail(ta["positioning"], allowed, canon)
            if nv != ta["positioning"]:
                if not nv.strip():
                    return None
                ta["positioning"], changed = nv, True
    return out if changed else dd


def apply_investors_should_strip(deepdives, rules=None, canon=_norm):
    """deepdives: {id: card}. Returns (changed_cards, skipped_cards)."""
    rules = load_rules() if rules is None else rules
    if not isinstance(deepdives, dict):
        return 0, 0
    done = skipped = 0
    for k, dd in deepdives.items():
        tails = rules.get(str(k))
        if not tails or not isinstance(dd, dict):
            continue
        allowed = {canon(t) for t in tails}
        new = _card_edit(dd, allowed, canon)
        if new is None:
            skipped += 1
        elif new is not dd:
            deepdives[k] = new
            done += 1
    return done, skipped
