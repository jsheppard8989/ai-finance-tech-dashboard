#!/usr/bin/env python3
"""
Standalone data export script for website updates.
Called by cron job for midday price refreshes.
"""

import re
import sys
from pathlib import Path
from datetime import datetime
import copy
import json
import sqlite3

# Add pipeline directory to path
sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db
from site_text_sanitize import apply_style_gate, report_style_gate_misses, sanitize_public_text, strip_cjk_public_text
from extract_guests import load_overrides
from workspace_paths import (
    DB_PATH,
    PIPELINE_DIR,
    SITE_DATA_DIR,
    SITE_DIR,
    STATE_DIR,
    WHISPER_QUEUE_DIR,
    WORKSPACE_ROOT,
)

SITE_ROOT = SITE_DIR


def bump_data_js_cache_in_site_html() -> None:
    """Keep data.js cache-buster in sync across all site/*.html that reference it."""
    cache_ver = int(datetime.now().timestamp())
    pat = re.compile(r"\./data/data\.js(\?v=\d+)?")

    def _repl(_m) -> str:
        return f"./data/data.js?v={cache_ver}"

    for html_path in sorted(SITE_ROOT.glob("*.html")):
        try:
            text = html_path.read_text(encoding="utf-8")
        except OSError:
            continue
        new_text = pat.sub(_repl, text)
        if new_text != text:
            html_path.write_text(new_text, encoding="utf-8")
            print(f"  ✓ Bumped data.js cache in {html_path.name} → v={cache_ver}")


def _refresh_pipeline_tracker() -> None:
    """
    Keep pipeline tracker state fresh before exporting pipeline_state.json.
    """
    try:
        from pipeline_tracker import PodcastPipelineTracker
        tracker = PodcastPipelineTracker()
        tracker.scan_pipeline()
    except Exception as e:
        print(f"  ⚠ Could not refresh pipeline tracker before export: {e}")


def _count_podcasts_analyzed_today() -> int:
    """
    Return count of podcast_episodes rows created today (local date).
    Used for status.json last_steps so notifications are per-run/day, not lifetime totals.
    """
    if not DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM podcast_episodes
            WHERE date(created_at, 'localtime') = date('now', 'localtime')
            """
        )
        n = int(cursor.fetchone()[0] or 0)
        conn.close()
        return n
    except Exception:
        return 0


SUMMARY_OVERRIDES_PATH = Path(__file__).parent / "summary_overrides.json"




def _replace_text(value, replacements):
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_replace_text(v, replacements) for v in value]
    return value


def _load_override_rules():
    try:
        return json.loads(SUMMARY_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


TITLE_FIELDS = ("episode_title", "title", "insight_title")


def _replace_all_strings(value, replacements, skip_keys=()):
    """Recursively apply replacements to every string in value (dict keys in skip_keys untouched)."""
    if isinstance(value, str):
        return _replace_text(value, replacements)
    if isinstance(value, list):
        return [_replace_all_strings(v, replacements, skip_keys) for v in value]
    if isinstance(value, dict):
        return {k: (v if k in skip_keys else _replace_all_strings(v, replacements, skip_keys))
                for k, v in value.items()}
    return value


def _drop_tickers(value, drop):
    drop = {d.upper() for d in drop}
    if isinstance(value, list):
        return [t for t in value if str(t).upper() not in drop]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, list):
            return json.dumps([t for t in parsed if str(t).upper() not in drop])
    return value


def _drop_ticker_analysis(value, drop):
    """Remove dropped symbols from a Deep Dive ticker_analysis dict (or its JSON string)."""
    drop = {d.upper() for d in drop}
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if str(k).upper() not in drop}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, dict):
            return json.dumps({k: v for k, v in parsed.items() if str(k).upper() not in drop})
    return value


def _normalize_tickers_mentioned(obj):
    """Oct 27 2026: every exported insight's tickers_mentioned is a real list.

    mainContent insights came out of the DB as a JSON string ('["NVDA", ...]') while archive
    insights were parsed, so the same card had two shapes in data.js. Parse JSON-string values
    (non-JSON strings split on commas; blank -> []). In place; idempotent. Returns the count fixed.
    """
    fixed = 0

    def norm(v):
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        return [t.strip() for t in s.split(",") if t.strip()]

    def walk(o):
        nonlocal fixed
        if isinstance(o, dict):
            if isinstance(o.get("tickers_mentioned"), str):
                o["tickers_mentioned"] = norm(o["tickers_mentioned"])
                fixed += 1
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return fixed


def _rename_map(renames):
    """Build old->new map; keys compared case-insensitively on apply."""
    out = {}
    for pair in renames or []:
        if not pair or len(pair) < 2:
            continue
        old, new = pair[0], pair[1]
        if old is None or new is None:
            continue
        out[str(old).upper()] = str(new)
    return out


def _rename_tickers(value, renames):
    """Rename symbols in a tickers list (or JSON list string). Drops dupes after rename."""
    rmap = _rename_map(renames)
    if not rmap:
        return value

    def remap_list(items):
        seen = set()
        out = []
        for t in items:
            key = str(t).upper()
            newt = rmap.get(key, t)
            nkey = str(newt).upper()
            if nkey in seen:
                continue
            seen.add(nkey)
            out.append(newt)
        return out

    if isinstance(value, list):
        return remap_list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, list):
            return json.dumps(remap_list(parsed))
    return value


def _rename_ticker_analysis(value, renames):
    """Rename keys in a Deep Dive ticker_analysis dict (or JSON string)."""
    rmap = _rename_map(renames)
    if not rmap:
        return value

    def remap_dict(d):
        out = {}
        for k, v in d.items():
            nk = rmap.get(str(k).upper(), k)
            if nk in out and str(k).upper() in rmap:
                continue  # keep first if collision
            out[nk] = v
        return out

    if isinstance(value, dict):
        return remap_dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, dict):
            return json.dumps(remap_dict(parsed))
    return value


def _add_key_tickers(value, add):
    """Append symbols to a key_tickers list (or JSON list string) if missing. Idempotent."""
    add = [str(a) for a in (add or []) if a]
    if not add:
        return value

    def merge(items):
        have = {str(t).upper() for t in items}
        return list(items) + [a for a in add if a.upper() not in have]

    if isinstance(value, list):
        return merge(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, list):
            return json.dumps(merge(parsed))
    return value


def _apply_ticker_fixes_to_record(o, drop=None, renames=None):
    drop = drop or []
    renames = renames or []
    if renames:
        for k in ("tickers_mentioned", "key_tickers"):
            if k in o:
                o[k] = _rename_tickers(o[k], renames)
        if "ticker_analysis" in o:
            o["ticker_analysis"] = _rename_ticker_analysis(o["ticker_analysis"], renames)
    if drop:
        for k in ("tickers_mentioned", "key_tickers"):
            if k in o:
                o[k] = _drop_tickers(o[k], drop)
        if "ticker_analysis" in o:
            o["ticker_analysis"] = _drop_ticker_analysis(o["ticker_analysis"], drop)


def _apply_summary_overrides(obj):
    """Apply pipeline/summary_overrides.json text fixes (in place).

    - 'summaries' rules: for any record whose episode_title/title/insight_title contains
      the rule's 'episode_title', apply 'replacements' to the WHOLE card: every string
      field (summary, key_takeaway(s), investment_thesis, notable_quotes quote+speaker,
      Deep Dive overview/evidence/falsification tracks, ...) except the title fields.
      Optional 'drop_tickers' removes symbols from tickers_mentioned / key_tickers.
      Optional 'rename_tickers' renames symbols in those fields and ticker_analysis keys.
      Optional 'add_key_tickers' appends missing symbols to key_tickers (idempotent).
      Optional 'drop_takeaways' removes key_takeaways entries containing any needle.
      Optional 'paraphrase_quotes' [[needle, summary]] turns a paraphrased notable quote into a
      summary line (quote=summary, paraphrase=True; shown without quote marks).
      Optional 'relabel_quotes' [[needle, speaker]] fixes a notable quote's speaker label only.
      Optional 'drop_list_items' {field: [needle]} removes list entries (e.g. falsification_tracks)
      containing any needle.
    - 'global_replacements': exact swaps applied to every string anywhere (except title
      fields), e.g. mis-transcribed speaker names in pundits/overton/podcastGuests.
    - 'global_name_replacements': WHOLE-WORD [old, new] swaps on every string except titles,
      slugs and URLs, raw transcript snippets included (Oct 19 2026, e.g. "Oliver Karaz").
    - 'ticker_renames' / 'global_drop_tickers' / 'sponsor_tickers' / 'asset_class_tickers': applied
      to every record that has tickers_mentioned, key_tickers, or ticker_analysis (after per-card rules).
    """
    rules_all = _load_override_rules()
    rules = rules_all.get("summaries", [])
    title_ovs = rules_all.get("title_overrides", [])
    if title_ovs:
        _apply_title_overrides(obj, title_ovs)
    global_reps = rules_all.get("global_replacements", [])
    global_ticker_renames = rules_all.get("ticker_renames", [])
    global_drop_tickers = list(rules_all.get("global_drop_tickers", []))
    # Oct 28 2026 (G, sweep_1028): 'sponsor_tickers' are podcast sponsors (e.g. LENS, the Sarmaya
    # Thematic ETF read on Monetary Matters), never a guest's pick. Dropped from every ticker list
    # (tickers_mentioned, key_tickers, deep-dive ticker_analysis) of every card; priceSnapshot and
    # free text are untouched ('lens' is also an ordinary word).
    global_drop_tickers += [t for t in rules_all.get("sponsor_tickers", []) if t not in global_drop_tickers]
    # Oct 29 2026 (G, sweep_1029): 'asset_class_tickers' are bond/asset-type abbreviations (BDC, REIT,
    # IG, HY, ABS, CMBS, ...) an analyzer sometimes lists as tickers. Not stock symbols, so dropped from
    # every ticker list the same way as sponsor_tickers; priceSnapshot and free text untouched.
    global_drop_tickers += [t for t in rules_all.get("asset_class_tickers", []) if t not in global_drop_tickers]

    def fix_record(o, r):
        reps = r.get("replacements", [])
        for k in list(o.keys()):
            if k in TITLE_FIELDS:
                continue
            o[k] = _replace_all_strings(o[k], reps, TITLE_FIELDS)
        _apply_ticker_fixes_to_record(
            o, drop=r.get("drop_tickers") or [], renames=r.get("rename_tickers") or []
        )
        if r.get("add_key_tickers") and "key_tickers" in o:
            o["key_tickers"] = _add_key_tickers(o["key_tickers"], r["add_key_tickers"])
        if r.get("drop_quotes") and "notable_quotes" in o:
            o["notable_quotes"] = _drop_quotes(o["notable_quotes"], r["drop_quotes"])
        # Oct 27 2026: 'drop_takeaways' [needle] removes key_takeaways entries containing a needle
        # (list or JSON string), e.g. a takeaway that re-quotes a garbled transcript line.
        if r.get("drop_takeaways") and "key_takeaways" in o:
            o["key_takeaways"] = _drop_quotes(o["key_takeaways"], r["drop_takeaways"])
        # Oct 23 2026 (c21): a "quote" that is really a paraphrase becomes a summary line
        # (rendered without quote marks or a "Speaker:" label).
        if r.get("paraphrase_quotes") and "notable_quotes" in o:
            o["notable_quotes"] = _paraphrase_quotes(o["notable_quotes"], r["paraphrase_quotes"])
        # Oct 28 2026 (G, deep dive drafts 616/625/628): 'relabel_quotes' [[needle, speaker]] sets the
        # speaker label of a notable quote whose text contains needle (quote text never changes).
        if r.get("relabel_quotes") and "notable_quotes" in o:
            o["notable_quotes"] = _relabel_quotes(o["notable_quotes"], r["relabel_quotes"])
        # Oct 28 2026 (G, deep dive drafts 616/625/628): 'drop_list_items' {field: [needle]} removes
        # entries of a list field (e.g. Deep Dive falsification_tracks) containing any needle.
        for field, needles in (r.get("drop_list_items") or {}).items():
            if field in o and needles:
                o[field] = _drop_quotes(o[field], needles)
        # Oct 21 2026: curated sentiment correction (scoped by ids like the other fields)
        if r.get("set_sentiment") and "sentiment" in o:
            o["sentiment"] = r["set_sentiment"]

    def walk(o):
        if isinstance(o, dict):
            title = " ".join(str(o.get(f) or "") for f in TITLE_FIELDS)
            for r in rules:
                if (r.get("episode_title") and r["episode_title"] in title) or _rule_matches_episode_id(o, r):
                    fix_record(o, r)
            if global_reps:
                for k in list(o.keys()):
                    if k not in TITLE_FIELDS and isinstance(o[k], str):
                        o[k] = _replace_text(o[k], global_reps)
            # Global ticker renames/drops on any card-like dict with ticker fields
            if global_ticker_renames or global_drop_tickers:
                if any(k in o for k in ("tickers_mentioned", "key_tickers", "ticker_analysis")):
                    _apply_ticker_fixes_to_record(
                        o, drop=global_drop_tickers, renames=global_ticker_renames
                    )
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                if isinstance(v, str) and global_reps:
                    o[i] = _replace_text(v, global_reps)
                else:
                    walk(v)
    walk(obj)
    # Oct 19 2026: whole-word swaps on EVERY string except titles/slugs/URLs, including raw
    # transcript snippets (last_proof_snippet) that name_replacements deliberately skips.
    global_name_reps = rules_all.get("global_name_replacements", [])
    if global_name_reps:
        _apply_global_name_replacements(obj, global_name_reps)
    name_reps = rules_all.get("name_replacements", [])
    if name_reps:
        _apply_name_replacements(obj, name_reps)
    # Oct 20 2026: pundit rows by id, AFTER the full-name swaps so a bare-surname fix on one
    # pundit can't pre-empt "First Last" swaps.
    # Always runs: also enforces pundit_exclusions (host ids + corrected-name check).
    _apply_pundit_rules(obj, rules_all.get("pundit_excludes") or [], rules_all.get("pundit_overrides") or [],
                        rules_all.get("pundit_merges") or [], name_reps=global_name_reps)
    # Oct 22 2026: a bio like "Referenced via…"/"Mentioned in…" describes a mention, not a guest.
    _drop_mention_bios(obj)
    # Backstop: full known-name list from name_normalizer (quote-safe, exact swaps only).
    try:
        import name_normalizer
        name_normalizer.apply_to_cards(obj)
    except Exception as e:
        print(f"  ⚠ name_normalizer backstop skipped: {e}")
    # Oct 26 2026: exact global_replacements again, LAST. The first run (in walk) happens before
    # the name swaps above, so a fix written against the name-swapped text (e.g. "Garing and
    # Rozencwajg", which only exists after "Rosenswag" -> "Rozencwajg") was missed on a single
    # pass and came back in pundits.json / archive.json / data.js. Swaps are idempotent.
    if global_reps:
        _apply_global_replacements(obj, global_reps)
    # Final ticker pass (Oct 16 2026): name fixes above (e.g. "TALENT ENERGY" -> "TALEN ENERGY")
    # also touch ticker lists, so a ticker rename applied in walk() could be undone. Re-apply
    # global ticker renames/drops last so ticker fields always end on the mapped symbol.
    if global_ticker_renames or global_drop_tickers:
        def final_tickers(o):
            if isinstance(o, dict):
                if any(k in o for k in ("tickers_mentioned", "key_tickers", "ticker_analysis")):
                    _apply_ticker_fixes_to_record(o, drop=global_drop_tickers, renames=global_ticker_renames)
                for v in o.values():
                    final_tickers(v)
            elif isinstance(o, list):
                for v in o:
                    final_tickers(v)
        final_tickers(obj)
    return obj


def _apply_global_replacements(obj, global_reps):
    """Exact global_replacements on every string except title fields (same scope as walk())."""
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if isinstance(v, str):
                if k not in TITLE_FIELDS:
                    obj[k] = _replace_text(v, global_reps)
            else:
                _apply_global_replacements(v, global_reps)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                obj[i] = _replace_text(v, global_reps)
            else:
                _apply_global_replacements(v, global_reps)
    return obj


def _is_episode_record(o, episode_id):
    """podcast_summaries-style episode record (its own id is the podcast_episode id)."""
    return o.get("id") == episode_id and "podcast_name" in o and "episode_title" in o


def _rule_matches_episode_id(o, r):
    """Oct 20 2026: a 'summaries' rule with 'podcast_episode_id' matches that episode's cards
    (insight, Deep Dive, podcast summary) by id, never by title text, so two episodes with
    similar titles can't share a fix."""
    pe = r.get("podcast_episode_id")
    if pe is None or not isinstance(o, dict):
        return False
    if o.get("podcast_episode_id") == pe or _is_episode_record(o, pe):
        return True
    iid = r.get("insight_id")
    return iid is not None and o.get("insight_id") == iid


