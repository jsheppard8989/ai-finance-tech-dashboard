#!/usr/bin/env python3
"""Summarizer attribution rules approved by Jared on Nov 15 2026 (decisions.md, 5:08 PM CT).

Covers: fixed host rosters (All-In key mismatch, Moonshots panel), clip attribution and
clip voices never listed as guests, no guest names from titles, the verbatim quote
checker (drop + log) on notable quotes / Overton quotes / Deep Dive evidence, and the
Overton "last detected by" speaker. Fixtures use the real ep 679 / 680 failures from
/workspace/cos/fixes/summary_attribution_fixes_2026-11-15.md.
"""

import json
import sqlite3
from pathlib import Path

import pytest

import speaker_attribution as sa
from two_pass_analyzer import (
    SITE_CONTRACT_PROMPT,
    build_extraction_prompt,
    get_known_hosts,
)

ALLIN = "All-In with Chamath, Jason, Sacks & Friedberg"
MOON = "Moonshots with Peter Diamandis"
ALLIN_TITLE = 'Jensen Ousted as Nvidia CEO: "Spy" Scandal, Export Restrictions, Market Impact'
MOON_TITLE = ("Jensen\u2019s Departure, NVIDIA\u2019s succession plan, AI doomer response, and Demis talks RSI "
              "| MOONSHOTS #311 (recorded live)")
MOON_311_NOTES = (
    "The Mates sit down with Emad Mostaque to discuss Jensen Huang\u2019s departure.\n"
    "Peter H. Diamandis, MD, is the Founder of XPRIZE\n"
    "Salim Ismail is the founder of Open ExO\n"
    "Dr. Alexander Wissner-Gross is a computer scientist and founder of Reified\n"
    "Read Emad\u2019s latest papers\n"
)

# Transcript snippets (Whisper style: no speaker labels).
ALLIN_TX = (
    "Nvidia reports earnings next Tuesday, critical moment for the company. And the stock has been crushed "
    "down 15% in the last week, which is hundreds of billions of dollars. "
    "Chamath, you're pretty close to this, is there someone in NVIDIA that continues running that effort? "
    "Colette Kress and you are kind of right. The bank of NVIDIA ran through Jensen and it's not clear what "
    "happens now. I think Anthropic is building the Microsoft killer and every SaaS company killer by bundling. "
    "We need HBM capacity and HBM integration to keep up."
)
MOON_TX = (
    "Paul Christiano opened the Jeff Hinton lectures with this statement, quote, I think there is a high risk "
    "of an AI takeover within the next three years. Friend of the pod, CEO Will Marshall, said users can now, "
    "quote, ask the Earth and search 10 years, 3000 plus layer archive of daily satellite imagery. "
    "Let's take a listen. The next phase, which I think carries the most risk, is closed RSI, closed loop, where "
    "you basically manage to somehow figure out how to do it without the human reviewer process in the whole "
    "procedure. It's making a human engineer maybe three, four, five times more productive."
)


# --- 1. Rosters -------------------------------------------------------------------

class TestRoster:
    def test_all_in_feed_name_gets_the_four_besties(self):
        # Old KNOWN_HOSTS was keyed "All-In Podcast", so the real feed name got no host list.
        assert get_known_hosts(ALLIN) == [
            "Jason Calacanis", "Chamath Palihapitiya", "David Sacks", "David Friedberg"]
        assert get_known_hosts("All-In Podcast") == get_known_hosts(ALLIN)

    def test_moonshots_regular_panel(self):
        assert get_known_hosts(MOON) == [
            "Peter Diamandis", "Alex Wissner-Gross", "Salim Ismail", "Dave Blundin", "Emad Mostaque"]

    def test_moonshots_show_notes_narrow_the_panel(self):
        # #311 show notes list Peter, Salim, Alex and Emad; Dave Blundin was absent.
        assert get_known_hosts(MOON, MOON_311_NOTES) == [
            "Peter Diamandis", "Alex Wissner-Gross", "Salim Ismail", "Emad Mostaque"]

    def test_google_x_moonshot_podcast_is_not_the_panel_show(self):
        assert not sa.is_host_panel_show("The Moonshot Podcast")
        assert get_known_hosts("Monetary Matters with Jack Farley") == ["Jack Farley"]

    def test_extraction_prompt_has_roster_rules_and_no_title_guest(self):
        prompt = build_extraction_prompt("transcript", podcast_name=ALLIN, episode_title=ALLIN_TITLE)
        assert "SHOW ROSTER" in prompt and "Jason Calacanis" in prompt
        assert "Moderator: Jason Calacanis." in prompt
        assert "Guest: Jensen" not in prompt
        assert "Only special episodes have a guest" in prompt
        assert "addresses them by name right before they answer" in prompt
        assert "When a host asks a named co-host a question, the answer belongs to THAT co-host." in prompt
        assert 'write "one host"' in prompt

    def test_cleanup_sets_fixed_roster_and_moves_regulars_out_of_guests(self):
        analysis = {"guests": [{"name": "David Sacks", "role": "guest", "intro_cue": "x"}],
                    "hosts": [{"name": "Chamath Palihapitiya", "role": "host"}]}
        sa.clean_guests_and_hosts(analysis, ALLIN, ALLIN_TX)
        assert analysis["guests"] == []
        assert [h["name"] for h in analysis["hosts"]] == get_known_hosts(ALLIN)


