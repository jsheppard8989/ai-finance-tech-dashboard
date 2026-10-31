"""Oct 31 2026: deep dive 644 overview 'They are betting that...' blocked the Mac publish (style gate).
Quote-safe phrase swap via name_replacements."""
import copy
import export_data
import publish_guard

OLD = "They are betting that the future of professional discovery runs through AI agents."
NEW = "Their view is that the future of professional discovery runs through AI agents."
QUOTE = '"They are betting that the future of professional discovery is ours," he said.'


def _payload():
    return {"deepDives": {"644": {"id": 644, "insight_id": 644, "podcast_episode_id": 9644,
                                  "insight_title": "t", "overview": "Intro. " + OLD,
                                  "notable_quotes": [{"quote": "They are betting that the future of professional work changes", "speaker": "X"}]}},
            "archive": {"insights": [{"id": 1, "summary": QUOTE}]}}


def test_dd644_overview_swapped_and_idempotent():
    d = _payload()
    export_data._apply_summary_overrides(d)
    assert d["deepDives"]["644"]["overview"] == "Intro. " + NEW
    once = copy.deepcopy(d)
    export_data._apply_summary_overrides(d)
    assert d == once


def test_dd644_quotes_untouched():
    d = _payload()
    export_data._apply_summary_overrides(d)
    assert d["deepDives"]["644"]["notable_quotes"][0]["quote"].startswith("They are betting that")
    assert d["archive"]["insights"][0]["summary"] == QUOTE


def test_dd644_passes_style_gate():
    d = _payload()
    export_data._apply_summary_overrides(d)
    assert not publish_guard.find_style_gate_hits({"overview": d["deepDives"]["644"]["overview"]})
    assert publish_guard.find_style_gate_hits({"overview": "Intro. " + OLD})