def _drop_quotes(value, needles):
    """Remove notable_quotes entries whose quote text contains any needle (list or JSON string)."""
    def keep(q):
        text = q.get("quote", "") if isinstance(q, dict) else str(q)
        return not any(n and n in text for n in needles)
    if isinstance(value, list):
        return [q for q in value if keep(q)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, list):
            return json.dumps([q for q in parsed if keep(q)])
    return value


def _relabel_quotes(value, pairs):
    """Oct 28 2026: [[needle, speaker], ...]. A notable_quotes entry whose quote text contains needle
    gets speaker=speaker; the quote text is untouched (idempotent; list or JSON string)."""
    def fix(items):
        out = []
        for q in items:
            if isinstance(q, dict):
                text = q.get("quote", "") or ""
                for needle, speaker in pairs:
                    if needle and needle in text:
                        q = dict(q, speaker=speaker)
                        break
            out.append(q)
        return out
    if isinstance(value, list):
        return fix(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, list):
            return json.dumps(fix(parsed))
    return value


def _paraphrase_quotes(value, pairs):
    """Oct 23 2026 (c21): [[needle, summary], ...]. A notable_quotes entry whose quote text
    contains needle gets quote=summary and paraphrase=True (idempotent; list or JSON string)."""
    def fix(items):
        out = []
        for q in items:
            if isinstance(q, dict):
                text = q.get("quote", "") or ""
                for needle, summary in pairs:
                    if needle and (needle in text or text == summary):
                        q = dict(q, quote=summary, paraphrase=True)
                        break
            out.append(q)
        return out
    if isinstance(value, list):
        return fix(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, list):
            return json.dumps(fix(parsed))
    return value


def _apply_title_overrides(obj, overrides):
    """Oct 20 2026: 'title_overrides' retitle ONE episode, scoped by ids (never a global string
    swap). Each rule: podcast_episode_id, insight_id, podcast_name, episode_date, old, new.
    Touches the episode's insight/Deep Dive/podcast-summary title fields, Overton
    first/last_mentioned_episode_title (by episode id), and pundit/guest last_episode_title +
    last_proof_cite (matched by podcast name + episode date + old title)."""
    def one(o, r):
        pe, iid, old, new = r.get("podcast_episode_id"), r.get("insight_id"), r.get("old"), r.get("new")
        if not old or not new:
            return
        own = (pe is not None and (o.get("podcast_episode_id") == pe or _is_episode_record(o, pe))) or (
            iid is not None and o.get("insight_id") == iid)
        if own:
            for f in TITLE_FIELDS:
                if o.get(f) == old:
                    o[f] = new
        for pref in ("last_mentioned", "first_detected"):
            if pe is not None and o.get(f"{pref}_episode_id") == pe and o.get(f"{pref}_episode_title") == old:
                o[f"{pref}_episode_title"] = new
        pod, day = r.get("podcast_name"), r.get("episode_date")
        if pod and day and o.get("last_podcast_name") == pod and o.get("last_episode_date") == day:
            if o.get("last_episode_title") == old:
                o["last_episode_title"] = new
            cite = o.get("last_proof_cite")
            if isinstance(cite, str) and cite == f"{pod} \u2022 {day} \u2022 {old}":
                o["last_proof_cite"] = f"{pod} \u2022 {day} \u2022 {new}"

    def walk(o):
        if isinstance(o, dict):
            for r in overrides:
                one(o, r)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return obj