# --- 2. Clips ------------------------------------------------------------------------

class TestClipAttribution:
    def test_clip_voices_never_listed_as_guests(self):
        # Ep 679's DB guest list held the clip voices (Hassabis, Christiano, Marshall).
        analysis = {"guests": [
            {"name": "Demis Hassabis (clip)", "role": "guest"},
            {"name": "Paul Christiano", "role": "guest"},  # quoted, no live intro
            {"name": "Will Marshall", "role": "quoted"},
        ]}
        dropped = sa.clean_guests_and_hosts(analysis, MOON, MOON_TX, MOON_311_NOTES)
        assert analysis["guests"] == []
        assert {d["name"] for d in dropped} == {"Demis Hassabis (clip)", "Paul Christiano", "Will Marshall"}

    def test_live_guest_with_intro_cue_is_kept(self):
        tx = "Welcome to the show, Jensen Huang, great to have you here. " + ALLIN_TX
        analysis = {"guests": [{"name": "Jensen Huang", "role": "guest",
                                "intro_cue": "Welcome to the show, Jensen Huang, great to have you here"}]}
        sa.clean_guests_and_hosts(analysis, ALLIN, tx)
        assert [g["name"] for g in analysis["guests"]] == ["Jensen Huang"]

    def test_quoted_by_label_keeps_original_speaker(self):
        assert sa.base_speaker_name("Paul Christiano (quoted by Peter Diamandis)") == "Paul Christiano"
        assert sa.is_clip_label("Demis Hassabis (clip)")
        assert sa.is_clip_label("Will Marshall (quoted by Peter Diamandis)")
        assert not sa.is_clip_label("Peter Diamandis")

    def test_prompts_carry_clip_rules(self):
        prompt = build_extraction_prompt("t", podcast_name=MOON, episode_title=MOON_TITLE)
        assert "Paul Christiano (quoted by" in prompt
        assert "Never list clip voices" in prompt
        assert "Never list clip voices, quoted people" in SITE_CONTRACT_PROMPT

    def test_hypothetical_rules_in_both_prompts(self):
        prompt = build_extraction_prompt("t", podcast_name=ALLIN)
        for p in (prompt, SITE_CONTRACT_PROMPT):
            assert "Never present it as their forecast" in p
            assert "systemic vulnerability" in p

    def test_legacy_prompt_carries_roster_and_rules(self):
        import analyze_transcript as at

        seen = {}

        class _Resp:
            class _C:
                class message:
                    content = json.dumps({"summary": "s", "notable_quotes": [], "guests": [], "hosts": []})
                finish_reason = "stop"
            choices = [_C()]

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        seen["prompt"] = kw["messages"][1]["content"]
                        return _Resp()

        at.analyze_transcript_with_ai(("openai", _Client()), ALLIN_TX * 3, ALLIN,
                                      name_hint=ALLIN_TITLE, show_notes="")
        p = seen["prompt"]
        assert "SHOW ROSTER" in p and "David Friedberg" in p
        assert "NOT a guest unless the transcript introduces" in p
        assert "SPEAKER ATTRIBUTION" in p and "CLIPS AND QUOTED PEOPLE" in p
        assert "machine-checked" in p
        assert '"speaker": "Full name of the person who said speaker_quote' in p


