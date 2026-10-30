"""Oct 30 2026: last 'open AI' strings. Card 381 (Hugging Face) names the companies -> [Anthropic]/[OpenAI];
404/450/473 mean open-source AI. Scoped by insight+episode; no overlap with the card 601 rule."""
import copy

from export_data import _apply_summary_overrides

CASES = [
    (381, 366, "episode_evidence", ["'...the hugging face security team tried to analyze the attack, using either anthropic or open AI, both models refused.' This incident"],
     ["'...the hugging face security team tried to analyze the attack, using either [Anthropic] or [OpenAI], both models refused.' This incident"]),
    (404, 389, "summary", "touches on model licensing, inference economics, and the future of open AI.",
     "touches on model licensing, inference economics, and the future of open-source AI."),
    (450, 436, "falsification_tracks", ["A significant regulatory crackdown specifically targeting open AI models across Western countries"],
     ["A significant regulatory crackdown specifically targeting open-source AI models across Western countries"]),
    (473, 458, "investment_thesis", "firms that build open AI architectures and routing technologies",
     "firms that build open-source AI architectures and routing technologies"),
]


def test_open_ai_wording_scoped_and_idempotent():
    recs = [{"id": i, "insight_id": i, "podcast_episode_id": ep, k: copy.deepcopy(old)} for i, ep, k, old, _ in CASES]
    other = {"id": 999, "insight_id": 999, "podcast_episode_id": 999, "summary": "the future of open AI."}
    data = {"deepDives": recs + [other]}
    _apply_summary_overrides(data)
    for r, (_, _, k, _, new) in zip(data["deepDives"], CASES):
        assert r[k] == new
    assert other["summary"] == "the future of open AI."
    once = copy.deepcopy(data)
    _apply_summary_overrides(data)
    assert data == once