def _is_pundit_record(o):
    """A pundits.json / dashboardData.pundits row (podcastGuests rows have no mention_score)."""
    return isinstance(o, dict) and "slug" in o and "mention_score" in o and "id" in o


def _pundit_word_swap(o, reps, key=None):
    """Whole-word swaps that also treat '-' as part of a word, so 'Gross' -> 'Wissner-Gross'
    never re-fires on 'Wissner-Gross' (idempotent on already-fixed text)."""
    def sub(text):
        for old, new in reps:
            if old and old in text:
                text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(old) + r"(?![A-Za-z0-9-])",
                              lambda _m, n=new: n, text)
        return text
    if isinstance(o, dict):
        for k in list(o.keys()):
            if isinstance(o[k], str):
                if k not in GLOBAL_NAME_SKIP_KEYS:
                    o[k] = sub(o[k])
            else:
                _pundit_word_swap(o[k], reps, k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str):
                if key not in GLOBAL_NAME_SKIP_KEYS:
                    o[i] = sub(v)
            else:
                _pundit_word_swap(v, reps, key)
    return o



def _drop_mention_bios(obj):
    """Null any pundit bio starting with 'Referenced' or 'Mentioned' (guest_check.is_rejected_bio)."""
    from guest_check import is_rejected_bio
    if isinstance(obj, dict):
        if "name" in obj and isinstance(obj.get("bio"), str) and is_rejected_bio(obj["bio"]):
            obj["bio"] = None
        for v in obj.values():
            _drop_mention_bios(v)
    elif isinstance(obj, list):
        for v in obj:
            _drop_mention_bios(v)

def _apply_pundit_rules(obj, excludes, overrides, merges=None, name_reps=None):
    """Oct 20 2026: pundit rows scoped by pundit id (DB rows are never deleted).

    - 'pundit_excludes': [{"id": 261, "name": "John Doe", ...}] drops that row from every exported
      pundit list (placeholders / non-people).
    - 'pundit_overrides': [{"id": 183, "set": {field: value}, "replacements": [[old, new]]}] sets
      fields and applies WHOLE-WORD swaps to every string of that one pundit (slugs/URLs skipped) (bio fixes, collisions).
      Optional "unset": [field] drops keys; optional "when": {field: value} applies the rule only if
      every listed field of the row equals that value."""
    from pundit_exclusions import is_excluded_pundit
    merges = merges or []
    drop = {int(e["id"] if isinstance(e, dict) else e) for e in excludes}
    by_id = {}
    for r in overrides:
        by_id.setdefault(int(r["id"]), []).append(r)

    def fix_row(o):
        for r in by_id.get(o.get("id"), []):
            # Oct 26 2026: optional 'when' {field: value} gate; the rule applies only when every
            # listed field of the row equals its value (e.g. last_episode_title), so a fix for one
            # episode's snippet no-ops once the pundit's latest episode changes.
            when = r.get("when")
            if isinstance(when, dict) and any(o.get(k) != v for k, v in when.items()):
                continue
            for k, v in (r.get("set") or {}).items():
                o[k] = copy.deepcopy(v)
            for k in r.get("unset") or []:
                o.pop(k, None)
            reps = r.get("replacements") or []
            if reps and name_reps:
                # Oct 26 2026: these rules run AFTER global_name_replacements, so an old text
                # written against the raw snippet (e.g. "... David Sachs, ...") must also match
                # its name-swapped form ("... David Sacks, ...").
                extra = []
                for pair in reps:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[0], str):
                        swapped = _replace_names(pair[0], name_reps)
                        if swapped != pair[0]:
                            extra.append([swapped, pair[1]])
                reps = list(reps) + extra
            if reps:
                _pundit_word_swap(o, reps)  # whole-word, hyphen-aware; skips slugs/URLs

    def walk(o):
        if isinstance(o, list):
            if any(_is_pundit_record(x) for x in o):
                for x in o:
                    if _is_pundit_record(x):
                        fix_row(x)
                _merge_pundit_rows(o, merges)
                o[:] = [x for x in o if not (_is_pundit_record(x) and (
                    x.get("id") in drop or is_excluded_pundit(x.get("id"), x.get("name") or "")))]
                for x in o:
                    if isinstance(x, dict):
                        x.pop("_guest_episode_ids", None)
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            if _is_pundit_record(o):
                fix_row(o)
            for v in o.values():
                walk(v)
    walk(obj)
    return obj


_PUNDIT_LATEST_FIELDS = (
    "last_seen", "last_episode_title", "last_podcast_name", "last_episode_date", "last_main_idea",
    "last_proof_cite", "last_proof_snippet", "supporting_takeaway",
)


def _merge_pundit_rows(rows, merges):
    """Oct 20 2026: 'pundit_merges' [{"keep": 192, "merge": [390]}] fold duplicate pundit rows of one
    person into the kept row (its bio/profile/net worth stay). The kept row takes the latest
    appearance fields (by last_seen) and the combined appearance count without double counting:
    when rows carry '_guest_episode_ids' (DB export) the count is the size of the union; otherwise
    the per-row counts are summed (callers have no episode lists). Presence (mention_score_decayed)
    is recomputed as combined count x the most recent row's decay factor (decayed / count), the
    same exponential decay db_manager applies from last_seen. Merged-away rows are removed here;
    list them in 'pundit_excludes' too so they stay hidden if a merge is ever dropped."""
    if not merges:
        return rows
    by_id = {x.get("id"): x for x in rows if _is_pundit_record(x)}
    gone = set()
    for m in merges:
        keep = by_id.get(m.get("keep"))
        others = [by_id[i] for i in m.get("merge") or [] if i in by_id and i != m.get("keep")]
        if keep is None or not others:
            continue
        group = [keep] + others
        if all(isinstance(x.get("_guest_episode_ids"), list) for x in group):
            count = len({e for x in group for e in x["_guest_episode_ids"]})
        else:
            count = sum(int(float(x.get("mention_score") or 0)) for x in group)
        latest = max(group, key=lambda x: str(x.get("last_seen") or ""))
        lc = float(latest.get("mention_score") or 0)
        factor = (float(latest.get("mention_score_decayed") or 0) / lc) if lc else 1.0
        if latest is not keep:
            for f in _PUNDIT_LATEST_FIELDS:
                if f in latest:
                    keep[f] = latest[f]
        keep["mention_score"] = count
        keep["mention_score_decayed"] = round(count * factor, 2)
        if all(isinstance(x.get("_guest_episode_ids"), list) for x in group):
            keep["_guest_episode_ids"] = sorted({e for x in group for e in x["_guest_episode_ids"]})
        gone.update(id(x) for x in others)
    rows[:] = [x for x in rows if id(x) not in gone]
    return rows


# Quote-safe name swaps (Oct 2026 sweep): 'name_replacements' fix mis-transcribed
# names everywhere EXCEPT direct quotes, raw transcript snippets, titles and slugs/URLs.
NAME_PROTECT_KEYS = frozenset(TITLE_FIELDS) | {
    "quote", "quotes", "notable_quotes", "last_proof_snippet", "last_proof_cite",
    "last_episode_title", "last_mentioned_episode_title", "transcript_excerpt",
    "slug", "url", "source_url", "link", "net_worth_source", "grokipedia_url",
}
_QUOTED_SPAN_RE = re.compile(
    r'"[^"\n]*"|\u201c[^\u201d]*\u201d|\u2018[^\u2019]*\u2019(?![A-Za-z])'
    r"|(?<![A-Za-z])'(?:[^'\n]|'(?=[A-Za-z]))*'(?![A-Za-z])"
)
# Transcript-style evidence lines ("Jason Calacanis: verbatim words"): the words after
# the speaker label are a direct quote; the label itself stays fixable.
_TRANSCRIPT_LINE_RE = re.compile(r"(?m)^[ \t]*(?:-[ \t]*)?[A-Z][\w.\u2019'-]*(?:[ \t][A-Z][\w.\u2019'-]*){0,3}:[ \t](.*)$")


def _protected_spans(text, key=None):
    spans = [m.span() for m in _QUOTED_SPAN_RE.finditer(text)]
    if key == "episode_evidence":
        spans += [m.span(1) for m in _TRANSCRIPT_LINE_RE.finditer(text)]
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def _name_pattern(old):
    """Whole-word match for a name swap: 'Alo's' must not hit 'Halo's', 'Open AI' must not hit 'Open AIs'."""
    pat = re.escape(old)
    if old[:1].isalnum():
        pat = r"(?<![A-Za-z0-9])" + pat
    if old[-1:].isalnum():
        pat = pat + r"(?![A-Za-z0-9])"
    return re.compile(pat)


def _replace_names(value, replacements):
    if not isinstance(value, str):
        return _replace_text(value, replacements)
    for old, new in replacements:
        if old and old in value:
            value = _name_pattern(old).sub(lambda _m, n=new: n, value)
    return value


def replace_outside_quotes(text, replacements, key=None):
    """Apply exact swaps to text, leaving quoted spans (and transcript lines) untouched."""
    if not isinstance(text, str) or not any(old in text for old, _ in replacements):
        return text
    out, pos = [], 0
    for a, b in _protected_spans(text, key) + [[len(text), len(text)]]:
        out.append(_replace_names(text[pos:a], replacements))
        out.append(text[a:b])
        pos = b
    return "".join(out)


GLOBAL_NAME_SKIP_KEYS = frozenset(TITLE_FIELDS) | {
    "slug", "url", "source_url", "link", "grokipedia_url", "net_worth_source", "audio_url", "transcript_path",
}