# --- 5. Title names --------------------------------------------------------------------

class TestTitleNameRejection:
    def test_all_in_title_fragment_is_not_a_guest(self):
        from extract_guests import extract_guest_name
        # Card 690: "Jensen Ousted as Nvidia CEO" came from the "Guest Name: Topic" pattern.
        assert extract_guest_name(ALLIN_TITLE, "The besties discuss Jensen leaving Nvidia.", ALLIN) is None

    def test_panel_show_never_uses_title_even_with_a_real_name(self):
        from extract_guests import extract_guest_name
        assert extract_guest_name("Jensen Huang: The Interview", "", ALLIN) is None

    def test_panel_show_summary_cannot_make_a_host_the_guest(self):
        from extract_guests import extract_guest_name
        assert extract_guest_name("Market week", "David Sacks discusses export controls.", ALLIN) is None

    def test_other_shows_need_episode_backing(self):
        from extract_guests import extract_guest_name
        title = "Fabs, Lithography and Yield | Pat Gelsinger"
        assert extract_guest_name(title, "", "The a16z Show") is None
        assert extract_guest_name(title, "Pat Gelsinger explains chip supply.", "The a16z Show") == "Pat Gelsinger"
        assert extract_guest_name(title, "", "The a16z Show",
                                  key_takeaways=["Pat Gelsinger said fabs take 4 years."]) == "Pat Gelsinger"

    def test_two_pass_prompt_marks_title_name_unconfirmed_on_interview_shows(self):
        prompt = build_extraction_prompt("t", podcast_name="The a16z Show",
                                         episode_title="Kevin Mandia: Building Defense")
        assert "Possibly a guest (named in the title" in prompt
        assert "- Guest: Kevin Mandia" not in prompt


# --- 4. Quote checker -----------------------------------------------------------------

class TestQuoteChecker:
    def test_invented_quote_dropped_and_logged(self, tmp_path):
        log = tmp_path / "drops.jsonl"
        analysis = {
            "notable_quotes": [
                # B5: invented Hassabis quote (0 hits in the episode)
                {"speaker": "Demis Hassabis (clip)", "quote": "And the bigger risk there is closed loop where the "
                 "intelligence starts to self-improve, maybe through its own experimentation, and is not at all "
                 "understandable to humans because it's created something that's a little bit alien."},
                {"speaker": "Demis Hassabis (clip)", "quote": "The next phase, which I think carries the most risk, "
                 "is closed RSI, closed loop, where you basically manage to somehow figure out how to do it"},
            ],
            "emerging_terms": [
                {"term": "Recursive Self-Improvement", "speaker_quote": "RSI will be solved by Tuesday for sure, says everyone"},
                {"term": "AI Takeover", "speaker_quote": "I think there is a high risk of an AI takeover within the next three years"},
            ],
        }
        drops = sa.verify_analysis_quotes(analysis, MOON_TX, episode_ref="ep679", log_path=log)
        assert len(analysis["notable_quotes"]) == 1
        assert analysis["notable_quotes"][0]["quote"].startswith("The next phase")
        assert analysis["emerging_terms"][0]["speaker_quote"] == ""  # dropped, never reworded
        assert analysis["emerging_terms"][1]["speaker_quote"].startswith("I think there is")
        assert len(drops) == 2
        logged = [json.loads(l) for l in log.read_text().splitlines()]
        assert {l["field"] for l in logged} == {"notable_quotes", "emerging_terms[Recursive Self-Improvement].speaker_quote"}
        assert all(l["episode"] == "ep679" for l in logged)

    def test_whisper_variants_still_pass(self):
        # Fuzzy 0.85: minor transcription differences are not drops.
        analysis = {"notable_quotes": [{"speaker": "Jason Calacanis",
                                        "quote": "the stock has been crushed down 15% in the last week, which is "
                                                 "hundreds of billions of dollar"}]}
        assert sa.verify_analysis_quotes(analysis, ALLIN_TX, log_path="/dev/null") == []
        assert len(analysis["notable_quotes"]) == 1

    def test_deep_dive_evidence_lines_checked(self, tmp_path):
        log = tmp_path / "d.jsonl"
        ev = ("Paul Christiano (quoted by Peter Diamandis): \"I think there is a high risk of an AI takeover within the next three years.\"\n"
              "Peter Diamandis: \"AI takeover is basically guaranteed by 2027 and nobody can stop it now.\"\n"
              "- Demis Hassabis (clip): \"It's making a human engineer maybe three, four, five times more productive.\"")
        kept, drops = sa.verify_evidence_lines(ev, MOON_TX, episode_ref="insight 691", log_path=log)
        assert "guaranteed by 2027" not in kept
        assert kept.count("\n") == 1
        assert len(drops) == 1 and drops[0]["speaker"] == "Peter Diamandis"
        assert log.exists()

    def test_generate_deepdives_hook_drops_lines(self, tmp_path, monkeypatch):
        import generate_deepdives as gd
        monkeypatch.setattr(sa, "_log_drops", lambda drops, log_path=None: None)
        content = {"episode_evidence": [
            "Jason Calacanis: Nvidia reports earnings next Tuesday, critical moment for the company.",
            "Chamath Palihapitiya: Nvidia will be worth ten trillion dollars by next spring, mark my words.",
        ]}
        drops = gd.apply_evidence_quote_check(content, ALLIN_TX, "insight 690")
        assert len(drops) == 1
        assert content["episode_evidence"] == [
            "Jason Calacanis: Nvidia reports earnings next Tuesday, critical moment for the company."]
        assert gd.apply_evidence_quote_check({"episode_evidence": ["x: y"]}, "", "") == []  # no transcript: skip


