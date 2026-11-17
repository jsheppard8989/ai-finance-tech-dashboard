"""Nov 17 2026 (G daily site check): card 696 / ep 685 guest is Alex Imas, not
'Alex E. Moss'; Cowen quote 'anthropic IPL' is IPO (transcript-confirmed); and
12 pundit net-worth figures/sources are dropped until a real source exists.

The #833/#841 lesson applies: test both the stored DB text and the live form.
For Moss and IPL the two forms currently match; the stored OpenAI quote still
reads 'for anthropic an open AI?' while the live text has already been swapped
to 'for Anthropic [and] OpenAI?' by the Nov 16 card rule.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

TITLE = "Alex Imas & Tyler Cowen | AI Is Moving Fast. Why Isn’t the Economy?"
IPL = "the anthropic IPL will go for"
IPO = "the anthropic IPO will go for"
STORED_OPENAI = "for anthropic an open AI?"
LIVE_OPENAI = "for Anthropic [and] OpenAI?"

NET_WORTH_IDS = (437, 364, 347, 308, 307, 123, 260, 163, 158, 281, 282, 157)
# Names on these four are left unchanged; G will send corrections separately.
NAME_HOLD_IDS = {123, 307, 308, 364}


def _card(form="stored"):
    openai = STORED_OPENAI if form == "stored" else LIVE_OPENAI
    quotes = [
        {"speaker": "Tyler Cowen",
         "quote": f"If you look at prediction markets for what {IPL}, it's not flying above 2 trillion."},
        {"speaker": "Tyler Cowen",
         "quote": f"You're giving me {openai} And no one had an answer for that question."},
        {"speaker": "Alex E. Moss",
         "quote": "What you actually need for really economic transformation is not just competence."},
    ]
    evidence = (
        f'Tyler Cowen: "If you look at prediction markets for what {IPL}, it\'s not flying above 2 trillion."\n'
        f'Tyler Cowen: "You\'re giving me {openai} And no one had an answer."\n'
        'Alex E. Moss: "What you actually need for really economic transformation is not just competence."'
    )
    return {
        "id": 696,
        "podcast_episode_id": 685,
        "title": TITLE,
        "summary": "Alex E. Moss argues the progress is real and accelerating.",
        "key_takeaway": "Tyler Cowen and Alex E. Moss both imply that without coordination, takeoff is unlikely.",
        "notable_quotes": quotes,
        "episode_evidence": evidence,
    }


def _assert_card_fixed(r, openai_expected):
    blob = (r["summary"] + r["key_takeaway"] + r["episode_evidence"]
            + "".join(q["speaker"] + q["quote"] for q in r["notable_quotes"]))
    assert "Alex E. Moss" not in blob
    assert "Alex Imas" in r["summary"]
    assert "Alex Imas" in r["key_takeaway"]
    assert r["notable_quotes"][2]["speaker"] == "Alex Imas"
    assert "Alex Imas:" in r["episode_evidence"]
    assert IPL not in blob
    assert IPO in r["notable_quotes"][0]["quote"]
    assert IPO in r["episode_evidence"]
    assert openai_expected in r["notable_quotes"][1]["quote"]
    # Title already names Imas and must stay a title (no swap needed).
    assert r["title"] == TITLE


def test_stored_form_moss_and_ipl():
    r = _card("stored")
    export_data._apply_summary_overrides([r])
    _assert_card_fixed(r, LIVE_OPENAI)  # stored OpenAI phrase is also rewritten by the Nov 16 rule


def test_live_form_moss_and_ipl():
    r = _card("live")
    export_data._apply_summary_overrides([r])
    _assert_card_fixed(r, LIVE_OPENAI)


def test_global_pair_catches_pundit_last_main_idea():
    # Live export copied the card 696 takeaway onto a pundit last_main_idea.
    row = {
        "id": 9999,
        "slug": "someone",
        "mention_score": 1,
        "name": "Tyler Cowen",
        "last_main_idea": "AI progress is real, but Tyler Cowen and Alex E. Moss both imply that without coordination, takeoff is unlikely.",
    }
    export_data._apply_summary_overrides([row])
    assert "Alex E. Moss" not in row["last_main_idea"]
    assert "Alex Imas" in row["last_main_idea"]


def _pundit(pid, name, source, usd=10_000_000):
    return {
        "id": pid,
        "slug": name.lower().replace(" ", "-"),
        "mention_score": 1,
        "name": name,
        "net_worth": f"${usd / 1_000_000:.1f}M",
        "net_worth_usd": usd,
        "net_worth_source": source,
        "net_worth_updated_at": "2026-09-04T08:47:14.550190",
    }


def test_net_worth_cleared_on_listed_ids_and_names_held():
    rows = [
        _pundit(437, "Ben Mildenhall", "https://mabumbe.com/people/jace-hall-age-net-worth-relationships-family-career-highlights-more/"),
        _pundit(364, "Justin Jo", "https://www.oreateai.com/blog/understanding-jts-net-worth-a-deep-dive-into-financial-success/038440304a611a384c01343e6d0bc517", 250_000_000),
        _pundit(347, "Clem Delangue", "https://eboona.com/ai-startup-founder/clement-delangue/", 500_000_000),
        _pundit(308, "John Mata", "https://mabumbe.com/people/juan-matas-life-story-early-years-achievements-family/", 60_000_000),
        _pundit(307, "Paul Beckas", "https://flashpress.co.uk/paul-boukadakis-net-worth/"),
        _pundit(123, "Chandler Luzsicza", "https://en.wikipedia.org/wiki/Christopher_Chandler_(businessman", 1_000_000_000),
        _pundit(260, "Clem Delangue", "https://www.celebritynetworth.com/richest-businessmen/ceos/scott-delong-net-worth/", 16_500_000),
        _pundit(163, "Josh Shapiro", "https://nationaltoday.com/us/pa/harrisburg/news/2026/02/24/josh-shapiros-35-million-net-worth-raises-questions-about-lobbying-ties/", 35_000_000),
        _pundit(158, "Shyam Sankar", "https://urbansweekly.com/shyam-sankar/", 1_000_000_000),
        _pundit(281, "Bill Maris", "https://www.zenithmaps.com/2557840/unveiling-the-billionaire-bill-maris039/", 1_300_000_000),
        _pundit(282, "Sachin Jain", "https://www.celebsagewiki.com/sachin-h-jain", 50_000_000),
        _pundit(157, "Trae Stephens", "https://www.oreateai.com/blog/palantir-founders-net-worth/", 500_000_000),
    ]
    held_names = {r["id"]: r["name"] for r in rows if r["id"] in NAME_HOLD_IDS}
    export_data._apply_summary_overrides(rows)
    by = {r["id"]: r for r in rows}
    assert set(by) == set(NET_WORTH_IDS)
    for pid, r in by.items():
        assert "net_worth" not in r, pid
        assert r.get("net_worth_usd") is None, pid
        assert r.get("net_worth_source") in (None, ""), pid
        assert r.get("net_worth_updated_at") is None, pid
    for pid, name in held_names.items():
        assert by[pid]["name"] == name


def test_entity_671_renamed_to_alex_imas():
    row = {
        "id": 671,
        "slug": "alex-e-moss",
        "mention_score": 1,
        "name": "Alex E. Moss",
        "known_for": "Appeared as Alex E. Moss on a16z.",
    }
    export_data._apply_summary_overrides([row])
    assert row["name"] == "Alex Imas"
    assert row["slug"] == "alex-imas"
    assert "Alex E. Moss" not in row["known_for"]
    assert "Alex Imas" in row["known_for"]
