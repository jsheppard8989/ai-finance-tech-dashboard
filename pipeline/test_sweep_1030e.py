"""Oct 30 2026: card 622 (Citrini, 'Monkeys Are The Next Bottleneck') semis stance wording. Scoped by insight+episode."""
import copy

from export_data import _apply_summary_overrides

OLD = "he remains selectively bullish on semiconductors but is more focused on AI usage and agentic utilities than on the broad infrastructure stack."
NEW = ("he has rotated out of most semiconductor stocks since about March and is short some AI hardware, though he says he is "
       "still bullish on Nvidia. His focus is now on AI usage and what he calls agentic utilities.")


def test_card_622_wording_scoped_and_idempotent():
    rec = {"id": 622, "insight_id": 622, "podcast_episode_id": 611, "summary": "Citrini says " + OLD}
    other = {"id": 999, "insight_id": 999, "podcast_episode_id": 999, "summary": "Citrini says " + OLD}
    data = {"deepDives": [rec, other]}
    _apply_summary_overrides(data)
    assert rec["summary"] == "Citrini says " + NEW
    assert OLD not in rec["summary"]
    assert other["summary"] == "Citrini says " + OLD
    once = copy.deepcopy(data)
    _apply_summary_overrides(data)
    assert data == once