# --- 3. Overton speaker ----------------------------------------------------------------

class TestOvertonSpeaker:
    def test_term_speaker_is_who_said_it_not_guest_list(self):
        analysis = {"guests": [], "hosts": [{"name": n} for n in get_known_hosts(ALLIN)]}
        # A14: HBM showed "Chamath Palihapitiya, David Sacks (hosts)" from the old host fallback.
        assert sa.emerging_term_speaker({"term": "HBM", "speaker": "Chamath"}, analysis, ALLIN) == "Chamath Palihapitiya"
        assert sa.emerging_term_speaker({"term": "HBM", "speaker": ""}, analysis, ALLIN) is None
        assert sa.emerging_term_speaker({"term": "HBM", "speaker": "one host"}, analysis, ALLIN) is None

    def test_clip_voice_keeps_clip_label(self):
        analysis = {"guests": [{"name": "Demis Hassabis"}, {"name": "Paul Christiano"}]}
        assert sa.emerging_term_speaker({"term": "AI Takeover", "speaker": "Paul Christiano (clip)"},
                                        analysis, MOON) == "Paul Christiano (clip)"
        # B9: never fall back to the (clip-voice) guest list on a panel show.
        assert sa.emerging_term_speaker({"term": "Hyperscalers"}, analysis, MOON) is None

    def test_interview_show_single_guest_fallback(self):
        analysis = {"guests": [{"name": "Stacy Rasgon"}]}
        assert sa.emerging_term_speaker({"term": "HBM"}, analysis, "Monetary Matters with Jack Farley") == "Stacy Rasgon"

    def test_db_new_episode_with_unknown_speaker_clears_old_name(self, tmp_path, monkeypatch):
        import db_manager
        db = db_manager.DashboardDB(tmp_path / "t.db")
        with db._get_connection() as conn:
            for eid, d in ((1, "2026-11-01"), (2, "2026-11-14")):
                conn.execute("INSERT INTO podcast_episodes (id, podcast_name, episode_title, episode_date) "
                             "VALUES (?, 'All-In', ?, ?)", (eid, f"ep{eid}", d))
        db.upsert_suggested_term_from_ai("HBM", "memory", None, "ctx", episode_id=1, detected_by="David Sacks")
        with db._get_connection() as conn:
            conn.execute("INSERT INTO overton_terms (term, status, last_mentioned_speaker) VALUES ('HBM', 'active', 'David Sacks')")
        # Episode 2: speaker known -> that name
        db.upsert_suggested_term_from_ai("HBM", None, None, "ctx", episode_id=2,
                                         detected_by="Chamath Palihapitiya", clear_speaker_if_none=True)
        with db._get_connection() as conn:
            row = conn.execute("SELECT last_mentioned_speaker, last_mentioned_episode_id FROM overton_terms").fetchone()
        assert (row[0], row[1]) == ("Chamath Palihapitiya", 2)

    def test_db_mention_scan_unknown_speaker_does_not_keep_stale_name(self, tmp_path):
        import db_manager
        from term_mention_scan import record_episode_mentions
        db = db_manager.DashboardDB(tmp_path / "t.db")
        with db._get_connection() as conn:
            for eid, d in ((1, "2026-11-01"), (2, "2026-11-14"), (3, "2026-11-15")):
                conn.execute("INSERT INTO podcast_episodes (id, podcast_name, episode_title, episode_date) "
                             "VALUES (?, 'Moonshots', ?, ?)", (eid, f"ep{eid}", d))
        db.upsert_suggested_term_from_ai("Hyperscalers", "d", None, "ctx", episode_id=1,
                                         detected_by="Demis Hassabis, Paul Christiano, Will Marshall")
        with db._get_connection() as conn:
            conn.execute("INSERT INTO overton_terms (term, status, last_mentioned_speaker, last_mentioned_episode_id) "
                         "VALUES ('Hyperscalers', 'active', 'Demis Hassabis, Paul Christiano, Will Marshall', 1)")
        n, _ = record_episode_mentions(db, transcript="the hyperscalers are spending", episode_id=2,
                                       detected_by=None, speakers_by_term={}, clear_speaker_if_none=True)
        assert n == 1
        with db._get_connection() as conn:
            row = conn.execute("SELECT last_mentioned_speaker, last_mentioned_episode_id FROM overton_terms").fetchone()
        assert row[1] == 2 and row[0] is None
        n, _ = record_episode_mentions(db, transcript="the hyperscalers are spending", episode_id=3,
                                       speakers_by_term={"hyperscalers": "Alex Wissner-Gross"},
                                       clear_speaker_if_none=True)
        with db._get_connection() as conn:
            row = conn.execute("SELECT last_mentioned_speaker FROM overton_terms").fetchone()
        assert row[0] == "Alex Wissner-Gross"

    def test_mention_scan_default_keeps_old_behaviour(self, tmp_path):
        """Callers that don't opt in (other scripts) keep the old COALESCE behaviour."""
        import db_manager
        from term_mention_scan import record_episode_mentions
        db = db_manager.DashboardDB(tmp_path / "t.db")
        with db._get_connection() as conn:
            for eid in (1, 2):
                conn.execute("INSERT INTO podcast_episodes (id, podcast_name, episode_title, episode_date) "
                             "VALUES (?, 'X', ?, '2026-11-01')", (eid, f"ep{eid}"))
        db.upsert_suggested_term_from_ai("Jevons Paradox", "d", None, "ctx", episode_id=1, detected_by="A Person")
        record_episode_mentions(db, transcript="jevons paradox again", episode_id=2)
        with db._get_connection() as conn:
            row = conn.execute("SELECT last_seen_speaker FROM suggested_terms").fetchone()
        assert row[0] == "A Person"


