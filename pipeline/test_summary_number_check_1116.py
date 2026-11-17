#!/usr/bin/env python3
"""Number-in-transcript check + 'bet' wording in every site-text prompt.

The A2 fixture is the real All-In ep 680 wording (Wendy / #834 follow-up):
Sacks said "let's just assume ... Nvidia's crippled for two or three years".
The summarizer invented "1- to 3-year" (run 5) / "1-3 years". "1" is not in
the transcript; "two" and "three" are.
"""

from decimal import Decimal

import pytest

from speaker_attribution import OUR_VOICE_WORDING_RULES, apply_attribution_rules
from summary_number_check import (
    apply_number_check,
    extract_numbers,
    site_text_prompts,
    strip_unsupported_numbers,
    transcript_number_set,
)

# Real ep 680 excerpt around 37:42 (pipeline/cos fixture allin_680.txt L499).
# Enough surrounding numbers (384, 72) so normalization cases can share it.
EP680_TX = (
    "they network 384 chips together in the thing called cloud matrix to create this rack system "
    "in video network 72 together and the NVL 72 is better than 384 of the Huawei chips nonetheless "
    "they were getting closer and closer and Jensen's your point they have energy to spare so "
    "what Huawei has been doing is they create a less powerful individual chip that consumes a lot more energy "
    "and then they network more of them together to get a comparable result at the rack system and that's "
    "how they've been catching up now let's just assume that like Nvidia's crippled for two or three "
    "years based on this right you get terminal at the company or whatever that's really good news for "
    "Huawei because they will catch up a lot faster obviously it's good for Nvidia's competitors too "
    "I mean it's going to be good for AMD and Intel maybe but again that's a very narrow way of looking at it "
    "I think it mostly will help Huawei if Nvidia has mastered slow down "
    "the velocity of capital is what drives that innovation engine so the rate at which we can improve "
    "our AI models the rate at which we can improve our AI chips is driven by how fast capital moves "
    "through the system"
)

A2_SENTENCE = (
    "One host described a 1- to 3-year loss of velocity that would let Huawei catch up faster."
)
A2_TAKEAWAY = "Nvidia may lose velocity for 1-3 years if export rules bite."


def test_a2_invented_one_to_three_is_stripped():
    cleaned, drops = strip_unsupported_numbers(A2_SENTENCE, EP680_TX, field="summary")
    assert drops, "the invented 1 in '1- to 3-year' must be stripped"
    assert all("1" in d.numbers or "1- to 3" in d.removed for d in drops)
    assert "1-" not in cleaned and "1-3" not in cleaned
    assert "1- to 3" not in cleaned
    # The sentence has no cleanly separable clause, so the whole sentence goes.
    assert cleaned == ""


def test_a2_takeaway_bullet_dropped():
    analysis = {
        "summary": "Huawei networks 384 chips into a rack. " + A2_SENTENCE,
        "key_takeaways": [
            "Huawei already networks 384 chips together.",
            A2_TAKEAWAY,
        ],
        "investment_thesis": "Export pressure could open a 1-3 year window for Huawei.",
    }
    drops = apply_number_check(analysis, EP680_TX, episode_ref="All-In ep 680")
    assert analysis["summary"] == "Huawei networks 384 chips into a rack."
    assert analysis["key_takeaways"] == ["Huawei already networks 384 chips together."]
    assert analysis["investment_thesis"] == ""
    removed = " ".join(d.removed for d in drops)
    assert "1- to 3-year" in removed or "1-3" in removed


def test_two_to_three_is_supported_by_transcript_words():
    # "2-3 years" uses numbers the speaker said (two, three). This check does
    # not try to catch the separate hypothetical-as-forecast wording issue.
    text = "One host said Nvidia could be crippled for 2-3 years."
    cleaned, drops = strip_unsupported_numbers(text, EP680_TX)
    assert cleaned == text
    assert drops == []


