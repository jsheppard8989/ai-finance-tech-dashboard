"""Tests for pipeline/summary_overrides.json handling in export_data.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

TITLE = "Martin Shkreli: Big Pharma's Blind Spot, Betting Against Quantum & What Prison Taught Him"


def test_takeaways_list_and_string_are_overridden():
    rec = {
        "episode_title": TITLE,
        "summary": "x",
        "key_takeaways": ["saying MATMO-style systems could outperform GPUs and that H100-class Nvidia chips"],
        "key_takeaway": "MATMO-style systems",
    }
    export_data._apply_summary_overrides({"items": [rec]})
    assert rec["key_takeaways"][0] == "saying matrix-multiplication systems could outperform GPUs and that H100-class Nvidia chips"
    assert rec["key_takeaway"] == "matrix-multiplication systems"


def test_takeaways_repr_string_is_overridden():
    rec = {"title": TITLE, "key_takeaways": "['MATMO-style systems and H100-class']"}
    export_data._apply_summary_overrides([rec])
    assert rec["key_takeaways"] == "['matrix-multiplication systems and H100-class']"


def test_other_episodes_untouched():
    rec = {"title": "Other", "key_takeaways": ["MATMO-style systems"]}
    export_data._apply_summary_overrides([rec])
    assert rec["key_takeaways"] == ["MATMO-style systems"]


def test_term_override():
    terms = [{"id": 888, "term": "MATMO", "definition": "old"}, {"term": "Other", "definition": "keep"}]
    export_data._apply_term_overrides(terms)
    assert terms[0]["term"] == "Photonic matrix-multiplication cores"
    assert "MATMO" not in json.dumps(terms)
    assert terms[1] == {"term": "Other", "definition": "keep"}


def test_site_data_has_no_matmo():
    data_dir = Path(__file__).parent.parent / "site" / "data"
    for name in ("data.js", "podcast_summaries.json", "archive.json"):
        assert "MATMO" not in (data_dir / name).read_text(encoding="utf-8"), name