# ---------------------------------------------------------------------------
# Change 1 enforced in code: a named panel speaker needs a transcript cue
# ---------------------------------------------------------------------------
from speaker_attribution import enforce_speaker_cues, speaker_is_cued, verify_evidence_lines as _vel  # noqa: E402

ALLIN = "All-In with Chamath, Jason, Sacks & Friedberg"
MOON = "Moonshots with Peter Diamandis"
FILLER = " and the market moved a lot this week on chips and models " * 3


def _tx_allin():
    return (
        "Okay Sacks, what do you think about the board? I would say it's tragic for the United States "
        "because Jensen is one of the key reasons Nvidia leads." + FILLER +
        "Friedberg, your take? Huawei is far behind on yield." + FILLER +
        "Okay I have two takes. I think Anthropic is building the Microsoft killer by bundling everything."
    )


def test_cue_keeps_addressed_cohost(tmp_path):
    ex = {"high_value_quotes": [{"speaker": "Sacks", "quote": "I would say it's tragic for the United States"}]}
    ch = enforce_speaker_cues(ex, _tx_allin(), ALLIN, log_path=tmp_path / "l.jsonl")
    assert ch == []
    assert ex["high_value_quotes"][0]["speaker"] == "David Sacks"


def test_cue_relabels_when_last_named_cohost_is_someone_else(tmp_path):
    # Last name said before the words is Friedberg's; the model guessed Sacks.
    ex = {"companies_and_assets": [{"name": "Huawei", "key_quotes": [
        {"speaker": "David Sacks", "quote": "Huawei is far behind on yield", "cue": "Huawei is far behind"}]}]}
    ch = enforce_speaker_cues(ex, _tx_allin(), ALLIN, log_path=tmp_path / "l.jsonl")
    assert ex["companies_and_assets"][0]["key_quotes"][0]["speaker"] == "one host"
    assert ch and ch[0]["speaker"] == "David Sacks"
    assert (tmp_path / "l.jsonl").read_text().count("David Sacks") == 1


