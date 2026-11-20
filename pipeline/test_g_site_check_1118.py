"""Nov 18 2026 (G weekday site check): card 704 Ken Liu name + drop
garbled quote 3; card 700 drop the AAPL ticker; 11 wrong-person pundit
net-worth blanks; deep dive 677 falsification_tracks wording.

The #833/#841 lesson applies: test both the stored DB text and the live
form. For 'Kim Liu' / 'Kim Liu\u2019s' the two forms currently match
(unicode apostrophe in both the DB and data.js). An ASCII-apostrophe
variant is also tested. The card-scoped swap plus a global_replacements
pair cover last_mentioned_speaker and episode_evidence labels.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export_data  # noqa: E402

TITLE_704 = "The Missing Layer for Personal AI | First Person Labs’ Ken Liu"
OPUS_QUOTE = "And at Opus 55 is pricing, that leads to a thousand dollars per day."
STORED_APOS = "Kim Liu\u2019s"
ASCII_APOS = "Kim Liu's"
FIXED_STORED_APOS = "Ken Liu\u2019s"
FIXED_ASCII_APOS = "Ken Liu's"

# Wrong-person net-worth records from G's Nov 18 list. Andy Constan is
# entity 254 (data.js pundits index 319; DB name 'Andy Constant').
# Geoffrey Woo is entity 302 (slug jeff-wu).
NET_WORTH_IDS = (392, 388, 254, 432, 168, 110, 302, 397, 384, 422, 284)

FT_677 = (
    "By the FY2026 10-K, HubSpot should not report a 15% or greater "
    "year-over-year decline in CRM-seat expansion or workflow engagement, "
    "with the 10-K as the named source grading the result."
)
FT_677_FIXED = (
    "By the FY2026 10-K, HubSpot should not report a 15% or greater "
    "year-over-year decline in CRM-seat expansion or workflow engagement, "
    "with the 10-K as the named source for the result."
)


def _card_704(apos=STORED_APOS):
    quotes = [
        {"speaker": "Kim Liu",
         "quote": "So we focus on essentially creating a model of a person and then put that person in control."},
        {"speaker": "Kim Liu",
         "quote": "It is a very hard problem, especially to get its secure private."},
        {"speaker": "Kim Liu",
         "quote": OPUS_QUOTE},
    ]
    evidence = (
        "Kim Liu: So we focus on essentially creating a model of a person and then put that person in control.\n"
        "Kim Liu: right now on your computer, there's just an infinite stream of events."
    )
    return {
        "id": 704,
        "podcast_episode_id": 693,
        "title": TITLE_704,
        "summary": (
            f"The episode centers on First Person Labs co-founder {apos} view that "
            "“Second” is a personal AI layer. Kim Liu says the system has to process "
            "an “infinite stream of events”. Kim Liu says reactive productivity is straightforward."
        ),
        "key_takeaway": "Secure, portable personal context could become the missing layer.",
        "notable_quotes": quotes,
        "episode_evidence": evidence,
    }


def _assert_704_fixed(r, expected_apos):
    blob = (r["summary"] + r["key_takeaway"] + r["episode_evidence"]
            + "".join(q["speaker"] + q["quote"] for q in r["notable_quotes"]))
    assert "Kim Liu" not in blob
    assert expected_apos in r["summary"]
    assert "Ken Liu says the system" in r["summary"]
    assert "Ken Liu says reactive" in r["summary"]
    assert all(q["speaker"] == "Ken Liu" for q in r["notable_quotes"])
    assert OPUS_QUOTE not in blob
    # Nov 19 2026 (G item 10): quote 2 ('especially to get its secure private') is dropped too.
    assert len(r["notable_quotes"]) == 1
    assert r["notable_quotes"][0]["quote"].startswith("So we focus")
    assert r["episode_evidence"].startswith("Ken Liu:")
    assert "Kim Liu:" not in r["episode_evidence"]
    # Title already names Ken and must stay a title (no swap needed).
    assert r["title"] == TITLE_704


def test_stored_form_kim_liu_and_drop_quote():
    r = _card_704(STORED_APOS)
    export_data._apply_summary_overrides([r])
    _assert_704_fixed(r, FIXED_STORED_APOS)


def test_ascii_apostrophe_form_kim_liu():
    r = _card_704(ASCII_APOS)
    export_data._apply_summary_overrides([r])
    _assert_704_fixed(r, FIXED_ASCII_APOS)


def test_global_pair_catches_last_mentioned_speaker():
    # Terms rows carry last_mentioned_speaker but not the card's episode id,
    # so only the global pair reaches them.
    row = {
        "id": 336,
        "term": "Confidential inference",
        "last_mentioned_episode_id": 693,
        "last_mentioned_speaker": "Kim Liu",
    }
    export_data._apply_summary_overrides([row])
    assert row["last_mentioned_speaker"] == "Ken Liu"


def test_card_700_drops_aapl_ticker():
    title = (
        "Brad Gerstner & Geoffrey Canada - Raising the Floor for Every "
        "American Child - [Invest Like the Best, EP.501]"
    )
    card = {
        "id": 700,
        "podcast_episode_id": 691,
        "title": title,
        "summary": "The episode centers on the Invest America / universal capital accounts idea.",
        "tickers_mentioned": ["AAPL"],
        "key_tickers": ["AAPL"],
    }
    dd = {
        "insight_id": 700,
        "podcast_episode_id": 691,
        "insight_title": title,
        "key_tickers": ["AAPL"],
        "ticker_analysis": {
            "AAPL": {"rationale": "Apple is named as one of the underlying companies.",
                     "positioning": "Watch"},
            "BRK.B": {"rationale": "Berkshire is cited as an example of a top holding.",
                      "positioning": "Watch"},
            "WMT": {"rationale": "Walmart is another named example.",
                    "positioning": "Watch"},
        },
    }
    other = {
        "id": 657,
        "title": "Some other card",
        "tickers_mentioned": ["AAPL", "GOOGL"],
        "key_tickers": ["AAPL"],
    }
    export_data._apply_summary_overrides([card, dd, other])
    assert card["tickers_mentioned"] == []
    assert card["key_tickers"] == []
    assert dd["key_tickers"] == []
    assert "AAPL" not in dd["ticker_analysis"]
    assert set(dd["ticker_analysis"]) == {"BRK.B", "WMT"}
    # Other cards that actually mention Apple stay untouched.
    assert other["tickers_mentioned"] == ["AAPL", "GOOGL"]
    assert other["key_tickers"] == ["AAPL"]


def _pundit(pid, name, source, usd, net_worth):
    return {
        "id": pid,
        "slug": name.lower().replace(" ", "-"),
        "mention_score": 1,
        "name": name,
        "net_worth": net_worth,
        "net_worth_usd": usd,
        "net_worth_source": source,
        "net_worth_updated_at": "2026-09-04T08:47:14.550190",
    }


def test_net_worth_cleared_on_listed_ids():
    # Mix stored DB names and live exported names; rules are scoped by id.
    rows = [
        _pundit(392, "Emilio Escobar",
                "https://motoelectro.com.au/pablo-escobar-net-worth-how-the-medellin-cartel-boss-built-a-30-billion-drug-empire/",
                30_000_000_000, "$30.00B"),
        _pundit(388, "Dylan Araps",  # stored DB name; live is Dylan Ayrey
                "https://finance-monthly.com/2025/02/bob-dylans-net-worth-2025-legendary-songwriters-fortune-revealed",
                500_000_000, "$500.0M"),
        _pundit(254, "Andy Constant",  # stored DB name; live is Andy Constan
                "https://www.finance-monthly.com/andy-williams-net-worth-2025-classic-crooners-legacy-in-numbers/",
                45_000_000, "$45.0M"),
        _pundit(432, "Aaron Zulman",
                "https://explore.st-aug.edu/exp/aaron-kaufman-net-worth-the-rise-of-a-tech-investor-shaping-silicon-valleys-future",
                1_300_000_000, "$1.30B"),
        _pundit(168, "Adam Rosenswag",  # stored DB name; live is Adam Rozencwajg
                "https://explore.st-aug.edu/exp/adam-22s-net-worth-shocked-the-business-world-the-untold-secrets-behind-his-billionairestyle-wealth",
                1_200_000_000, "$1.20B"),
        _pundit(110, "Adam Warmouth",
                "https://explore.st-aug.edu/exp/adam-22s-net-worth-shocked-the-business-world-the-untold-secrets-behind-his-billionairestyle-wealth",
                1_200_000_000, "$1.20B"),
        _pundit(302, "Geoffrey Woo",
                "https://www.ainutoken.net/net-worth/jihan-wu/",
                800_000_000, "$800.0M"),
        _pundit(397, "Kush Bavaria",
                "https://ftp.richardgraygallery.com/posts/kush-patel-net-worth-updated-2026.html",
                50_000_000, "$50.0M"),
        _pundit(384, "Simon Mow",
                "https://magazinesvalves.com/simon-yiming-ma-net-worth/",
                500_000_000, "$500.0M"),
        _pundit(422, "Jim Wiederhold",
                "https://moneyarcher.com/james-wedmore-net-worth/",
                5_000_000, "$5.0M"),
        _pundit(284, "Alex Boden",
                "https://biahaixom.com.vn/tag/alex-bodi-net-worth/",
                10_000_000, "$10.0M"),
    ]
    # A different pundit with a real source must keep its figure.
    other = _pundit(9999, "Someone Else", "https://example.com/real-source", 1_000_000, "$1.0M")
    export_data._apply_summary_overrides(rows + [other])
    by = {r["id"]: r for r in rows}
    assert set(by) == set(NET_WORTH_IDS)
    for pid, r in by.items():
        assert "net_worth" not in r, pid
        assert r.get("net_worth_usd") is None, pid
        assert r.get("net_worth_source") in (None, ""), pid
        assert r.get("net_worth_updated_at") is None, pid
    assert other.get("net_worth") == "$1.0M"
    assert other.get("net_worth_usd") == 1_000_000


def test_deep_dive_677_falsification_wording():
    dd = {
        "insight_id": 677,
        "podcast_episode_id": 666,
        "falsification_tracks": [
            "By the Q3 2026 10-Q, HubSpot must not show a 200 bps or greater decline in net revenue retention.",
            FT_677,
            "By 2027-12-31, the US Census should not show the share of new companies falling below 60%.",
        ],
    }
    # 672 uses 'grading' as a literal course rubric and must be left alone.
    other = {
        "insight_id": 672,
        "podcast_episode_id": 661,
        "falsification_tracks": [
            "checked against the course internal grading rubric for the result."
        ],
    }
    export_data._apply_summary_overrides([dd, other])
    assert dd["falsification_tracks"][1] == FT_677_FIXED
    assert "grading the result" not in dd["falsification_tracks"][1]
    assert "named source for the result" in dd["falsification_tracks"][1]
    assert other["falsification_tracks"][0] == (
        "checked against the course internal grading rubric for the result."
    )


def test_global_pair_fixes_suggested_term_definitions():
    # generate_website_js now runs _apply_summary_overrides on suggested_terms
    # so the same global pair covers auto-extracted definitions.
    terms = [
        {
            "id": 1231,
            "term": "Confidential inference",
            "definition": (
                "A technical approach for running model inference in a protected "
                "environment so outsiders cannot see inside the computation. Kim Liu "
                "contrasts it with policy-only promises like zero data retention."
            ),
        },
        {
            "id": 1232,
            "term": "Context continuity",
            "definition": (
                "Kim Liu’s term for carrying the same task context across devices "
                "and sessions, such as moving from a laptop to a phone without losing "
                "the thread."
            ),
        },
    ]
    export_data._apply_summary_overrides(terms)
    blob = terms[0]["definition"] + terms[1]["definition"]
    assert "Kim Liu" not in blob
    assert "Ken Liu contrasts" in terms[0]["definition"]
    assert "Ken Liu’s term" in terms[1]["definition"]