def _apply_global_name_replacements(obj, replacements, key=None):
    """Whole-word [old, new] swaps on every string (quotes and transcript snippets included),
    skipping title fields and slugs/URLs/paths."""
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if isinstance(v, str):
                if k not in GLOBAL_NAME_SKIP_KEYS:
                    obj[k] = _replace_names(v, replacements)
            else:
                _apply_global_name_replacements(v, replacements, k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                if key not in GLOBAL_NAME_SKIP_KEYS:
                    obj[i] = _replace_names(v, replacements)
            else:
                _apply_global_name_replacements(v, replacements, key)
    return obj


def _apply_name_replacements(obj, replacements, key=None):
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if isinstance(v, str):
                if k not in NAME_PROTECT_KEYS:
                    obj[k] = replace_outside_quotes(v, replacements, k)
            else:
                _apply_name_replacements(v, replacements, k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                if key not in NAME_PROTECT_KEYS:
                    obj[i] = replace_outside_quotes(v, replacements, key)
            else:
                _apply_name_replacements(v, replacements, key)
    return obj


def _term_rule_matches(rule, t):
    if rule.get("id") is not None and t.get("id") == rule["id"]:
        return True
    return bool(rule.get("term")) and t.get("term") == rule["term"]


def _apply_term_overrides(terms, rules=None):
    """Apply 'terms' rules (matched by id or exact term text) to term records (in place).

    A rule with "drop": true removes the record (quote fragments such as "floor").
    A rule's optional "scope" ("suggested" / "overton") limits where it applies; ids differ
    between suggested_terms and overton_terms, so id rules should set a scope.
    Optional "when" {field: value} (Oct 27 2026): the rule applies only if every listed field
    of the record equals that value (e.g. last_mentioned_episode_id), so a speaker fix for one
    episode no-ops once a later episode becomes the term's last mention.
    """
    if rules is None:
        rules = _load_override_rules().get("terms", [])
    if not isinstance(terms, list):
        return terms
    keep = []
    for t in terms:
        if not isinstance(t, dict):
            keep.append(t)
            continue
        dropped = False
        for r in rules:
            if _term_rule_matches(r, t):
                when = r.get("when")
                if isinstance(when, dict) and any(t.get(k) != v for k, v in when.items()):
                    continue
                if r.get("drop"):
                    dropped = True
                    break
                for field, value in r.get("set", {}).items():
                    t[field] = value
        if not dropped:
            keep.append(t)
    terms[:] = keep
    return terms


def _apply_overton_term_overrides(container, keys=("overton", "overton_recent", "overton_established")):
    """Apply overton-scoped term rules to Overton lists in mainContent / archive (in place)."""
    rules = [r for r in _load_override_rules().get("terms", []) if r.get("scope") == "overton"]
    if not rules or not isinstance(container, dict):
        return container
    for k in keys:
        if isinstance(container.get(k), list):
            _apply_term_overrides(container[k], rules)
    return container


CURATED_OVERTON_PATH = Path(__file__).parent.parent / "site" / "data" / "curated_overton.json"


def _drop_terms_pinned_as_curated(terms, path=None):
    """Drop suggested terms superseded by an active curated Overton seed (one term, not two).

    A seed supersedes a pipeline term when it lists the term id in 'pipeline_term_ids' or
    has the same term text (case-insensitive). E.g. 'Compute glut' seed replaces term 902.
    """
    try:
        cur = json.loads(Path(path or CURATED_OVERTON_PATH).read_text(encoding="utf-8")).get("curated") or []
    except Exception:
        return terms
    ids, names = set(), set()
    for c in cur:
        if isinstance(c, dict) and c.get("status") == "active":
            ids.update(int(i) for i in c.get("pipeline_term_ids") or [])
            if c.get("term"):
                names.add(str(c["term"]).strip().lower())
    if not isinstance(terms, list):
        return terms
    terms[:] = [t for t in terms if not (isinstance(t, dict) and (
        t.get("id") in ids or str(t.get("term") or "").strip().lower() in names))]
    return terms


def _apply_summary_overrides_to_files(site_dir: Path) -> None:
    for name in ("podcast_summaries.json", "archive.json", "pundits.json", "podcast_guests.json"):
        f = site_dir / name
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠ summary overrides skipped for {name}: {e}")
            continue
        before = json.dumps(data)
        if name == "podcast_guests.json" and isinstance(data, list):
            gov = load_overrides()
            block = set(gov.get("blocklist") or [])
            fixes = gov.get("fixes") or {}
            data = [g for g in data if not (isinstance(g, dict) and (g.get("name") or "") in block)]
            for g in data:
                if isinstance(g, dict) and fixes.get(g.get("name") or ""):
                    g["name"] = fixes[g["name"]]
            _apply_guest_bio_overrides(data, gov)
        if name == "archive.json" and isinstance(data, dict):
            # Oct 27 2026: archive.json carries the Overton list too; apply the same
            # overton-scoped term rules data.js gets (speaker fixes, drops).
            _apply_overton_term_overrides(data)
        _apply_summary_overrides(data)
        _normalize_tickers_mentioned(data)  # Oct 27 2026: lists, never JSON strings
        apply_style_gate(data)  # warn-only 'bet' wording check
        if json.dumps(data) != before:
            with open(f, "w") as fh:
                json.dump(data, fh, indent=2)
            print(f"  ✓ Applied summary overrides to {name}")
    report_style_gate_misses()


def export_website_data():
    """Export data for website."""
    print("="*60)
    print("Exporting Website Data")
    print("="*60)
    
    db = get_db()
    site_dir = SITE_DATA_DIR
    site_dir.mkdir(parents=True, exist_ok=True)
    
    stats = db.export_for_website(site_dir)
    print(f"✓ Exported: {stats}")
    _apply_summary_overrides_to_files(site_dir)

    # Main-page section counts (same content that feeds the three dashboard sections)
    main_content = db.get_main_page_content()
    main_page = {
        "overton": len(main_content.get("overton", [])),
        "insights": len(main_content.get("insights", [])),
        "pundits": stats.get("pundits", 0),
    }

    # Write a lightweight status.json for frontend health display
    status = {
        "last_pipeline_run": datetime.now().isoformat(),
        "last_steps": {
            # Per-day run signal (not lifetime total), so health/notifications stay truthful.
            "podcasts_analyzed": _count_podcasts_analyzed_today(),
            "overton_terms": db.get_stats().get("overton_terms_total", 0) if hasattr(db, "get_stats") else 0,
            "pundits": stats.get("pundits", 0),
        },
        "main_page": main_page,
        "counts": db.get_stats() if hasattr(db, "get_stats") else {}
    }
    with open(site_dir / "status.json", "w") as f:
        json.dump(status, f, indent=2, default=str)

    # Data Status page (pipeline-health.html) retired 2026-10-22: pipeline_state.json
    # is no longer published. _export_pipeline_state() is kept for local/manual use.

    _stamp_debate_contract_publishable()

    # Trap Map retired 2026-10-22: trap_map_home.json is no longer regenerated.

    return stats


def _regenerate_trap_home() -> None:
    """Regenerate trap_map_home.json from trap_map.json for home page summary."""
    try:
        from regenerate_trap_home import regenerate_trap_home, write_trap_home, TRAP_MAP_PATH, TRAP_HOME_PATH
        if not TRAP_MAP_PATH.is_file():
            return
        home_data = regenerate_trap_home()
        write_trap_home(home_data)
        print(f"  ✓ Regenerated trap_map_home.json ({len(home_data.get('last_monitored', []))} monitored, {len(home_data.get('upcoming_watches', []))} upcoming)")
    except Exception as e:
        print(f"  ⚠ Could not regenerate trap_map_home.json: {e}")


def _stamp_debate_contract_publishable() -> None:
    """Refresh publishable flag on debate_contract.json so the site can gate the listen page."""
    contract_path = SITE_DIR / "audio" / "debate_contract.json"
    history_path = SITE_DIR / "debate_history.json"
    if not contract_path.is_file():
        return
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ Could not read debate contract for publish stamp: {e}")
        return
    prior: list = []
    if history_path.is_file():
        try:
            hist = json.loads(history_path.read_text(encoding="utf-8"))
            # Skip the contract's own history entry (same friday_iso): a contract must not be
            # held as "too similar" to itself once its week is archived (Red Team N-1, Oct 16).
            own = str(contract.get("friday_iso") or "").strip()
            prior = [
                w.get("prompt", "")
                for w in hist.get("weeks", [])
                if w.get("prompt") and not (own and str(w.get("friday_iso") or "").strip() == own)
            ]
        except Exception:
            prior = []
    spx_ref = None
    try:
        from debate_weekly import fetch_yahoo_last_price

        spx_ref = fetch_yahoo_last_price("^GSPC")
    except Exception:
        spx_ref = None
    try:
        from debate_quality import stamp_contract_publishable

        stamped = stamp_contract_publishable(contract, prior, spx_ref=spx_ref)
    except Exception as e:
        print(f"  ⚠ Debate publish stamp skipped: {e}")
        return
    if stamped.get("publishable") != contract.get("publishable"):
        status = "publishable" if stamped.get("publishable") else "held"
        print(f"  ✓ Debate contract marked {status}")
    contract_path.write_text(json.dumps(stamped, indent=2), encoding="utf-8")


def _parse_iso_date_prefix(s: str):
    """Extract YYYY-MM-DD from many possible date strings."""
    if not s:
        return None
    s = str(s).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    return None


def _count_mp3_in_dir(d: Path) -> int:
    if not d.is_dir():
        return 0
    return len(list(d.glob("*.mp3")))


STAGE_ORDER = ("downloaded", "transcribed", "analyzed", "insight_created", "published")


def _remediation_for_stage(
    stage: str,
    *,
    has_db_row: bool,
    downloaded: bool,
    transcribed: bool,
    analyzed: bool,
    insight_created: bool,
    whisper_queue_mp3: int,
    pipe: str,
    ws: str,
) -> dict:
    """
    Machine-oriented remediation for pipeline_state.json (LLM / simple automations).
    `commands` are exemplar shell lines; adjust paths if WORKSPACE_ROOT differs.
    """
    pipe = pipe.replace("\\", "/")
    ws = ws.replace("\\", "/")
    base: dict = {"action_id": "", "steps": [], "commands": []}

    if stage == "downloaded":
        return {
            **base,
            "action_id": "FETCH_AUDIO",
            "steps": [
                "Approve the episode in curation (curate.py refreshes pipeline/state/curation_log.json).",
                "Download audio and enqueue transcription: fetch_latest.py --queue-only.",
                "If MP3 never appears, inspect pipeline/logs/pipeline_schedule.err and fetch_latest output.",
            ],
            "commands": [
                f"cd {pipe} && python3 curate.py",
                f"cd {pipe} && python3 fetch_latest.py --queue-only",
            ],
        }

    if stage == "transcribed":
        if not downloaded:
            return {
                **base,
                "action_id": "FETCH_BEFORE_TRANSCRIBE",
                "steps": [
                    "Audio must exist before transcription. Complete FETCH_AUDIO first.",
                ],
                "commands": [f"cd {pipe} && python3 curate.py", f"cd {pipe} && python3 fetch_latest.py --queue-only"],
            }
        extra_q = []
        if whisper_queue_mp3 > 0:
            extra_q.append(
                f"There are {whisper_queue_mp3} MP3 file(s) in whisper_queue/ waiting for the worker."
            )
        return {
            **base,
            "action_id": "TRANSCRIBE",
            "steps": [
                *extra_q,
                "Run whisper_worker.sh from the repo root (WORKSPACE_ROOT) so whisper_queue/ drains to whisper_done/.",
                "If the queue is empty but there is still no transcript, read whisper_worker.log for Whisper failures.",
                "After transcripts land in whisper_done/, run auto_pipeline.py so fetch sweeps them into the DB and pipeline/transcripts/.",
            ],
            "commands": [
                f"cd {ws} && ./whisper_worker.sh",
                f"cd {pipe} && python3 auto_pipeline.py",
            ],
        }

    if stage == "analyzed":
        return {
            **base,
            "action_id": "ANALYZE_TRANSCRIPTS",
            "steps": [
                "Run transcript analysis so is_processed=1 on podcast_episodes (analyze_transcript via auto_pipeline).",
                "Ensure LLM keys in workspace .env (e.g. MOONSHOT_API_KEY) are set if the analyzer requires them.",
                "Quick path: auto_pipeline.py --analyze-only analyzes then continues promotion/export steps in that run.",
            ],
            "commands": [
                f"cd {pipe} && python3 auto_pipeline.py --analyze-only",
                f"cd {pipe} && python3 auto_pipeline.py",
            ],
        }

    if stage == "insight_created":
        return {
            **base,
            "action_id": "PROMOTE_INSIGHT",
            "steps": [
                "Promotion to latest_insights runs inside auto_pipeline after analysis.",
                "If analysis succeeded but insight is missing, re-run full auto_pipeline.py and check logs for promote_episodes_to_insights errors.",
            ],
            "commands": [f"cd {pipe} && python3 auto_pipeline.py"],
        }

    if stage == "published":
        return {
            **base,
            "action_id": "EXPORT_AND_PUBLISH",
            "steps": [
                "Site export runs only after generate_deepdives.py succeeds; if Deep Dives fail, export and git push are skipped.",
                "Fix Deep Dive errors (see pipeline logs), then run auto_pipeline.py to export site JSON and push.",
                "When added_to_site=1 on the episode row, this stage turns green.",
            ],
            "commands": [
                f"cd {pipe} && python3 generate_deepdives.py",
                f"cd {pipe} && python3 auto_pipeline.py",
            ],
        }

    return {**base, "action_id": "UNKNOWN", "steps": ["Re-run export_data / auto_pipeline and inspect logs."], "commands": []}


def _export_pipeline_state(site_dir: Path):
    """
    Canonical pipeline export consumed by `site/pipeline-health.html`.

    Design goal:
    - Episodes selection comes from `pipeline/state/curation_log.json` approvals.
    - Stage completion comes ONLY from DB rows (`podcast_episodes`, `latest_insights`).
    - No artifact-based inference (no substring search in data.js, no tracker snapshot dependency).
    """
    from db_manager import get_db

    state_dir = Path(__file__).parent / "state"
    curated_path = state_dir / "curation_log.json"
    rss_filter_criteria = _rss_filter_criteria()

    generated_at = datetime.now().isoformat()
    last_updated = generated_at

    _refresh_pipeline_tracker()

    # Load curated approvals (episodes Clawbot should be processing).
    curated_eps = []
    if curated_path.exists():
        try:
            curated = json.loads(curated_path.read_text(encoding="utf-8"))
            for ep in curated.get("episodes", []):
                if ep.get("status") != "APPROVED":
                    continue
                curated_eps.append(ep)
        except Exception:
            curated_eps = []

    # DB lookups
    db = get_db()
    episode_rows_by_guid = {}
    insights_by_episode_id = {}
    deepdives_by_episode_id = {}
    try:
        with db._get_connection() as conn:
            # Insight counts for every episode id — not only rows matched by rss_guid below.
            # Episodes with NULL/missing rss_guid are joined via fuzzy fallback; their ids were
            # omitted from the old "insights for guid-matched ids only" query, which falsely
            # showed insight_created=false (pipeline stuck on needs_insight) despite a row in
            # latest_insights.
            cur_ins = conn.execute(
                """
                SELECT podcast_episode_id, COUNT(*) as c
                FROM latest_insights
                WHERE podcast_episode_id IS NOT NULL
                GROUP BY podcast_episode_id
                """
            )
            for row2 in cur_ins.fetchall():
                rr = dict(row2)
                pid = rr.get("podcast_episode_id")
                if pid is None:
                    continue
                insights_by_episode_id[int(pid)] = int(rr["c"] or 0)

            # Deep dive counts by episode id — used to identify off-main overflow
            # (episodes that have insight + deep dive but just didn't make the main-10)
            cur_dd = conn.execute(
                """
                SELECT li.podcast_episode_id, COUNT(ddc.id) as c
                FROM deep_dive_content ddc
                JOIN latest_insights li ON ddc.insight_id = li.id
                WHERE li.podcast_episode_id IS NOT NULL
                GROUP BY li.podcast_episode_id
                """
            )
            for row2 in cur_dd.fetchall():
                rr = dict(row2)
                pid = rr.get("podcast_episode_id")
                if pid is None:
                    continue
                deepdives_by_episode_id[int(pid)] = int(rr["c"] or 0)

            # Fetch all podcast_episodes rows for curated rss_guids in one shot.
            guids = [str(ep.get("rss_guid") or "").strip() for ep in curated_eps if ep.get("rss_guid")]
            guids = sorted(set([g for g in guids if g]))
            if guids:
                # SQLite parameter limit safety not needed for small windows.
                q_marks = ",".join(["?"] * len(guids))
                cur = conn.execute(
                    f"""
                    SELECT id, rss_guid, podcast_name, episode_title, episode_date,
                           audio_url, transcript_path, is_processed, added_to_site
                    FROM podcast_episodes
                    WHERE rss_guid IN ({q_marks})
                    """,
                    guids,
                )
                for row in cur.fetchall():
                    r = dict(row)
                    episode_rows_by_guid[str(r.get("rss_guid") or "")] = r
    except Exception as e:
        print(f"  ⚠ Could not build pipeline_state from DB: {e}")

    def derive_status(downloaded: bool, transcribed: bool, analyzed: bool, insight_created: bool, published: bool, deepdive_blocked: bool = False) -> str:
        if not downloaded:
            return "needs_download"
        if not transcribed:
            return "needs_transcription"
        if not analyzed:
            return "needs_analysis"
        if not insight_created:
            return "needs_insight"
        if deepdive_blocked:
            return "blocked_deepdive"
        if not published:
            return "needs_export"
        return "complete"

    def stage_reason_missing(missing_stage: str, has_db_row: bool) -> str:
        if not has_db_row:
            return (
                "No podcast_episodes row yet (curated APPROVED but DB not updated). "
                "Usually fixed by: fetch_latest --queue-only + whisper worker + auto_pipeline sweep."
            )
        mapping = {
            "downloaded": "No audio_url/transcript_path on DB row and no local audio file in curation — run fetch.",
            "transcribed": "No transcript on DB/disk — whisper_queue must drain (whisper_worker.sh) then auto_pipeline.",
            "analyzed": "Transcript exists but is_processed=0 — run auto_pipeline analysis (or --analyze-only).",
            "insight_created": "Analyzed but no latest_insights row — re-run auto_pipeline (insight promotion step).",
            "published": "Insight exists but no deep dive content yet — run generate_deepdives.py then auto_pipeline.",
        }
        return mapping.get(missing_stage, "Missing stage.")

    # Build episode objects
    episodes_out = []
    stale_threshold_days = 2
    # stale_episodes: curation_log APPROVED is the active fetch queue, while stale
    # also covers unpublished recent DB rows (episodes that finished processing but
    # haven't reached the live site yet).
    stale_episodes = []

    def compute_age_days(pub_str: str):
        tup = _parse_iso_date_prefix(pub_str)
        if not tup:
            return None
        try:
            from datetime import date

            pub_d = date(tup[0], tup[1], tup[2])
            return (date.today() - pub_d).days
        except Exception:
            return None

    stage_counts = {
        "downloaded": 0,
        "transcribed": 0,
        "analyzed": 0,
        "insight_created": 0,
        "published": 0,
        "total": 0,
    }

    fallback_cache = {}

    # Deterministic "disk evidence" index:
    # - When a curated episode isn't yet present in SQLite (`podcast_episodes` row missing),
    #   we still want the pipeline-health dashboard to reflect whether audio/transcript
    #   files exist locally.
    #
    # This fixes situations where:
    #   - DB row is missing (analysis failed to insert), but
    #   - the download/transcription artifacts are already on disk.
    transcript_dir = Path(__file__).parent / "transcripts"
    needed_rss = {
        str(ep.get("rss_guid") or "").strip()
        for ep in curated_eps
        if ep.get("rss_guid")
    }
    rss_to_transcript_txt: dict[str, Path] = {}
    if needed_rss and transcript_dir.is_dir():
        for meta_path in transcript_dir.glob("*.meta.json"):
            if len(rss_to_transcript_txt) >= len(needed_rss):
                break
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rg = str(meta.get("rss_guid") or "").strip()
            if not rg or rg not in needed_rss:
                continue
            if rg in rss_to_transcript_txt:
                continue
            # transcript file name is the meta file name with the trailing
            # ".meta.json" replaced by ".txt"
            txt_name = meta_path.name
            if txt_name.endswith(".meta.json"):
                txt_name = txt_name[: -len(".meta.json")] + ".txt"
            else:
                txt_name = meta_path.stem + ".txt"
            rss_to_transcript_txt[rg] = meta_path.with_name(txt_name)

    whisper_queue_mp3 = _count_mp3_in_dir(WHISPER_QUEUE_DIR)
    pipe_dir = str(PIPELINE_DIR)
    ws_dir = str(WORKSPACE_ROOT)

    for ep in curated_eps:
        podcast = ep.get("podcast", "") or ""
        title = ep.get("title", "") or ""
        rss_guid = (ep.get("rss_guid") or "").strip()
        published_str = ep.get("published_date") or ep.get("published") or ""
        age_days = compute_age_days(published_str)

        pe = episode_rows_by_guid.get(rss_guid) if rss_guid else None
        # Fallback: sometimes rss_guid isn't persisted into podcast_episodes
        # (e.g. missing transcript sidecar meta). If so, match by podcast + title
        # prefix so pipeline-health isn't permanently stuck on "Not in DB yet".
        if pe is None and rss_guid:
            cache_key = f"{podcast}::{str(title)[:40].lower()}"
            if cache_key in fallback_cache:
                pe = fallback_cache[cache_key]
            else:
                try:
                    import difflib

                    def _norm(s: str) -> str:
                        # Strip punctuation/whitespace; keep alnum only.
                        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

                    target_norm = _norm(title)[:120]

                    best_ratio = 0.0
                    best_row = None

                    with db._get_connection() as conn2:
                        cur = conn2.execute(
                            """
                            SELECT id, rss_guid, podcast_name, episode_title, episode_date,
                                   audio_url, transcript_path, is_processed, added_to_site
                            FROM podcast_episodes
                            WHERE podcast_name = ?
                            ORDER BY episode_date DESC, id DESC
                            LIMIT 25
                            """,
                            (podcast,),
                        )
                        for row in cur.fetchall():
                            cand = dict(row)
                            cand_norm = _norm(cand.get("episode_title") or "")[:120]
                            if not cand_norm:
                                continue
                            ratio = difflib.SequenceMatcher(None, target_norm, cand_norm).ratio()
                            if ratio > best_ratio:
                                best_ratio = ratio
                                best_row = cand

                    # Threshold intentionally low because episode_title may be AI-inferred or slug-derived.
                    pe = best_row if best_ratio >= 0.35 else None
                except Exception:
                    pe = None
                # Never attach another episode's DB row: fuzzy match must not steal
                # pipeline state when this curation row has its own rss_guid that
                # simply isn't in podcast_episodes yet (or differs from a coincidentally
                # similar title — e.g. "…Building a16z…" vs "Building for the Physical Economy").
                if pe is not None and rss_guid:
                    db_g = str(pe.get("rss_guid") or "").strip()
                    if db_g and db_g != rss_guid:
                        pe = None
                fallback_cache[cache_key] = pe
        has_db_row = bool(pe)
        podcast_episode_id = int(pe["id"]) if pe and pe.get("id") is not None else None

        audio_url = (pe.get("audio_url") or "") if pe else ""
        transcript_path = (pe.get("transcript_path") or "") if pe else ""
        is_processed = bool(pe.get("is_processed")) if pe else False
        added_to_site = bool(pe.get("added_to_site")) if pe else False

        downloaded_db = bool(audio_url) or bool(transcript_path)
        transcribed_db = bool(transcript_path)

        # Disk evidence (from curation_log + transcript meta mapping)
        audio_file = str(ep.get("audio_file") or "").strip()
        downloaded_fs = bool(audio_file) and Path(audio_file).is_file()

        transcript_txt = rss_to_transcript_txt.get(rss_guid) if rss_guid else None
        transcribed_fs = bool(transcript_txt) and Path(transcript_txt).is_file()

        downloaded = downloaded_db or downloaded_fs
        transcribed = transcribed_db or transcribed_fs
        analyzed = is_processed
        insight_created = False
        has_deepdive = False
        if podcast_episode_id is not None:
            insight_created = bool(insights_by_episode_id.get(podcast_episode_id, 0) > 0)
            has_deepdive = bool(deepdives_by_episode_id.get(podcast_episode_id, 0) > 0)
        published = added_to_site

        # Stage reasons (deterministic, DB-based)
        st_reasons = {}
        if not downloaded:
            st_reasons["downloaded"] = stage_reason_missing("downloaded", has_db_row)
        if not transcribed:
            st_reasons["transcribed"] = stage_reason_missing("transcribed", has_db_row)
        if not analyzed:
            st_reasons["analyzed"] = stage_reason_missing("analyzed", has_db_row)
        if not insight_created:
            st_reasons["insight_created"] = stage_reason_missing("insight_created", has_db_row)
        if not published:
            st_reasons["published"] = stage_reason_missing("published", has_db_row)

        status = derive_status(downloaded, transcribed, analyzed, insight_created, published)
        ep_key = rss_guid if rss_guid else f"{podcast}_{title[:40]}".replace(" ", "_").lower()

        stages_dict = {
            "downloaded": downloaded,
            "transcribed": transcribed,
            "analyzed": analyzed,
            "insight_created": insight_created,
            "published": published,
        }
        remediation_by_stage: dict[str, dict] = {}
        for sk in STAGE_ORDER:
            if stages_dict.get(sk):
                continue
            remediation_by_stage[sk] = _remediation_for_stage(
                sk,
                has_db_row=has_db_row,
                downloaded=downloaded,
                transcribed=transcribed,
                analyzed=analyzed,
                insight_created=insight_created,
                whisper_queue_mp3=whisper_queue_mp3,
                pipe=pipe_dir,
                ws=ws_dir,
            )
        first_blocker = next((sk for sk in STAGE_ORDER if not stages_dict.get(sk)), None)

        # Increment stage counts
        if downloaded:
            stage_counts["downloaded"] += 1
        if transcribed:
            stage_counts["transcribed"] += 1
        if analyzed:
            stage_counts["analyzed"] += 1
        if insight_created:
            stage_counts["insight_created"] += 1
        if published:
            stage_counts["published"] += 1

        episodes_out.append(
            {
                "id": ep_key,
                "podcast": podcast,
                "title": pe.get("episode_title") if pe and pe.get("episode_title") else title,
                "published": published_str,
                "rss_guid": rss_guid,
                "stages": stages_dict,
                "stage_reasons": st_reasons,
                "first_blocker": first_blocker,
                "remediation_by_stage": remediation_by_stage,
                "status": status,
            }
        )

        # After decoupling added_to_site from display_on_main:
        # Episodes with insight + deep dive have added_to_site=1 (published=True, status=complete)
        # regardless of whether they're on the main-10 carousel. True pipeline debt (status!=complete)
        # means missing insight OR missing deep dive - escalate those to stale list.

        if status != "complete" and age_days is not None and age_days >= stale_threshold_days:
            blocker = next((k for k in ["downloaded", "transcribed", "analyzed", "insight_created", "published"] if not (episodes_out[-1]["stages"].get(k))), "unknown")
            stale_episodes.append(
                {
                    "id": ep_key,
                    "podcast": podcast,
                    "title": episodes_out[-1]["title"],
                    "status": status,
                    "published": published_str,
                    "age_days": age_days,
                    "next_blocker": blocker,
                }
            )

    # New on feeds: RSS-only episodes not yet in curation/db pipeline selection.
    # We preserve existing curate/filter logic (window + feeds list) by using the helper.
    curated_guid_set = {str(ep.get("rss_guid") or "").strip() for ep in curated_eps if ep.get("rss_guid")}

    def _norm(s: str) -> str:
        # Normalize for identity matching regardless of punctuation/typography.
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    def _episode_identity_key(podcast: str, title: str) -> str:
        # Use a prefix of title so minor truncation doesn't break matching.
        return f"{_norm(podcast)}::{_norm(title)[:120]}"

    curated_identity_set = {
        _episode_identity_key(str(ep.get("podcast") or ""), str(ep.get("title") or ""))
        for ep in curated_eps
    }
    try:
        from curate import get_feed_episodes_not_in_db

        raw_available = get_feed_episodes_not_in_db()
        available_from_rss = []
        for ep in raw_available:
            g = (ep.get("rss_guid") or "").strip() if isinstance(ep, dict) else ""
            if g and g in curated_guid_set:
                continue
            available_from_rss.append(
                {
                    "podcast": ep.get("podcast", ""),
                    "title": ep.get("title", ""),
                    "published": ep.get("published", "") or ep.get("published_date", ""),
                    "published_date": ep.get("published_date", ""),
                    "rss_guid": ep.get("rss_guid", ""),
                }
            )
    except Exception:
        available_from_rss = []

    # Treat RSS-only rows as first-class pipeline placeholders.
    tracked_feed_placeholders = []
    for ep in available_from_rss:
        ep_id = f"rss::{(ep.get('podcast', '') or '').strip().lower()}::{(ep.get('title', '') or '').strip().lower()}"[:180]
        placeholder_published_date = ep.get("published_date", "") or ""

        # If this RSS item is already in the curated selection, don't show it
        # again as an "RSS-only placeholder" (common when rss_guid is missing/blank).
        if _episode_identity_key(str(ep.get("podcast") or ""), str(ep.get("title") or "")) in curated_identity_set:
            continue

        stages_ph = {
            "downloaded": False,
            "transcribed": False,
            "analyzed": False,
            "insight_created": False,
            "published": False,
        }
        rem_ph: dict[str, dict] = {}
        for sk in STAGE_ORDER:
            rem_ph[sk] = _remediation_for_stage(
                sk,
                has_db_row=False,
                downloaded=False,
                transcribed=False,
                analyzed=False,
                insight_created=False,
                whisper_queue_mp3=whisper_queue_mp3,
                pipe=pipe_dir,
                ws=ws_dir,
            )
        tracked_feed_placeholders.append(
            {
                "id": ep_id,
                "podcast": ep.get("podcast", ""),
                "title": ep.get("title", ""),
                # Prefer ISO date for sorting/display so placeholders don't
                # look like "different episodes" just due to RSS timestamp formatting.
                "published": placeholder_published_date or (ep.get("published", "") or ""),
                "published_date": placeholder_published_date,
                "rss_guid": ep.get("rss_guid", ""),
                "stages": stages_ph,
                "stage_reasons": {
                    "downloaded": "RSS-only: not in curation_log APPROVED list yet — run curate.py so it can be fetched.",
                    "transcribed": "Blocked until download completes.",
                    "analyzed": "Blocked until transcript exists.",
                    "insight_created": "Blocked until analysis completes.",
                    "published": "Blocked until export after insight promotion.",
                },
                "first_blocker": "downloaded",
                "remediation_by_stage": rem_ph,
                "status": "needs_download",
            }
        )

    episodes_all = episodes_out + tracked_feed_placeholders
    stage_counts["total"] = len(episodes_all)

    # Also include old RSS placeholders in stale list if past threshold.
    for ep in tracked_feed_placeholders:
        age_days = compute_age_days(ep.get("published_date", "") or ep.get("published", ""))
        if age_days is not None and age_days >= stale_threshold_days:
            stale_episodes.append(
                {
                    "id": ep.get("id", ""),
                    "podcast": ep.get("podcast", ""),
                    "title": ep.get("title", ""),
                    "status": ep.get("status", "needs_download"),
                    "published": ep.get("published", ""),
                    "age_days": age_days,
                    "next_blocker": "downloaded",
                }
            )

    # Third pass: Include recent DB episodes that are incomplete from a site perspective.
    # This catches episodes that finished analysis/insight but aren't on the live site yet,
    # even if they've left the curation window (curation_log APPROVED is the active fetch
    # queue, while stale also covers unpublished recent DB rows).
    stale_lookback_days = 14
    tracked_episode_ids = set()
    tracked_rss_guids = set()
    for ep in stale_episodes:
        eid = ep.get("id", "")
        if eid:
            tracked_episode_ids.add(str(eid).lower())
        rss = ep.get("rss_guid", "")
        if rss:
            tracked_rss_guids.add(str(rss).strip())

    try:
        with db._get_connection() as conn:
            # Check if deep_dive_generation_failures table exists
            failures_table_exists = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='deep_dive_generation_failures'"
            ).fetchone()[0] > 0
            
            # Query recent episodes with actual pipeline debt:
            # - Within lookback window (last 14 days by episode_date or created_at)
            # - Age >= stale_threshold_days
            # - Missing insight OR missing deep dive (true pipeline debt)
            # NOTE: episodes with insight + deep dive but added_to_site=0 are "off-main
            # overflow" (lost the main-10 race) — NOT pipeline debt, so excluded here.
            blocked_subquery = """(SELECT COUNT(*) FROM deep_dive_generation_failures dgf
                     JOIN latest_insights li3 ON dgf.insight_id = li3.id
                     WHERE li3.podcast_episode_id = pe.id AND dgf.status = 'blocked')""" if failures_table_exists else "0"
            
            cur = conn.execute(
                f"""
                SELECT 
                    pe.id,
                    pe.rss_guid,
                    pe.podcast_name,
                    pe.episode_title,
                    pe.episode_date,
                    pe.audio_url,
                    pe.transcript_path,
                    pe.is_processed,
                    pe.added_to_site,
                    pe.created_at,
                    (SELECT COUNT(*) FROM latest_insights li WHERE li.podcast_episode_id = pe.id) AS insight_count,
                    (SELECT COUNT(*) FROM deep_dive_content ddc 
                     JOIN latest_insights li2 ON ddc.insight_id = li2.id 
                     WHERE li2.podcast_episode_id = pe.id) AS deepdive_count,
                    {blocked_subquery} AS blocked_deepdive_count
                FROM podcast_episodes pe
                WHERE date(COALESCE(pe.episode_date, date(pe.created_at))) >= date('now', ?)
                  AND julianday('now') - julianday(COALESCE(pe.episode_date, date(pe.created_at))) >= ?
                  AND (
                      NOT EXISTS (SELECT 1 FROM latest_insights li WHERE li.podcast_episode_id = pe.id)
                      OR NOT EXISTS (
                          SELECT 1 FROM deep_dive_content ddc
                          JOIN latest_insights li2 ON ddc.insight_id = li2.id
                          WHERE li2.podcast_episode_id = pe.id
                      )
                  )
                ORDER BY pe.episode_date DESC, pe.id DESC
                """,
                (f'-{stale_lookback_days} days', stale_threshold_days),
            )
            for row in cur.fetchall():
                r = dict(row)
                ep_id = r.get("id")
                rss_guid = str(r.get("rss_guid") or "").strip()

                # Dedupe: skip if already tracked by rss_guid or constructed id
                if rss_guid and rss_guid in tracked_rss_guids:
                    continue
                ep_key = rss_guid if rss_guid else f"{r.get('podcast_name', '')}_{str(r.get('episode_title', ''))[:40]}".replace(" ", "_").lower()
                if ep_key.lower() in tracked_episode_ids:
                    continue

                # Compute age
                pub_str = str(r.get("episode_date") or "")[:10]
                age_days = compute_age_days(pub_str)
                if age_days is None:
                    # Fallback to created_at
                    created = str(r.get("created_at") or "")[:10]
                    age_days = compute_age_days(created)
                if age_days is None or age_days < stale_threshold_days:
                    continue

                # Compute status and blocker
                downloaded = bool(r.get("audio_url")) or bool(r.get("transcript_path"))
                transcribed = bool(r.get("transcript_path"))
                analyzed = bool(r.get("is_processed"))
                insight_created = int(r.get("insight_count") or 0) > 0
                has_deepdive = int(r.get("deepdive_count") or 0) > 0
                deepdive_blocked = int(r.get("blocked_deepdive_count") or 0) > 0
                published = bool(r.get("added_to_site")) and insight_created and has_deepdive

                status = derive_status(downloaded, transcribed, analyzed, insight_created, published, deepdive_blocked)
                if status == "complete":
                    continue  # Already fully published

                if deepdive_blocked:
                    blocker = "deepdive_blocked"
                else:
                    blocker = next(
                        (k for k in ["downloaded", "transcribed", "analyzed", "insight_created", "published"]
                         if not {"downloaded": downloaded, "transcribed": transcribed, "analyzed": analyzed,
                                 "insight_created": insight_created, "published": published}.get(k)),
                        "unknown"
                    )

                stale_episodes.append(
                    {
                        "id": ep_key,
                        "podcast": r.get("podcast_name", ""),
                        "title": r.get("episode_title", ""),
                        "status": status,
                        "published": pub_str,
                        "age_days": age_days,
                        "next_blocker": blocker,
                        "source": "db_incomplete",  # Distinguish from curated/rss sources
                    }
                )
                tracked_episode_ids.add(ep_key.lower())
                if rss_guid:
                    tracked_rss_guids.add(rss_guid)
    except Exception as e:
        print(f"  ⚠ Could not add DB-incomplete episodes to stale list: {e}")

    # main-page tie-out and counts (keep dashboard consistent)
    try:
        main_content = db.get_main_page_content()
        pundits_count = 0
        # Prefer the exact list exported for the site so Pipeline Health tie-out matches.
        try:
            pundits_path = site_dir / "pundits.json"
            if pundits_path.exists():
                with open(pundits_path, "r", encoding="utf-8") as f:
                    pundits = json.load(f)
                pundits_count = len(pundits) if isinstance(pundits, list) else 0
        except Exception:
            pundits_count = main_content.get("pundits", 0)
        main_page = {
            "overton": len(main_content.get("overton", [])),
            "insights": len(main_content.get("insights", [])),
            "pundits": pundits_count,
        }
    except Exception:
        main_page = {"overton": 0, "insights": 0, "pundits": 0}

    try:
        counts = db.get_stats()
    except Exception:
        counts = {}
    # Health dashboard expects a "podcasts_analyzed" key for tie-out counts.
    # This should be a per-day signal (not lifetime totals).
    try:
        counts["podcasts_analyzed"] = _count_podcasts_analyzed_today()
    except Exception:
        counts["podcasts_analyzed"] = 0

    payload = {
        "generated_at": generated_at,
        "last_updated": last_updated,
        "last_pipeline_run": generated_at,
        "main_page": main_page,
        "counts": counts,
        "step_results": {
            # stage_counts as integers
            "downloaded": stage_counts["downloaded"],
            "transcribed": stage_counts["transcribed"],
            "analyzed": stage_counts["analyzed"],
            "insight_created": stage_counts["insight_created"],
            "published": stage_counts["published"],
            "total": stage_counts["total"],
        },
        "episodes": episodes_all,
        "available_from_rss": available_from_rss,
        "stale_episodes": stale_episodes,
        "stale_threshold_days": stale_threshold_days,
        "rss_filter_criteria": rss_filter_criteria,
        "automation_hints": {
            "stage_order": list(STAGE_ORDER),
            "whisper_queue_pending_mp3": whisper_queue_mp3,
            "fix_order": "For each episode, read first_blocker then remediation_by_stage[first_blocker].",
            "end_to_end": f"cd {pipe_dir} && python3 auto_pipeline.py",
            "analyze_only": f"cd {pipe_dir} && python3 auto_pipeline.py --analyze-only",
            "whisper_worker": f"cd {ws_dir} && ./whisper_worker.sh",
            "schema": "episode.remediation_by_stage[stage] = {action_id, steps[], commands[]}",
        },
        "note": "Canonical pipeline_state from DB + curation. Red stages include stage_reasons (human) and remediation_by_stage (action_id, steps, commands) for automation.",
    }

    payload = strip_cjk_public_text(payload)

    site_dir.mkdir(parents=True, exist_ok=True)
    out_path = site_dir / "pipeline_state.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  ✓ Exported pipeline_state.json: {len(episodes_all)} tracked")