def test_number_word_and_digit_and_scale_normalization():
    tx = (
        "Revenue was fifteen percent higher, about $100 billion, maybe 1.4 trillion "
        "in total, or two million units, and a range of one to three percent. "
        "They filed the 10-Q and talked about the H100 and GPT-5."
    )
    allowed = transcript_number_set(tx)
    assert Decimal(15) in allowed
    assert Decimal(10) ** 11 in allowed  # 100 billion; the bare 100 is not also unlocked
    assert Decimal(100) not in allowed
    assert Decimal("1.4") * Decimal(10) ** 12 in allowed
    assert Decimal(2) * Decimal(10) ** 6 in allowed
    assert Decimal(1) in allowed and Decimal(3) in allowed

    keep, drops = strip_unsupported_numbers(
        "Sales rose 15% on $100B of revenue, or $1.4T, with 2M units in a 1-3 percent band.",
        tx,
    )
    assert drops == []
    assert "15%" in keep

    # Identifier digits must not leak: 10-Q is not the figure 10, H100 is not 100.
    assert Decimal(10) not in allowed
    # Invented 10 (not the form name) still drops.
    cleaned, drops = strip_unsupported_numbers("The margin is 10%.", tx)
    assert drops and cleaned == ""


def test_one_host_is_not_the_number_one():
    text = "One host said Huawei already networks 384 chips together."
    cleaned, drops = strip_unsupported_numbers(text, EP680_TX)
    assert cleaned == text and drops == []


def test_attributed_quote_numbers_pass_if_quote_is_in_transcript():
    tx = 'Sacks said, "let\'s just assume that like Nvidia\'s crippled for two or three years."'
    text = 'Sacks said, "let\'s just assume that like Nvidia\'s crippled for two or three years."'
    cleaned, drops = strip_unsupported_numbers(text, tx)
    assert cleaned == text and drops == []

    # Our-voice invented 1-3 still drops even when a real quote sits next to it.
    mixed = (
        'Sacks said, "let\'s just assume that like Nvidia\'s crippled for two or three years." '
        "That implies a 1-3 year gap."
    )
    cleaned, drops = strip_unsupported_numbers(mixed, tx)
    assert drops
    assert "1-3" not in cleaned
    assert "crippled for two or three years" in cleaned


def test_clause_and_parenthetical_drop_keep_the_rest():
    tx = "Huawei networks 384 chips together."
    text = "Huawei networks 384 chips together (a 1-3 year lag); AMD also benefits."
    # "AMD also benefits" has no number; the parenthetical holds 1-3.
    # 384 is supported. After dropping the parenthetical, "AMD also benefits" is
    # in a semicolon clause without unsupported numbers... actually the sentence
    # is one sentence with a parenthetical and a semicolon clause.
    cleaned, drops = strip_unsupported_numbers(text, tx)
    assert drops
    assert "1-3" not in cleaned
    assert "384" in cleaned
    assert "AMD also benefits" in cleaned


def test_no_transcript_skips_without_changing_text(capsys):
    analysis = {"summary": A2_SENTENCE, "key_takeaways": [A2_TAKEAWAY]}
    drops = apply_number_check(analysis, "", episode_ref="no-tx")
    assert drops == []
    assert analysis["summary"] == A2_SENTENCE
    err = capsys.readouterr()
    # print() goes to stdout
    assert "WARN number check: skipped (no transcript)" in err.out


def test_falsification_tracks_are_not_stripped():
    # Constructed thresholds are required on Deep Dives and are often not spoken.
    content = {
        "overview": "Huawei networks 384 chips; a 1-3 year lag would help it catch up.",
        "falsification_tracks": [
            "Revenue under $318M in the Q3 2026 10-Q, due by Nov 9, 2026.",
        ],
        "investment_thesis": "Watch AMD if the 384-chip rack closes the gap.",
    }
    apply_number_check(content, EP680_TX, kind="deep_dive")
    assert content["falsification_tracks"][0].startswith("Revenue under $318M")
    assert "1-3" not in content["overview"]
    assert "384" in content["overview"]
    assert "384-chip" in content["investment_thesis"]


