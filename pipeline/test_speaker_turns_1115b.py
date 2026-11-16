#!/usr/bin/env python3
"""Speaker turns from YouTube auto-captions (G, Nov 15 2026; follow-up to PR #826).

YouTube auto-captions mark each change of speaker with '>>'. caption_turns splits them into
turns and names a turn only on solid evidence (a directed question / hand-off right before it,
self-identification, or a clear continuation). Everything else stays "one host". Fixtures are
taken from the real ep 679 (Moonshots #311) and ep 680 (All-In) captions, including the cases
that must NOT be named.
"""

import json

import pytest

import caption_turns as ct
import speaker_attribution as sa

ALLIN = "All-In with Chamath, Jason, Sacks & Friedberg"
MOON = "Moonshots with Peter Diamandis"
MOON_311_NOTES = ("The Mates sit down with Emad Mostaque. Peter H. Diamandis, Salim Ismail, "
                  "Dr. Alexander Wissner-Gross")
ALLIN_ROSTER = sa.episode_roster(ALLIN)
MOON_ROSTER = sa.episode_roster(MOON, MOON_311_NOTES)


def vtt(*turns):
    """Plain WebVTT, one cue per (seconds, text); '>> ' marks a new speaker like YouTube."""
    out = ["WEBVTT", ""]
    for i, (sec, text) in enumerate(turns):
        out.append(f"00:{sec // 60:02d}:{sec % 60:02d}.000 --> 00:{(sec + 5) // 60:02d}:{(sec + 5) % 60:02d}.000")
        out.append(text)
        out.append("")
    return "\n".join(out)


def tmap(roster, *turns):
    tm = ct.build_turn_map(vtt(*turns), roster)
    assert tm is not None
    return tm


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

ROLLING = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:01.750 align:start position:0%
 
All<00:00:00.160><c> right,</c><00:00:00.480><c> everybody.</c>

00:00:01.750 --> 00:00:01.760 align:start position:0%
All right, everybody.
 

00:00:01.760 --> 00:00:04.309 align:start position:0%
All right, everybody.
Sachs,<00:00:01.920><c> what's</c><00:00:02.399><c> new?</c>