def _rss_filter_criteria():
    """RSS filter criteria for Pipeline Health (from curate.py / cutoff_date)."""
    try:
        from cutoff_date import CUTOFF_DATE_ISO
    except Exception:
        CUTOFF_DATE_ISO = "2026-02-01"
    try:
        from curate import CURRENT_MONTH_ONLY
    except Exception:
        CURRENT_MONTH_ONLY = True
    criteria = {
        "cutoff_date": CUTOFF_DATE_ISO,
        "approval": "Feed list is the filter. If a feed is in podcast_feeds.txt, all its episodes (within window) are approved. No per-episode relevance score.",
        "feeds": "podcast_feeds.txt (active); podcast_feeds_on_hold.txt (paused — no new fetch/transcribe). Episodes already in DB (by rss_guid) are skipped.",
    }
    if CURRENT_MONTH_ONLY:
        criteria["window"] = "Current calendar month only (forward-looking; no backfill of prior months)."
    else:
        criteria["max_episode_age_days"] = 60
    return criteria


def _apply_guest_export_overrides(main_content: dict, podcast_guests: list) -> tuple[dict, list]:
    """Stamp insight guest lines and drop blocklisted title-fragment guests."""
    ov = load_overrides()
    by_insight = ov.get("insight_guest_by_id") or {}
    block = set(ov.get("blocklist") or [])
    host_by = ov.get("insight_host_by_id") or {}
    org_by = ov.get("insight_guest_org_by_id") or {}
    for ins in main_content.get("insights", []) or []:
        key = str(ins.get("id"))
        if key in by_insight:
            override = by_insight[key]
            # Oct 21 2026: "" / null = explicitly blank (never fall back to a title fragment)
            ins["guest_name"] = override if override else None
        if host_by.get(key):
            ins["host_name"] = host_by[key]
        if org_by.get(key):
            ins["guest_org"] = org_by[key]
    filtered = [g for g in podcast_guests if (g.get("name") or "") not in block]
    fixes = ov.get("fixes") or {}
    for g in filtered:
        fixed = fixes.get(g.get("name") or "")
        if fixed:
            g["name"] = fixed
    _apply_guest_bio_overrides(filtered, ov)
    return main_content, filtered


