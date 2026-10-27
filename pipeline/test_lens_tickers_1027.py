"""Oct 27 2026 follow-up 3 (G, sweep_1027): LENS (Sarmaya Thematic ETF) is the Monetary Matters
sponsor; in episodes 608 (insight 617, George Noble), 544 (insight 560, Ed Zitron) and 559
(insight 569, J Mintzmyer) the transcript mentions it only inside the sponsor reads, so it is
dropped from those episodes' tickers by id. Also: tickers_mentioned is always exported as a list."""
import copy
import json

import export_data

TARGETS = [(617, 608), (560, 544), (569, 559), (600, 589)]  # 600: follow-up 4 (Jim Bianco)


def _payload():
    cards, dds, eps = [], {}, []
    for iid, pe in TARGETS + [(900, 900)]:
        cards.append({"id": iid, "podcast_episode_id": pe, "title": f"t{iid}",
                      "tickers_mentioned": ["NVDA", "LENS"], "key_tickers": ["LENS", "NVDA"]})
        dds[str(iid)] = {"id": iid + 1, "insight_id": iid, "podcast_episode_id": pe, "insight_title": f"t{iid}",
                         "key_tickers": ["LENS", "NVDA"],
                         "ticker_analysis": {"NVDA": {"rationale": "a"}, "LENS": {"rationale": "b"}}}
        eps.append({"id": pe, "podcast_name": "Monetary Matters", "episode_title": f"t{iid}",
                    "key_tickers": ["NVDA", "LENS"]})
    main = [dict(cards[0], tickers_mentioned=json.dumps(["NVDA", "LENS"]))]
    return {"archive": {"insights": cards}, "mainContent": {"insights": main}, "deepDives": dds, "eps": eps}


def test_lens_dropped_for_sponsor_only_episodes_by_id():
    data = _payload()
    export_data._apply_summary_overrides(data)
    export_data._normalize_tickers_mentioned(data)
    by = {c["id"]: c for c in data["archive"]["insights"]}
    eps = {e["id"]: e for e in data["eps"]}
    for iid, pe in TARGETS:
        assert by[iid]["tickers_mentioned"] == ["NVDA"]
        assert by[iid]["key_tickers"] == ["NVDA"]
        assert data["deepDives"][str(iid)]["key_tickers"] == ["NVDA"]
        assert list(data["deepDives"][str(iid)]["ticker_analysis"]) == ["NVDA"]
        assert eps[pe]["key_tickers"] == ["NVDA"]
    assert data["mainContent"]["insights"][0]["tickers_mentioned"] == ["NVDA"]
    # an unrelated episode keeps LENS (no global drop)
    assert by[900]["tickers_mentioned"] == ["NVDA", "LENS"]
    assert "LENS" in data["deepDives"]["900"]["ticker_analysis"]
    assert eps[900]["key_tickers"] == ["NVDA", "LENS"]
    once = copy.deepcopy(data)
    export_data._apply_summary_overrides(data)
    export_data._normalize_tickers_mentioned(data)
    assert data == once


def test_lens_rules_are_id_keyed_not_global():
    rules = json.load(open(export_data.Path(export_data.__file__).parent / "summary_overrides.json"))
    assert "LENS" not in [t.upper() for t in rules.get("global_drop_tickers", [])]
    have = {(r.get("insight_id"), r.get("podcast_episode_id")) for r in rules["summaries"]
            if "LENS" in (r.get("drop_tickers") or [])}
    assert set(TARGETS) | {(622, 611)} <= have


def test_normalize_tickers_mentioned():
    data = {"mainContent": {"insights": [
        {"id": 1, "tickers_mentioned": '["NVDA", "TSLA"]'},
        {"id": 2, "tickers_mentioned": "[]"},
        {"id": 3, "tickers_mentioned": ""},
        {"id": 4, "tickers_mentioned": "AAPL, MSFT"},
        {"id": 5, "tickers_mentioned": ["META"]},
        {"id": 6, "tickers_mentioned": None},
    ]}}
    assert export_data._normalize_tickers_mentioned(data) == 4
    got = [i["tickers_mentioned"] for i in data["mainContent"]["insights"]]
    assert got == [["NVDA", "TSLA"], [], [], ["AAPL", "MSFT"], ["META"], None]
    assert export_data._normalize_tickers_mentioned(data) == 0


def test_deep_dive_600_lens_analysis_dropped_keeps_wtbn():
    """Follow-up 4: deep dive 600 had LENS only in ticker_analysis (key_tickers is WTBN)."""
    data = {"deepDives": {"600": {"id": 600, "insight_id": 600, "podcast_episode_id": 589, "insight_title": "Bianco",
                                  "key_tickers": ["WTBN"],
                                  "ticker_analysis": {"WTBN": {"rationale": "a"}, "LENS": {"rationale": "b"}}}},
            "priceSnapshot": {"LENS": {"price": 1.0}}}
    export_data._apply_summary_overrides(data)
    dd = data["deepDives"]["600"]
    assert dd["key_tickers"] == ["WTBN"] and list(dd["ticker_analysis"]) == ["WTBN"]
    assert "LENS" in data["priceSnapshot"]  # price data untouched