def test_cue_relabels_moderator_turn_credited_to_previous_speaker(tmp_path):
    ex = {"high_value_quotes": [{"speaker": "David Friedberg",
                                 "quote": "I think Anthropic is building the Microsoft killer"}]}
    tx = _tx_allin().replace("Okay I have two takes.", FILLER * 20 + " Okay I have two takes.")
    enforce_speaker_cues(ex, tx, ALLIN, log_path=tmp_path / "l.jsonl")
    assert ex["high_value_quotes"][0]["speaker"] == "one host"


def test_cue_ignores_third_person_mention():
    tx = ("Emad, what's your timeline? Alex and I have spoken about two or three years. "
          "Yeah I think two three years for knocking down the core mechanisms of disease.")
    roster = ["Peter Diamandis", "Alex Wissner-Gross", "Salim Ismail", "Emad Mostaque"]
    from speaker_attribution import _norm
    assert not speaker_is_cued("Alex Wissner-Gross", "two three years for knocking down the core mechanisms",
                               _norm(tx), roster)
    assert speaker_is_cued("Emad Mostaque", "two three years for knocking down the core mechanisms",
                           _norm(tx), roster)


def test_cue_clip_voice_needs_own_name_whisper_spelling_ok(tmp_path):
    tx = ("So Paul Cristiano opened the Hinton lectures with this statement quote "
          "I think there is a high risk of an AI takeover within the next three years.")
    ex = {"high_value_quotes": [
        {"speaker": "Paul Christiano (clip)", "quote": "I think there is a high risk of an AI takeover"},
        {"speaker": "Demis Hassabis (clip)", "quote": "within the next three years"}]}
    enforce_speaker_cues(ex, tx, MOON, log_path=tmp_path / "l.jsonl")
    assert ex["high_value_quotes"][0]["speaker"] == "Paul Christiano (clip)"
    assert ex["high_value_quotes"][1]["speaker"] == "one host"


def test_cue_hedged_or_unlocatable_labels_become_one_host(tmp_path):
    ex = {"major_claims": [
        {"claim": "x", "speaker": "one host / Alex Wissner-Gross", "evidence": ["AI is a universal translator"]},
        {"claim": "y", "speaker": "Salim Ismail", "evidence": ["Repeated claims about disintermediation"]}]}
    tx = "Alex, go. AI is a universal translator."
    enforce_speaker_cues(ex, tx, MOON, log_path=tmp_path / "l.jsonl")
    assert [c["speaker"] for c in ex["major_claims"]] == ["one host", "one host"]


def test_cue_check_leaves_non_panel_shows_alone(tmp_path):
    ex = {"high_value_quotes": [{"speaker": "Jack Farley", "quote": "rates matter"}]}
    assert enforce_speaker_cues(ex, "rates matter", "Monetary Matters with Jack Farley",
                                log_path=tmp_path / "l.jsonl") == []
    assert ex["high_value_quotes"][0]["speaker"] == "Jack Farley"


def test_cue_blanks_uncued_emerging_term_speaker(tmp_path):
    ex = {"emerging_terms": [{"term": "RSI engine", "speaker": "David Sacks",
                              "speaker_quote": "I think Anthropic is building the Microsoft killer"}]}
    tx = _tx_allin().replace("Okay I have two takes.", FILLER * 20 + " Okay I have two takes.")
    enforce_speaker_cues(ex, tx, ALLIN, log_path=tmp_path / "l.jsonl")
    assert ex["emerging_terms"][0]["speaker"] == ""