def _apply_guest_bio_overrides(guests, ov=None):
    """Fill empty podcastGuests bio/known_for from guest_overrides.json 'overrides' (by exact name).

    extract_guests.grokipedia_lookup only applies these at extraction time, so guests already
    in the DB with bio=None stay blank on a re-export without this export-time pass.
    """
    ov = ov if ov is not None else load_overrides()
    curated = ov.get("overrides") or {}
    for g in guests if isinstance(guests, list) else []:
        if not isinstance(g, dict):
            continue
        entry = curated.get(g.get("name") or "")
        if not isinstance(entry, dict):
            continue
        for field in ("bio", "known_for"):
            if entry.get(field) and not g.get(field):
                g[field] = entry[field]
    return guests


def generate_website_js():
    """Generate JavaScript file with data for website."""
    print("\n" + "="*60)
    print("Generating Website JavaScript")
    print("="*60)
    
    db = get_db()
    site_dir = SITE_DATA_DIR
    
    # Get all data including archive
    archive = sanitize_public_text(db.export_archive_data())
    main_content = sanitize_public_text(db.get_main_page_content())
    deepdives = sanitize_public_text(db.get_all_deep_dive_content())
    suggested_terms = sanitize_public_text(db.get_suggested_terms_for_website(limit=4))
    podcast_guests = sanitize_public_text(db.get_podcast_guests_for_site(limit=20))
    main_content, podcast_guests = _apply_guest_export_overrides(main_content, podcast_guests)
    _apply_summary_overrides(archive)
    _apply_summary_overrides(main_content)
    _apply_summary_overrides(deepdives)
    _apply_summary_overrides(podcast_guests)
    _apply_term_overrides(suggested_terms, [r for r in _load_override_rules().get("terms", [])
                                            if r.get("scope", "suggested") == "suggested"])
    _apply_overton_term_overrides(main_content)
    _apply_overton_term_overrides(archive)
    # Oct 27 2026: mainContent insights carried tickers_mentioned as a JSON string; export lists.
    for _part in (archive, main_content, deepdives):
        _normalize_tickers_mentioned(_part)
    _drop_terms_pinned_as_curated(suggested_terms)
    # Load pundits (semantic layer) from JSON exported by export_for_website
    pundits_path = site_dir / "pundits.json"
    try:
        with open(pundits_path, "r") as f:
            pundits = sanitize_public_text(json.load(f))
        _apply_summary_overrides(pundits)
    except FileNotFoundError:
        pundits = []

    # Chart metadata for cache-busting
    charts_version = None
    last_chart_run_path = STATE_DIR / "last_chart_run.json"
    if last_chart_run_path.exists():
        try:
            with open(last_chart_run_path, "r") as f:
                meta = json.load(f)
            charts_version = meta.get("timestamp")
        except Exception:
            charts_version = None

    # NOTE: ticker_scores.json no longer exported — Alpha/Atrophy UI retired in PR #98
    # (replaced by Trap Map). tickerScores in data.js is now an empty array with a comment.

    # Intraday prices for header tickers (same file fetch_prices.py writes; keeps index on one bundle)
    # Fail-closed: never embed {} / missing QQQ|BTC — keep prior data.js snapshot or refuse empty publish.
    price_snapshot: dict = {}
    price_path = SITE_ROOT / "price_data.json"
    price_load_err: str | None = None
    if price_path.is_file():
        try:
            raw_text = price_path.read_text(encoding="utf-8")
            if "<<<<<<<" in raw_text or "=======" in raw_text or ">>>>>>>" in raw_text:
                raise ValueError("price_data.json has unresolved git conflict markers")
            raw_prices = json.loads(raw_text)
            if isinstance(raw_prices, dict):
                price_snapshot = dict(raw_prices)
                price_snapshot.pop("_metadata", None)
        except Exception as e:
            price_load_err = str(e)
            price_snapshot = {}
            print(f"  ⚠ price_data.json unusable ({e}); will try prior data.js priceSnapshot")

    def _snapshot_has_banner(snap: dict) -> bool:
        if not isinstance(snap, dict) or not snap:
            return False
        qqq = snap.get("QQQ")
        btc = snap.get("BTC") or snap.get("BTC-USD")
        def _ok(entry) -> bool:
            return isinstance(entry, dict) and entry.get("price") is not None
        return _ok(qqq) and _ok(btc)

    if not _snapshot_has_banner(price_snapshot):
        prev_path = site_dir / "data.js"
        prev_snap: dict = {}
        if prev_path.is_file():
            try:
                prev_text = prev_path.read_text(encoding="utf-8")
                marker = "priceSnapshot:"
                idx = prev_text.find(marker)
                if idx >= 0:
                    brace = prev_text.find("{", idx)
                    depth = 0
                    end = None
                    for i, c in enumerate(prev_text[brace:], brace):
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                    if end is not None:
                        prev_snap = json.loads(prev_text[brace:end])
            except Exception as e:
                print(f"  ⚠ Could not recover prior priceSnapshot from data.js: {e}")
        if _snapshot_has_banner(prev_snap):
            print(
                "  ⚠ New priceSnapshot missing QQQ/BTC"
                + (f" ({price_load_err})" if price_load_err else "")
                + f"; keeping prior data.js snapshot ({len(prev_snap)} tickers)"
            )
            price_snapshot = prev_snap
        else:
            raise RuntimeError(
                "Refuse to write data.js: priceSnapshot missing QQQ and/or BTC "
                "(price_data.json empty/corrupt and no usable prior snapshot). "
                "Run fetch_prices.py, then retry export."
            )
    else:
        print(f"  ✓ priceSnapshot ready ({len(price_snapshot)} tickers, QQQ+BTC present)")

    price_json = json.dumps(price_snapshot, indent=2)
    
    # Portfolio baskets (Healthcare Abundance, etc.)
    portfolio_data: dict = {}
    portfolio_path = site_dir / "portfolio.json"
    if portfolio_path.is_file():
        try:
            portfolio_data = json.loads(portfolio_path.read_text(encoding="utf-8"))
            portfolio_data.pop("_metadata", None)
        except Exception:
            portfolio_data = {}
    portfolio_json = json.dumps(portfolio_data, indent=2)
    
    # Generate data.js that the HTML can load
    # Pre-serialize to avoid f-string issues
    archive_json = json.dumps(archive, indent=2)
    main_json = json.dumps(main_content, indent=2)
    deepdives_json = json.dumps(deepdives, indent=2)
    suggested_json = json.dumps(suggested_terms, indent=2)
    podcast_guests_json = json.dumps(podcast_guests, indent=2)
    pundits_json = json.dumps(pundits, indent=2)

    schema_version = 2

    js_content = f"""// Auto-generated data file
// DO NOT EDIT MANUALLY

const dashboardData = {{
  schemaVersion: {schema_version},
  generatedAt: "{datetime.now().isoformat()}",
  chartsVersion: {json.dumps(charts_version) if 'charts_version' in locals() else 'null'},
  priceSnapshot: {price_json},
  tickerScores: [],
  archive: {archive_json},
  mainContent: {main_json},
  deepDives: {deepdives_json},
  suggestedTerms: {suggested_json},
  podcastGuests: {podcast_guests_json},
  pundits: {pundits_json},
  portfolio: {portfolio_json}
}};

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {{
  module.exports = dashboardData;
}}
"""
    
    for _sec in (archive, main_content, deepdives, suggested_terms, podcast_guests, pundits):
        apply_style_gate(_sec)  # warn-only: flags 'bet' wording, never rewrites
    report_style_gate_misses()

    with open(site_dir / 'data.js', 'w') as f:
        f.write(js_content)

    bump_data_js_cache_in_site_html()
    
    total_archive = sum(len(v) for v in archive.values() if isinstance(v, list))
    print(f"✓ Generated data.js with {total_archive} archive items, {len(deepdives)} deep dives, {len(suggested_terms)} suggested terms, {len(podcast_guests)} legacy guests, {len(pundits)} pundits; chartsVersion={charts_version}")
    return True


def main():
    """Run data export."""
    print(f"Data Export Started: {datetime.now()}")
    
    export_website_data()
    generate_website_js()
    # Market Commentary: newest commentary/YYYY-MM-DD.md -> site/data/commentary/latest.json
    try:
        import export_commentary
        export_commentary.main([])
    except Exception as e:
        print(f"  ⚠ commentary export skipped: {e}")
    
    print(f"\n✓ Data export complete")


if __name__ == "__main__":
    main()
