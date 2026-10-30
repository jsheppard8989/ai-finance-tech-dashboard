"""Oct 30 2026 daily site check (cos/sweep_1030/fixes.md) #8-#15: cards 631-639. Tickers, sentiment,
plain-language wording and speaker labels; quote text changes only where G listed the word. Scoped, idempotent."""
import copy
import json
from pathlib import Path

import export_data
import publish_guard

ROOT = Path(__file__).resolve().parent.parent


def _cards():
    a = json.loads((ROOT / "site" / "data" / "archive.json").read_text(encoding="utf-8"))
    return [copy.deepcopy(r) for r in a["insights"] if 631 <= r["id"] <= 639]


def _run(cards):
    data = {"archive": {"insights": cards}}
    export_data._apply_summary_overrides(data)
    export_data._normalize_tickers_mentioned(data)
    return data


def _q(c):
    q = c.get("notable_quotes") or []
    return json.loads(q) if isinstance(q, str) else q


def test_cards_631_639():
    data = _run(_cards())
    by = {c["id"]: c for c in data["archive"]["insights"]}
    blob = json.dumps(data, ensure_ascii=False)
    for old in ("Woop", "Anthropica", "Steve Ho(head)", "support the capex cycle", "at the EBITDA level", "NuBank",
                "20 bps drop", "Defense-led capex is de-risking", "de-risk capex", "Dwarkesh Podcast host"):
        assert old not in blob, old
    assert by[639]["tickers_mentioned"] == []
    assert any(q["quote"].startswith("On average, a [WHOOP] member wears [WHOOP] 23.6 hours a day") for q in _q(by[639]))
    assert by[634]["tickers_mentioned"] == []
    assert by[631]["tickers_mentioned"] == ["MU"]
    assert any(q["quote"].startswith("[Anthropic] now earns $2.8 in revenue") for q in _q(by[631]))
    assert [q["speaker"] for q in _q(by[632])][:2] == ["Steve Hou", "Steve Hou"]
    assert "support the AI spending cycle" in by[632]["key_takeaway"]
    assert "before counting the wear-out of its equipment" in by[632]["summary"]
    assert by[632]["sentiment"] == "positive"
    assert "Nubank" in by[638]["summary"] and "Nubank" in by[638]["key_takeaway"]
    assert by[637]["sentiment"] == "negative"
    assert "0.20 percentage-point drop in the 10-year Treasury yield" in by[637]["summary"]
    assert by[635]["key_takeaway"].startswith("Defense spending is lowering the risk of building") or \
        "Defense spending is lowering the risk of building" in by[635]["key_takeaway"]
    assert "lower the risk of building factories" in by[635]["summary"]
    assert by[635]["sentiment"] == "positive"
    assert {q["speaker"] for q in _q(by[636])} == {"Dwarkesh Patel"}
    once = copy.deepcopy(data)
    _run(data["archive"]["insights"])
    assert data == once
    assert publish_guard.find_style_gate_hits(data["archive"]) == []


def test_other_quote_text_unchanged():
    before = {c["id"]: _q(c) for c in _cards()}
    after = {c["id"]: _q(c) for c in _run(_cards())["archive"]["insights"]}
    fixed = {"a Woop member wears Woop": "a [WHOOP] member wears [WHOOP]", "Anthropica now earns": "[Anthropic] now earns"}
    for i, qs in before.items():
        for b, a in zip(qs, after[i]):
            t = b["quote"]
            for o, n in fixed.items():
                t = t.replace(o, n)
            assert a["quote"] == t