def test_evidence_line_speaker_relabelled_when_uncued(tmp_path):
    tx = _tx_allin().replace("Okay I have two takes.", FILLER * 20 + " Okay I have two takes.")
    lines = ["David Friedberg: I think Anthropic is building the Microsoft killer",
             "David Sacks: I would say it's tragic for the United States"]
    kept, drops = _vel(lines, tx, podcast_name=ALLIN, log_path=tmp_path / "l.jsonl")
    assert drops == []
    assert kept[0].startswith("one host: I think Anthropic")
    assert kept[1].startswith("David Sacks:")


# ---------------------------------------------------------------------------
# Named prose needs a cued item; "one host" evidence lines pass the Deep Dive check
# ---------------------------------------------------------------------------
from speaker_attribution import enforce_named_prose  # noqa: E402


def test_prose_name_kept_when_cued_item_supports_it(tmp_path):
    analysis = {"summary": "David Sacks says leaking classified intelligence is a crime.",
                "key_takeaways": ["Sacks says Jensen's removal is tragic for the United States."],
                "notable_quotes": [{"speaker": "David Sacks",
                                    "quote": "leaking classified intelligence is a crime, tragic for the United States"}]}
    ch = enforce_named_prose(analysis, ALLIN, extraction={}, log_path=tmp_path / "l.jsonl")
    assert ch == []
    assert analysis["summary"].startswith("David Sacks says")


def test_prose_name_replaced_when_no_cued_item(tmp_path):
    # Re-run 2: Chamath's 50-150 bp line was put on Sacks although the extraction said "one host".
    analysis = {"summary": "The hosts debate chips. David Sacks says growth could fall 50 to 150 basis points.",
                "key_takeaways": ["David Sacks says the market could see a 50 to 150 basis point growth hit.",
                                  "one host says rates matter."],
                "investment_thesis": "Nvidia matters.",
                "notable_quotes": []}
    extraction = {"major_claims": [{"claim": "Growth could lose 50 to 150 basis points", "speaker": "one host"}],
                  "high_value_quotes": [{"speaker": "David Sacks", "quote": "leaking classified intelligence is a crime"}]}
    ch = enforce_named_prose(analysis, ALLIN, extraction=extraction, log_path=tmp_path / "l.jsonl")
    assert analysis["summary"] == "The hosts debate chips. One host says growth could fall 50 to 150 basis points."
    assert analysis["key_takeaways"][0].startswith("One host says the market")
    assert analysis["key_takeaways"][1].startswith("One host says rates")
    assert len(ch) == 2


def test_prose_clip_sentence_left_to_clip_rule(tmp_path):
    analysis = {"summary": "Dario Amodei (quoted by Jason Calacanis) said diseases could be relics in a decade.",
                "key_takeaways": [], "notable_quotes": []}
    enforce_named_prose(analysis, ALLIN, extraction={}, log_path=tmp_path / "l.jsonl")
    assert "Jason Calacanis" in analysis["summary"]


def test_prose_check_skips_non_panel_shows(tmp_path):
    analysis = {"summary": "Jack Farley says rates matter.", "key_takeaways": [], "notable_quotes": []}
    assert enforce_named_prose(analysis, "Monetary Matters with Jack Farley", extraction={},
                               log_path=tmp_path / "l.jsonl") == []


def test_deep_dive_structural_accepts_one_host_lines():
    from generate_deepdives import deep_dive_structural_ok
    content = {"episode_evidence": [
        "one host: I think Anthropic is building the Microsoft killer by bundling everything they ship.",
        "one host: When you export chips what they ask of the exporter is have telemetry, right?",
        "David Sacks: Leaking classified intelligence is a crime."],
        "overview": "x" * 200, "investment_thesis": "y" * 200}
    ok, why = deep_dive_structural_ok(content)
    assert "name the speaker" not in why


def test_prose_two_uncued_names_become_two_hosts(tmp_path):
    analysis = {"summary": "Alex Wissner-Gross and Salim Ismail tie the moment to RASA.",
                "key_takeaways": ["The panel, including Alex and Salim Ismail, discussed RASA."], "notable_quotes": []}
    enforce_named_prose(analysis, MOON, extraction={}, log_path=tmp_path / "l.jsonl")
    assert analysis["summary"] == "Two hosts tie the moment to RASA."
    assert analysis["key_takeaways"][0] == "The panel, including two hosts, discussed RASA."
