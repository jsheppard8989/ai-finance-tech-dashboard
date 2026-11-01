"""Oct 31 2026 (sweep_1031 R1-R4, Jared approved): card 528 fixes come from summary_overrides.json at export."""
import json
from pathlib import Path
import export_data
import publish_guard

KT = ("Eric Wallerstein says a garden-variety bear market is increasingly his base case, "
      "driven by fiscal drag, energy-supply shocks and rate hikes.")


def _card():
    return {"archive": {"insights": [{"id": 528, "podcast_episode_id": 513, "title": "Energy Shock",
                                      "summary": "In this episode, Jack Farley discusses the bear market.",
                                      "key_takeaway": ""}]},
            "deepDives": {"528": {"id": 517, "insight_id": 528, "podcast_episode_id": 513,
                                  "ticker_analysis": {"NVDA": {"rationale": "NVIDIA represents a strong investment opportunity, as it stands at the forefront of the AI boom."}},
                                  "catalysts": ["Fed meeting on November 1, 2023, where new interest rate guidance may be issued."]}}}


def test_card_528_r1_to_r4_and_idempotent():
    d = _card()
    export_data._apply_summary_overrides(d)
    a = d["archive"]["insights"][0]
    assert a["summary"] == "In this episode, Jack Farley and guest Eric Wallerstein discuss the bear market."
    assert a["key_takeaway"] == KT
    dd = d["deepDives"]["528"]
    assert dd["ticker_analysis"]["NVDA"]["rationale"] == "NVIDIA stands at the forefront of the AI boom."
    assert dd["catalysts"] == []
    snap = json.dumps(d)
    export_data._apply_summary_overrides(d)
    assert json.dumps(d) == snap


def test_set_key_takeaway_never_overwrites():
    d = _card()
    d["archive"]["insights"][0]["key_takeaway"] = "Existing text."
    export_data._apply_summary_overrides(d)
    assert d["archive"]["insights"][0]["key_takeaway"] == "Existing text."


def test_live_data_js_card_528():
    root = Path(__file__).resolve().parent.parent
    D = publish_guard.parse_data_js((root / "site/data/data.js").read_text(encoding="utf-8"))
    a = [i for i in D["archive"]["insights"] if i.get("id") == 528][0]
    assert a["key_takeaway"] == KT and "Jack Farley discusses" not in a["summary"]
    dd = [v for v in D["deepDives"].values() if v.get("insight_id") == 528][0]
    assert dd["catalysts"] == [] and "strong investment opportunity" not in json.dumps(dd)
