"""Oct 27 2026 follow-up (G, sweep_1027): Joe Liemandt pundit (DB entity 582 is ASR 'Joel Amond')
via a confirmed guest appearance + id-keyed name/slug rule; plus 624 line cut, LENS dropped from 622,
623 quote #1 removed and pundit 580's takeaway blanked (episode-gated). DB untouched."""
import copy, json
import export_data
import pundit_exclusions

TITLE_615 = "Reinventing School for the AI Era | Joe Liemandt, Gagan Biyani & Erik Torenberg"
SENT_624 = ('He also highlighted a capability gradient across models: better models do not merely jump around '
            'more, but "abandon the lousy places fast," implying some level of improved inference about where not to search. ')


def _row(pid, title, **kw):
    return dict({"id": pid, "name": f"p{pid}", "slug": f"p{pid}", "mention_score": 1,
                 "last_episode_title": title}, **kw)


def test_joel_amond_is_a_confirmed_guest_on_615():
    assert pundit_exclusions.is_confirmed_guest_appearance("Joel Amond", TITLE_615)
    assert not pundit_exclusions.is_confirmed_guest_appearance("Joel Amond", "Some other episode")
    assert not pundit_exclusions.is_excluded_pundit(582, "Joe Liemandt")


def test_582_named_joe_liemandt_everywhere():
    rows = {"pundits": [_row(582, TITLE_615, name="Joel Amond", slug="joel-amond",
                             bio="Founder of Alpha School.",
                             supporting_takeaway="Joel Amond reported that 90% of Alpha students love school.",
                             last_proof_snippet="Amond said it.", last_proof_cite="The a16z Show • 2026-10-27 • " + TITLE_615)]}
    export_data._apply_summary_overrides(rows)
    p, = rows["pundits"]
    assert p["name"] == "Joe Liemandt" and p["slug"] == "joe-liemandt"
    assert p["supporting_takeaway"] == "Joe Liemandt reported that 90% of Alpha students love school."
    assert "Amond" not in json.dumps(p)
    once = copy.deepcopy(rows)
    export_data._apply_summary_overrides(rows)
    assert rows == once


def test_580_takeaway_blanked_only_on_its_episode():
    t = "OpenAI: When AI Agents Use Computers Faster Than You"
    rows = {"pundits": [_row(580, t, supporting_takeaway="James Sun says fewer thinking tokens.",
                             last_proof_snippet="x.", last_proof_cite="c")]}
    export_data._apply_summary_overrides(rows)
    assert not rows["pundits"][0].get("supporting_takeaway")
    rows = {"pundits": [_row(580, "A later episode", supporting_takeaway="New takeaway.")]}
    export_data._apply_summary_overrides(rows)
    assert rows["pundits"][0]["supporting_takeaway"] == "New takeaway."


def _cards():
    return {
        "archive": {"insights": [
            {"id": 624, "podcast_episode_id": 614, "title": "Leash", "summary": "Intro. " + SENT_624 + "Leash has screened."},
            {"id": 622, "podcast_episode_id": 611, "title": "Citrini", "tickers_mentioned": ["CRL", "META", "LENS"]},
            {"id": 623, "podcast_episode_id": 612, "title": "OpenAI", "notable_quotes": [
                {"speaker": "James Sun", "quote": "One is it is a little bit faster on average because it uses fewer thinking tokens to do the same task."},
                {"speaker": "James Sun", "quote": "If you look at the system card for it."}]},
            {"id": 617, "podcast_episode_id": 608, "title": "Noble", "tickers_mentioned": ["NVDA", "LENS"]},
        ]},
        "deepDives": {
            "624": {"id": 624, "insight_id": 624, "podcast_episode_id": 614, "insight_title": "x",
                    "episode_evidence": "Ian Quigley: Before.\nIan Quigley: But they especially abandon the lousy places fast. And then more."},
            "622": {"id": 622, "insight_id": 622, "podcast_episode_id": 611, "insight_title": "y",
                    "ticker_analysis": {"CRL": {"rationale": "a"}, "LENS": {"rationale": "LENS is included"}}},
        },
    }


def test_card_cuts_scoped_and_idempotent():
    data = _cards()
    export_data._apply_summary_overrides(data)
    ins = {i["id"]: i for i in data["archive"]["insights"]}
    assert ins[624]["summary"] == "Intro. Leash has screened."
    assert data["deepDives"]["624"]["episode_evidence"] == "Ian Quigley: Before.\nIan Quigley: And then more."
    assert ins[622]["tickers_mentioned"] == ["CRL", "META"]
    assert "LENS" not in json.dumps(data["deepDives"]["622"])
    assert ins[617]["tickers_mentioned"] == ["NVDA", "LENS"]  # other episodes keep LENS
    assert [q["quote"] for q in ins[623]["notable_quotes"]] == ["If you look at the system card for it."]
    once = copy.deepcopy(data)
    export_data._apply_summary_overrides(data)
    assert data == once
