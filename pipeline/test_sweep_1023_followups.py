"""Oct 23 2026 sweep follow-ups (cos/verify_1023): c21 paraphrases, c23 debait names/Ukraine,
non-quote 'thin'. Fixes live in summary_overrides.json / pundit_exclusions.py / debate_history.json
and re-apply on export from the pre-fix files."""
import json, re, subprocess
from pathlib import Path
import pytest
import export_data
from pundit_exclusions import is_excluded_pundit_name

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PRE = "62cd22b"  # origin/main before these follow-ups (#575)
OLD_QUOTES = (
    "Tenex’s AI strategists are responsible for customer retention and growth, giving them",
    "Plans and decisions are checked into Git alongside the code.",
    "Real workloads behave differently",
)
GARBLED = ("Honorable Duffy", "Mavruchus", "Yuternoff")


def _git(path):
    r = subprocess.run(["git", "show", f"{PRE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pre-fix snapshot not available")
    return r.stdout


def _old(path):
    return json.loads(_git(path))


def _fix(obj):
    out = export_data._apply_summary_overrides(obj)
    return out if out is not None else obj


def _datajs_sections(text):
    keys = ["archive", "mainContent", "deepDives", "suggestedTerms", "podcastGuests", "pundits", "portfolio"]
    out = {}
    for i, k in enumerate(keys):
        a = re.search(r"\n  %s: " % k, text).end()
        b = re.search(r"\n  %s: " % keys[i + 1], text).start() if i + 1 < len(keys) else text.rindex("\n};")
        body = text[a:b].rstrip()
        out[k] = json.loads(body[:-1] if body.endswith(",") else body)
    return out


def _current_datajs():
    return _datajs_sections((SITE / "data" / "data.js").read_text(encoding="utf-8"))


def _insights(arch):
    return {i["id"]: i for i in arch.get("insights", [])}


def test_paraphrases_become_summaries_on_export():
    ins = _insights(_fix(_old("site/data/archive.json")))
    for iid, speaker in ((606, "Alex Lieberman"), (606, "CJ Hess"), (614, "Erik Bernhardsson")):
        qs = [q for q in ins[iid]["notable_quotes"] if q.get("paraphrase") and q["speaker"] == speaker]
        assert len(qs) == 1, (iid, speaker)
        assert qs[0]["quote"].startswith(speaker + " ")  # framed as a summary naming the speaker
    text = json.dumps(ins[606], ensure_ascii=False) + json.dumps(ins[614], ensure_ascii=False)
    for q in OLD_QUOTES:
        assert q not in text
    # real direct quotes stay direct quotes
    assert any(not q.get("paraphrase") and q["quote"].startswith("Sandboxes is now") for q in ins[614]["notable_quotes"])


def test_deep_dive_evidence_lines_are_summaries():
    dd = _fix(_datajs_sections(_git("site/data/data.js"))["deepDives"])
    ev = dd["606"]["episode_evidence"] + dd["614"]["episode_evidence"]
    for bad in ("CJ Hess: Plans", "Alex Lieberman: Tenex", "Erik Bernhardsson: Real workloads"):
        assert bad not in ev
    assert "Lieberman argued" in ev and "Bernhardsson argued" in ev


def test_paraphrase_rule_idempotent_and_handles_json_strings():
    pairs = [["Plans and decisions", "CJ Hess said X."]]
    once = export_data._paraphrase_quotes([{"speaker": "CJ Hess", "quote": "Plans and decisions are here."}], pairs)
    assert once == [{"speaker": "CJ Hess", "quote": "CJ Hess said X.", "paraphrase": True}]
    assert export_data._paraphrase_quotes(once, pairs) == once
    s = export_data._paraphrase_quotes(json.dumps([{"speaker": "A", "quote": "Plans and decisions"}]), pairs)
    assert json.loads(s)[0]["paraphrase"] is True


def test_renderer_drops_quote_marks_for_paraphrases():
    js = (SITE / "js" / "common.js").read_text(encoding="utf-8")
    assert "paraphrase: !!q.paraphrase" in js
    i = js.index("if (q.paraphrase)")
    block = js[i:js.index("return;", i)]
    assert "insight-paraphrase" in block and "&ldquo;" not in block


def test_committed_site_data_matches():
    d = _current_datajs()
    blob = json.dumps(d, ensure_ascii=False)
    for q in OLD_QUOTES:
        assert q not in blob
    for f in ("archive.json", "pundits.json"):
        t = json.dumps(json.loads((SITE / "data" / f).read_text()), ensure_ascii=False)
        for q in OLD_QUOTES + GARBLED:
            assert q not in t, (f, q)
    for g in GARBLED:
        assert g.lower() not in blob.lower()


def test_debait_history_garbled_names_and_ukraine_removed():
    t = (SITE / "debate_history.json").read_text(encoding="utf-8")
    for g in GARBLED + ("Ukraine",):
        assert g not in t
    weeks = json.loads(t)["weeks"]
    assert not any(w.get("friday_iso") == "2026-05-29" for w in weeks)
    btc = [w for w in weeks if w.get("friday_iso") == "2026-07-17"][0]
    assert btc["debater_b"] == ""  # renders as "—"; no guessed name
    assert "Ukraine" in _git("site/debate_history.json")  # the pre-fix file had it


def test_garbled_pundits_dropped_on_export():
    old = {p["id"]: p for p in _old("site/data/pundits.json")}
    assert old[255]["name"] == "Dino Mavruchus" and old[256]["name"] == "Honorable Duffy"
    new = {p["id"]: p for p in _fix(_old("site/data/pundits.json"))}
    assert 255 not in new and 256 not in new
    assert new[317]["slug"] == "sergey-edunov"
    assert is_excluded_pundit_name("Dino Mavruchus") and is_excluded_pundit_name("Honorable Duffy")
    assert not is_excluded_pundit_name("Sergey Edunov")
    dd = _fix(_datajs_sections(_git("site/data/data.js"))["deepDives"])
    assert "Mavruchus" not in dd["243"]["episode_evidence"]
    assert "One guest states, 'You have to bend" in dd["243"]["episode_evidence"]


def test_thin_rewordings():
    dd = _fix(_datajs_sections(_git("site/data/data.js"))["deepDives"])
    assert "a light workflow layer" in dd["608"]["investment_thesis"]
    assert "is running out" in dd["441"]["overview"]
    assert "the very low margins in retail" in dd["323"]["episode_evidence"]
    farris = [p for p in _fix(_old("site/data/pundits.json")) if p["id"] == 449][0]
    assert "low global grain reserves" in json.dumps(farris, ensure_ascii=False)


def _strings(o, path=""):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _strings(v, f"{path}[{i}]")
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, f"{path}.{k}")


def test_no_thin_outside_quotes_and_titles():
    d = _current_datajs()
    hits = []
    for path, s in _strings(d):
        if "notable_quotes" in path or "title" in path.lower() or "url" in path.lower() or "source" in path.lower():
            continue
        # strip single/double-quoted spans (direct quotes inside prose)
        prose = re.sub(r"'[^']*'|\"[^\"]*\"|“[^”]*”|‘[^’]*’", "", s)
        if re.search(r"\bthin\b", prose, re.I):
            hits.append(path)
    assert hits == [], hits