00:00:04.309 --> 00:00:06.000 align:start position:0%
Sachs, what's new?
&gt;&gt;<00:00:04.500><c> Benioff</c><00:00:04.800><c> rolled</c><00:00:05.000><c> out</c><00:00:05.200><c> a</c><00:00:05.300><c> new</c><00:00:05.400><c> reporting</c><00:00:05.500><c> feature.</c>
"""


def test_rolling_youtube_vtt_is_deduplicated_and_split_at_markers():
    lines = ct.parse_youtube_vtt(ROLLING)
    assert [t for _, t in lines] == ["All right, everybody.", "Sachs, what's new?",
                                     ">> Benioff rolled out a new reporting feature."]
    turns = ct.split_turns(lines)
    assert [t.text for t in turns] == ["All right, everybody. Sachs, what's new?",
                                       "Benioff rolled out a new reporting feature."]
    assert ct.count_markers(ROLLING) == 1


def test_no_markers_means_no_turn_map():
    assert ct.build_turn_map(vtt((0, "Just one long speaker with no markers at all.")), ALLIN_ROSTER) is None


# ---------------------------------------------------------------------------
# 1. A directed question names the next turn
# ---------------------------------------------------------------------------

def test_directed_question_names_the_next_turn():
    # ep 680, 22:47 and 28:52 (Exa: Chamath asks Jason; Jason answers)
    tm = tmap(ALLIN_ROSTER,
              (0, "Everybody else just still has an enormous amount of work to do. Jason, what's your take on all of this?"),
              (10, ">> Yeah, so I've been thinking about it from two vectors. Who should make the decision?"))
    t = tm.turns[1]
    assert (t.name, t.evidence) == ("Jason Calacanis", "directed_question")
    assert "Jason, what's your take" in t.cue


def test_handoff_after_a_run_of_questions_names_the_next_turn():
    # ep 679, 11:19 -> Alex 11:41
    tm = tmap(MOON_ROSTER,
              (0, "A lot of layers here. So, Alex, I'm going to you first. Is this a national security failure? "
                  "Is it a political hit job? Or is this just a CEO who made a lot of wrong decisions? What are your thoughts"),
              (20, ">> I'll say as a preliminary matter, we don't have all the facts yet."))
    assert tm.turns[1].name == "Alex Wissner-Gross"


def test_whisper_and_caption_spellings_of_names_are_matched():
    tm = tmap(MOON_ROSTER,
              (0, "Thank you. What should they be doing? Imad, what would you be doing if you were running OpenAI?"),
              (10, ">> I'd define it properly for a start, you know."))
    assert tm.turns[1].name == "Emad Mostaque"
    tm = tmap(ALLIN_ROSTER,
              (0, "I think this company could even be massively undervalued at this point. What do you think, Sax?"),
              (10, ">> Well, I said on a previous podcast that they were creating the most valuable monopoly."))
    assert tm.turns[1].name == "David Sacks"


# ---------------------------------------------------------------------------
# 2. With no cue, the turn stays unnamed
# ---------------------------------------------------------------------------

def test_no_cue_leaves_the_turn_unnamed():
    tm = tmap(ALLIN_ROSTER,
              (0, "China benefits from this because Jensen is a tentpole of our entire AI ecosystem."),
              (10, ">> Wait, you're saying Jensen made enemies of certain people in America?"),
              (20, ">> Guys, this is not in doubt."))
    assert [t.name for t in tm.turns] == [None, None, None]


def test_third_person_mention_and_reply_address_are_not_handoffs():
    tm = tmap(ALLIN_ROSTER,
              (0, "But yeah, look, I think Freeberg makes a good point which is what is the crime here?"),
              (10, ">> So let's see how this all plays out."),
              (20, ">> I agree with Chamath."),
              (30, ">> It's a great question."),
              (40, ">> Sacks, I agree with you on the economics."),
              (50, ">> Thanks, Jason."),
              (60, ">> Okay."))
    assert all(t.name is None for t in tm.turns)


def test_mid_sentence_name_is_not_a_handoff():
    # ep 680, 15:24: Chamath to Sacks "a fifth question though to yours, Sax, which is why now?";
    # FRIEDBERG answered (Exa 15:41). Naming the next turn Sacks would be wrong.
    tm = tmap(ALLIN_ROSTER,
              (0, "I think there's a fifth question though to yours, Sax, which is why at all and why now? "
                  "What did they see where they felt this had to happen and then why now?"),
              (15, ">> And the other discrediting affair stories coming out in a coordinated way at the same time?"))
    assert tm.turns[1].name is None


def test_answer_already_inside_the_turn_means_a_missed_marker_no_name():
    # ep 679, 15:28-16:15: captions missed the '>>' before Salim's answer, so the next marked turn
    # is Peter ("Alex, I mean Salim, they were..."). It must not be named Salim.
    tm = tmap(MOON_ROSTER,
              (0, "Having had battles with Nvidia about open weight models. Salim, what's your take here, pal? "
                  "I think it's clear. I'm wondering why the board acted so fast. Like you could have waited a few "
                  "days. You could have launched a board investigation. So this seems to be a coordinated."),
              (30, ">> Alex I mean Salim, they were. I just think at this point they told Jensen, listen."))
    assert tm.turns[1].name is None


def test_sentence_split_by_a_spurious_marker_is_not_a_handoff():
    # ep 679, 34:40: Alex "It certainly would be hilarious, Peter, >> if Jensen ended up becoming CEO..."
    tm = tmap(MOON_ROSTER,
              (0, "It certainly would be hilarious, Peter,"),
              (2, ">> if Jensen ended up becoming CEO of the TerraFab and then SpaceX acquires Nvidia."))
    assert tm.turns[1].name is None


def test_name_stops_at_a_missed_marker_lowercase_restart():
    # ep 680, 28:52: Jason's answer runs on into Friedberg ("... massive way. just taking a broader view")
    tm = tmap(ALLIN_ROSTER,
              (0, "It has not changed their homework. Jason, what's your take on all of this?"),
              (10, ">> Yeah, so I've been thinking about it from two vectors. I'm speculating here in a massive way. "
                   "just taking a broader view on the role that Nvidia is playing currently, it may be about slowing "
                   "down the US AI economy."))
    t = tm.turns[1]
    assert t.name == "Jason Calacanis"
    assert tm.speaker_for("I've been thinking about it from two vectors")["status"] == "named"
    assert tm.speaker_for("taking a broader view on the role that Nvidia is playing currently")["status"] == "unnamed"


def test_two_people_addressed_is_ambiguous():
    tm = tmap(ALLIN_ROSTER,
              (0, "Okay. Sacks, Chamath, what do you guys think?"),
              (10, ">> Look, I think it's beyond obvious."))
    assert tm.turns[1].name is None


# ---------------------------------------------------------------------------
# 3. A clip voice is never treated as a host
# ---------------------------------------------------------------------------

def test_turn_after_a_clip_cue_is_a_clip_and_never_named():
    tm = tmap(MOON_ROSTER,
              (0, "Let's take a listen to Demis, and then let's chat about it."),
              (10, ">> The next phase which I think carries the most risk is closed RSI, closed loop."),
              (40, ">> Interesting. Is the pressure on? Salim, your thoughts?"),
              (50, ">> I'd like to just highlight one thing that he said."))
    assert tm.turns[1].clip and tm.turns[1].name is None
    assert tm.turns[3].name == "Salim Ismail"


def test_host_handoff_after_a_long_clip_with_a_missed_marker():
    # ep 679 7:43: the Fox clip turn also holds Peter's comments (captions missed the '>>'), ending
    # "So, Alex, I'm going to you first ... What are your thoughts" -> Alex answers at 11:41.
    fox = " ".join(["Fox News Alert, chip king Jensen is gone and there is something suspicious here."] * 12)
    tm = tmap(MOON_ROSTER,
              (0, "It's an amazing overview of what is going on. Let's take a look."),
              (10, ">> " + fox + " Well, the article doesn't say. A lot of layers here. So, Alex, I'm going to you "
                   "first. Is this a national security failure? Is it a political hit job? Or is this just a CEO who "
                   "made a lot of wrong decisions on his personal side? What are your thoughts"),
              (200, ">> I'll say as a preliminary matter, we don't have all the facts yet."))
    assert tm.turns[1].clip and tm.turns[1].name is None
    assert (tm.turns[2].name, tm.turns[2].evidence) == ("Alex Wissner-Gross", "directed_question")


def test_short_clip_ending_in_a_roster_name_does_not_hand_off():
    # A short clip (an old interview) that ends "Jason, what do you think?" is still clip audio.
    tm = tmap(ALLIN_ROSTER,
              (0, "Play the clip, Nick."),
              (5, ">> We will cure these diseases within a decade. Jason, what do you think?"),
              (10, ">> I think it's possible, yes."))
    assert tm.turns[1].clip and tm.turns[2].name is None


def test_clip_addressing_a_non_roster_person_names_nobody():
    tm = tmap(MOON_ROSTER,
              (0, "Play the clip, Nick."),
              (5, ">> Demis, what do you think about closed loop recursive self-improvement?"),
              (10, ">> I do worry about it because in the limit it is dangerous."))
    assert all(t.name is None for t in tm.turns)


def test_host_label_on_clip_words_becomes_a_clip_and_clip_label_is_kept():
    tm = tmap(MOON_ROSTER,
              (0, "Paul Christiano opened the Hinton lectures. Let's watch this video and then let's talk about this."),
              (10, ">> I think there is a high risk of an AI takeover within the next three years."),
              (20, ">> Wow. Just wow. So, Imad, what do you make of this? Do you buy this premise?"),
              (30, ">> I don't really buy it at all. Like I have a high P doom, but where is the evidence?"))
    tx = ("Paul Christiano opened the Hinton lectures. Let's watch this video. I think there is a high risk of an "
          "AI takeover within the next three years. Wow. Just wow. So, Imad, what do you make of this? Do you buy "
          "this premise? I don't really buy it at all. Like I have a high P doom, but where is the evidence?")
    ext = {"high_value_quotes": [
        {"speaker": "Peter Diamandis", "quote": "I think there is a high risk of an AI takeover within the next three years"},
        {"speaker": "Paul Christiano (clip)", "quote": "I think there is a high risk of an AI takeover within the next three years"},
        {"speaker": "one host", "quote": "I don't really buy it at all. Like I have a high P doom"},
    ]}
    sa.enforce_speaker_cues(ext, tx, MOON, show_notes=MOON_311_NOTES, turns=tm)
    q = ext["high_value_quotes"]
    assert q[0]["speaker"] == "a clip"                  # never the host
    assert q[1]["speaker"] == "Paul Christiano (clip)"  # clip voice keeps its own name
    assert q[2]["speaker"] == "Emad Mostaque"           # named by the directed question


def test_quote_read_out_by_host_and_played_in_clip_is_placed_in_the_clip():
    # ep 679: Peter reads Christiano's line at 39:08 ("with this statement, quote, I think there is a high
    # risk ...") and the clip plays it at 40:20. The words are the clip's: never "one host" or Peter.
    line = "I think there is a high risk of an AI takeover within the next three years"
    tm = tmap(MOON_ROSTER,
              (0, "Paul Christiano opened the Hinton lectures in Toronto with this statement, quote, " + line +
               ". Christiano is the guy who ran the alignment team. " +
               " ".join(f"Filler sentence number {n} about the lectures and the alignment debate." for n in range(12)) +
               " Let's watch this video."),
              (60, ">> I'm going to start with the most important sentence. Uh so " + line +
               ". What I mean by an AI takeover is a situation where AIs call the shots."),
              (80, ">> Wow. Just wow."))
    d = tm.speaker_for(line)
    assert d["status"] == "clip" and d["turn"].index == 1
    tx = " ".join(t.text for t in tm.turns)
    ext = {"high_value_quotes": [{"speaker": "one host", "quote": "So " + line}]}
    sa.enforce_speaker_cues(ext, tx, MOON, show_notes=MOON_311_NOTES, turns=tm)
    assert ext["high_value_quotes"][0]["speaker"] == "a clip"


def test_moonshots_db_guest_list_is_not_used():
    # ep 679's DB guest list holds clip voices; turn names come from the roster only.
    assert set(MOON_ROSTER) == {"Peter Diamandis", "Alex Wissner-Gross", "Salim Ismail", "Emad Mostaque"}
    tm = tmap(MOON_ROSTER,
              (0, "Friend of the pod, Will, over to you. Will, what do you think?"),
              (10, ">> Users can now ask the Earth."))
    assert tm.turns[1].name is None


def test_db_clip_voices_excluded_as_ep_679_pundit_guests():
    from pundit_exclusions import is_excluded_guest_appearance
    title = ("Jensen\u2019s Departure, NVIDIA\u2019s succession plan, AI doomer response, and Demis talks RSI "
             "| MOONSHOTS #311 (recorded live)")
    for name in ("Demis Hassabis", "Paul Christiano", "Will Marshall", "Dario Amodei"):
        assert is_excluded_guest_appearance(name, title)
    assert not is_excluded_guest_appearance("Demis Hassabis", "Demis Hassabis on AGI | EP #253")


# ---------------------------------------------------------------------------
# 4. The host roster is respected
# ---------------------------------------------------------------------------

def test_absent_roster_member_is_never_assigned():
    # Dave Blundin was absent from #311; show notes narrow the roster, so "Dave?" names nobody.
    assert "Dave Blundin" not in MOON_ROSTER
    tm = tmap(MOON_ROSTER,
              (0, "Dave, unfortunately, couldn't make it today. Dave?"),
              (10, ">> I'm here in spirit."))
    assert tm.turns[1].name is None


def test_shared_first_name_is_not_a_cue():
    # "David" is both Sacks and Friedberg: not enough to name anyone.
    tm = tmap(ALLIN_ROSTER, (0, "David, what do you think?"), (10, ">> I think it's tragic."))
    assert tm.turns[1].name is None


def test_names_are_roster_spellings():
    tm = tmap(ALLIN_ROSTER, (0, "Any thoughts there, Chimath, on that claim?"), (10, ">> I think we're going to be in a recession by 2028."))
    assert tm.turns[1].name == "Chamath Palihapitiya"


def test_self_identification_and_continuation():
    tm = tmap(MOON_ROSTER,
              (0, "Welcome back everybody."),
              (5, ">> Hi, I'm Salim Ismail and I run OpenExO, and here's the thing about"),
              (10, ">> Yeah."),
              (12, ">> exponential organizations that people miss."))
    assert (tm.turns[1].name, tm.turns[1].evidence) == ("Salim Ismail", "self_identification")
    assert (tm.turns[3].name, tm.turns[3].evidence) == ("Salim Ismail", "continuation")


# ---------------------------------------------------------------------------
# Labels from turns (enforce_speaker_cues / evidence lines) and logging
# ---------------------------------------------------------------------------

ALLIN_TX = (
    "Chamath, you're pretty close to this, but if Jensen's out of the picture, is there someone in Nvidia that "
    "continues running that effort? Look, I mean, I think Colette Kress and the head of M&A are really smart, "
    "good guys, but you are kind of right. The bank of Nvidia ran through Jensen and it's not clear what happens "
    "now. I think it's beyond obvious. You asked the question, who benefits? It's China. China benefits from this."
)


def allin_turns():
    return tmap(ALLIN_ROSTER,
                (0, "Chamath, you're pretty close to this, but if Jensen's out of the picture, is there someone in Nvidia "
                    "that continues running that effort?"),
                (10, ">> Look, I mean, I think Colette Kress and the head of M&A are really smart, good guys, but you are "
                     "kind of right. The bank of Nvidia ran through Jensen and it's not clear what happens now."),
                (30, ">> I think it's beyond obvious. You asked the question, who benefits? It's China. China benefits from this."))


def test_turn_names_fix_wrong_names_and_upgrade_one_host(tmp_path):
    log = tmp_path / "speaker_turn_names.jsonl"
    relog = tmp_path / "speaker_cue_relabels.jsonl"
    ext = {
        "high_value_quotes": [
            {"speaker": "David Friedberg", "quote": "The bank of Nvidia ran through Jensen and it's not clear what happens now"},
            {"speaker": "one host", "quote": "I think Colette Kress and the head of M&A are really smart, good guys"},
            {"speaker": "Chamath Palihapitiya", "quote": "You asked the question, who benefits? It's China. China benefits from this"},
        ],
        "major_claims": [{"claim": "The bank of Nvidia depended on Jensen", "speaker": "",
                          "evidence": "The bank of Nvidia ran through Jensen and it's not clear what happens now"}],
    }
    sa.enforce_speaker_cues(ext, ALLIN_TX, ALLIN, turns=allin_turns(), log_path=relog, turn_log_path=log)
    q = ext["high_value_quotes"]
    assert q[0]["speaker"] == "Chamath Palihapitiya"   # A5: "bank of Nvidia" was credited to Friedberg
    assert q[1]["speaker"] == "Chamath Palihapitiya"   # "one host" gets the name back
    assert q[2]["speaker"] == "one host"               # no cue for the Sacks turn: no name
    assert ext["major_claims"][0]["speaker"] == "Chamath Palihapitiya"
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert {r["new_speaker"] for r in rows} == {"Chamath Palihapitiya"}
    assert all(r["evidence"] == "directed_question" and "Chamath, you're pretty close" in r["cue"] for r in rows)
    assert all(r["turn_start"] for r in rows)
    re_rows = [json.loads(l) for l in relog.read_text().splitlines()]
    assert re_rows[0]["speaker"] == "Chamath Palihapitiya" and re_rows[0]["new_speaker"] == "one host"


def test_quote_not_in_captions_falls_back_to_826_cue_check():
    ext = {"high_value_quotes": [{"speaker": "David Sacks", "quote": "a sentence the captions never had in any form"}]}
    sa.enforce_speaker_cues(ext, ALLIN_TX + " a sentence the captions never had in any form", ALLIN, turns=allin_turns())
    assert ext["high_value_quotes"][0]["speaker"] == "one host"


def test_evidence_lines_use_turn_names():
    lines = [
        "David Friedberg: The bank of Nvidia ran through Jensen and it's not clear what happens now",
        "Chamath Palihapitiya: You asked the question, who benefits? It's China. China benefits from this.",
    ]
    kept, drops = sa.verify_evidence_lines(lines, ALLIN_TX, podcast_name=ALLIN, turns=allin_turns(),
                                           turn_log_path="/dev/null")
    assert drops == []
    assert kept[0].startswith("Chamath Palihapitiya: The bank of Nvidia")
    assert kept[1].startswith("one host: You asked the question")


# ---------------------------------------------------------------------------
# 5. The quote checker still drops non-verbatim lines
# ---------------------------------------------------------------------------

def test_quote_checker_still_drops_non_verbatim_lines_with_turns(tmp_path):
    analysis = {
        "notable_quotes": [
            {"speaker": "Chamath Palihapitiya", "quote": "The bank of Nvidia ran through Jensen and it's not clear what happens now"},
            {"speaker": "Chamath Palihapitiya", "quote": "Nvidia's lending arm is now permanently closed and every startup will starve"},
        ],
        "guests": [], "hosts": [],
    }
    log = tmp_path / "quote_check_drops.jsonl"
    rep = sa.apply_attribution_rules(analysis, ALLIN_TX, ALLIN, log_path=log, turns=allin_turns())
    assert [q["quote"][:20] for q in analysis["notable_quotes"]] == ["The bank of Nvidia r"]
    assert len(rep["dropped_quotes"]) == 1
    lines, drops = sa.verify_evidence_lines(
        ["Chamath Palihapitiya: the bank is closed forever and nobody gets paid"], ALLIN_TX,
        podcast_name=ALLIN, turns=allin_turns(), log_path=log)
    assert lines == [] and len(drops) == 1


# ---------------------------------------------------------------------------
# Loading captions for a transcript
# ---------------------------------------------------------------------------

FILLER = [f"Point number {n} is about {w} and why the {w} market matters for chips in year {2000 + n}."
          for n, w in enumerate(["memory", "power", "fabs", "cooling", "export", "pricing", "networking", "software",
                                 "robotics", "satellites", "batteries", "lasers", "storage", "packaging", "talent",
                                 "capital", "tariffs", "lithography", "inference", "training"])]


def test_load_turn_map_needs_matching_text_and_panel_show(tmp_path):
    tx = ALLIN_TX + " " + " ".join(FILLER)
    tx_path = tmp_path / "ALLIN-E297_Ch.txt"
    tx_path.write_text(tx)
    cap = ct.caption_path_for(tx_path)
    assert cap.name == "ALLIN-E297_Ch.yt.vtt"
    body = vtt(
        (0, "Chamath, you're pretty close to this, but if Jensen's out of the picture, is there someone in Nvidia "
            "that continues running that effort?"),
        (10, ">> Look, I mean, I think Colette Kress and the head of M&A are really smart, good guys, but you are "
             "kind of right. The bank of Nvidia ran through Jensen and it's not clear what happens now."),
        (30, ">> I think it's beyond obvious. You asked the question, who benefits? It's China. China benefits from this. "
             + " ".join(FILLER)))
    cap.write_text(body)
    tm = ct.load_turn_map_for_transcript(tx_path, tx, ALLIN, fetch=False)
    assert tm is not None and tm.turns[1].name == "Chamath Palihapitiya"
    # not a panel show -> unused
    assert ct.load_turn_map_for_transcript(tx_path, tx, "Odd Lots", fetch=False) is None
    # captions of a different episode -> rejected
    other = tmp_path / "OTHER.txt"
    other_tx = " ".join(f"Bond auction {n} cleared at {n} basis points over the {n}-year note today." for n in range(40))
    other.write_text(other_tx)
    ct.caption_path_for(other).write_text(body)
    assert ct.load_turn_map_for_transcript(other, other_tx, ALLIN, fetch=False) is None


def test_fetch_is_skipped_without_yt_dlp(tmp_path, monkeypatch):
    monkeypatch.setenv("YT_DLP_BIN", str(tmp_path / "missing-yt-dlp"))
    monkeypatch.setattr(ct.shutil, "which", lambda *_: None)
    assert ct.fetch_youtube_captions(tmp_path / "x.txt", ALLIN, "Some title") is None


def test_a_clip_evidence_line_counts_as_an_honest_label():
    from generate_deepdives import ONE_HOST_LINE_RE
    ev = "a clip: I think there is a high risk of an AI takeover\none host: We don't have all the facts yet."
    assert ONE_HOST_LINE_RE.findall(ev) == ["a clip", "one host"]