def test_apply_attribution_rules_runs_the_number_check():
    analysis = {"summary": A2_SENTENCE, "key_takeaways": [A2_TAKEAWAY], "guests": [], "hosts": []}
    report = apply_attribution_rules(analysis, EP680_TX, "All-In with Chamath, Jason, Sacks & Friedberg")
    assert report.get("number_drops")
    assert "1-3" not in (analysis.get("summary") or "")
    assert analysis.get("key_takeaways") == []


def test_spoken_figures_and_years_match_transcript():
    """Normalization misses found in the Nov 1–15 stored-summary sweep."""
    cases = [
        ("I think that tenure interest rates want to five and a quarter percent.",
         "He frames Treasury rates as wanting to move toward 5.25%."),
        ("We'll be doing a million deliveries a day. There are five and a half billion instant deliveries.",
         "The company expects to reach 1 million deliveries per day. There are already 5.5 billion instant deliveries."),
        ("You bought this thing for 500 million and like it's doing a billion in earnings.",
         "A $500 million acquisition became a $1 billion earnings business."),
        ("Three years ago, this was a billion-dollar market. It's now a $10 billion market.",
         "The market has grown from about $1B to $10B in three years."),
        ("We're going back to the 90s and 2000s again.",
         "Cybersecurity could resemble the 1990s and 2000s again."),
        ("We pivoted into the police market in late 99.",
         "The business pivoted to police in late 1999."),
        ("Meaningful capex in 2027. I get really worried about 2028.",
         "Infrastructure winners could be reshaped over 2027-2028."),
        ("After 60, you need between one and a half to two grams of protein per kilo.",
         "People over 60 should target about 1.5–2.0 g/kg of protein."),
        ("Google alone is over a trillion of that.",
         "Google alone is committing over $1 trillion."),
        ("A target rate of some mode between five and a half and six for the ten year treasury.",
         "Fair value around 5.5% to 6%."),
        # Year-cue traps: "in 16 days" / "by 51%" / "of 70,000" are not years.
        ("we reduced maternal mortality from postpartum hemorrhage by 51%.",
         "A University of Pennsylvania publication found a 51% reduction in maternal mortality."),
        ("Finn, you can get up running on average in 16 days. We had it up and running actually in 14 days.",
         "Salesforce says it got Finn running internally in 14 days, versus a typical 16-day ramp."),
        ("Over the last month it's gone up by 40%.",
         "He says costs have still increased about 40% in the last month."),
        ("Bitcoin to retest 70,000 and a bottom in liquidity by late 2027.",
         "An expected retest of 70,000 in 2027 if liquidity worsens."),
    ]
    for tx, summary in cases:
        cleaned, drops = strip_unsupported_numbers(summary, tx)
        assert drops == [], (tx, summary, [(d.numbers, d.removed) for d in drops])
        assert cleaned == summary


def test_bet_rule_is_in_every_site_text_prompt():

    required = [
        'Never write "bet"',
        '"bets"',
        '"betting"',
        "call, view, lean, position, or trade",
        "attributed guest quotes stay verbatim",
    ]
    for phrase in required:
        assert phrase in OUR_VOICE_WORDING_RULES, phrase

    prompts = site_text_prompts()
    expected = {
        "OUR_VOICE_WORDING_RULES",
        "SITE_CONTRACT_PROMPT",
        "SYNTHESIS_PROMPT",
        "EXTRACTION_DEEPDIVE_PROMPT",
        "LEGACY_DEEPDIVE_HARD_RULES",
        "analyze_transcript",
    }
    assert expected <= set(prompts)
    for name, text in prompts.items():
        if name == "analyze_transcript":
            assert "OUR_VOICE_WORDING_RULES" in text, name
            continue
        for phrase in required:
            assert phrase in text, f"{name} missing {phrase!r}"
