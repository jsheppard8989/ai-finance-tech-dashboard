"""Nov 17 2026 (G): export unblock. Ep 689 / card 702 ASR names, stored and live forms."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

TITLE = "Can AI Learn to Improve Itself? | Recursive Self-Improvement"
Q = "Andthropic published research in August, showing that automated AI researchers could already discover fixes"
SNIP_LIVE = ("In this first episode of Working Theory, Sarah Wang sits down with Open AI's Mark Chen "
             "and thinking machine's John Schulman to unpack recursive self-improvement or RSI.")
SNIP_STORED = SNIP_LIVE.replace("Mark Chen and", "Mark Chen\nand")


def test_702_quote_and_evidence():
    card = {"id": 702, "podcast_episode_id": 689, "title": TITLE,
            "notable_quotes": [{"speaker": "one host", "quote": Q}]}
    dd = {"insight_id": 702, "podcast_episode_id": 689,
          "episode_evidence": "their work is producing better models.\none host: " + Q}
    export_data._apply_summary_overrides([card, dd])
    assert card["notable_quotes"][0]["quote"].startswith("Anthropic published research in August")
    assert "one host: Anthropic published research in August" in dd["episode_evidence"]


def test_pundit_snippet_live_and_stored_forms():
    rows = [{"name": "Mark Chen", "last_proof_snippet": SNIP_LIVE},
            {"name": "John Schulman", "last_proof_snippet": SNIP_STORED}]
    export_data._apply_summary_overrides(rows)
    assert "with OpenAI's Mark Chen and Thinking Machines' John Schulman to unpack" in rows[0]["last_proof_snippet"]
    assert "OpenAI's Mark Chen\nand Thinking Machines' John Schulman" in rows[1]["last_proof_snippet"]


def test_levie_title_left_as_published():
    # a16z feed title is literally "Aaron Levie on Why Open AI Wins"; titles are not rewritten.
    rec = [{"id": 473, "title": "Aaron Levie on Why Open AI Wins"}]
    export_data._apply_summary_overrides(rec)
    assert rec[0]["title"] == "Aaron Levie on Why Open AI Wins"
