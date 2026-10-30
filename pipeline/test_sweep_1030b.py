"""Oct 30 2026 publish unblock: card 640 'open AI' (same swap as card 601) and pundit 591 'Steve Houhead'."""
import json
from pathlib import Path

from export_data import _apply_summary_overrides

ROOT = Path(__file__).resolve().parent.parent
Q = "Anyone who thinks that meta-open AI andthropic or Elon's got neural"


def _card(iid=640, ep=629, quote=Q):
    return {"id": iid, "podcast_episode_id": ep, "summary": "s", "key_takeaway": "k",
            "notable_quotes": [{"speaker": "Guest", "quote": quote}]}


def test_card_640_openai_name_fix_scoped_and_idempotent():
    data = {"archive": {"insights": [_card(), _card(9404, 9389, "the future of open AI.")]}}
    _apply_summary_overrides(data)
    c640, c404 = data["archive"]["insights"]
    assert c640["notable_quotes"][0]["quote"] == "Anyone who thinks that meta-OpenAI Anthropic or Elon's got neural"
    assert c404["notable_quotes"][0]["quote"] == "the future of open AI."  # other cards untouched
    once = json.dumps(data)
    _apply_summary_overrides(data)
    assert json.dumps(data) == once


def test_steve_hou_pundit_name_and_snippet():
    rec = [{"id": 591, "name": "Steve Houhead", "slug": "steve-houhead", "mention_score": 1,
            "bio": "Research at Silicon Data.", "last_proof_snippet": "Steve Houhead of Silicon Data said",
            "last_episode_title": "Why Compute Prices Are Still Rising | Steve Hou of Silicon Data"}]
    _apply_summary_overrides(rec)
    assert rec[0]["name"] == "Steve Hou"
    assert "Houhead" not in rec[0]["last_proof_snippet"]
    assert rec[0]["slug"] == "steve-houhead"  # slugs/URLs are never rewritten


def test_rules_present():
    d = json.loads((ROOT / "pipeline" / "summary_overrides.json").read_text(encoding="utf-8"))
    assert ["Steve Houhead", "Steve Hou"] in d["global_name_replacements"]
    assert ["Steve Houhead", "Steve Hou"] in d["name_replacements"]
