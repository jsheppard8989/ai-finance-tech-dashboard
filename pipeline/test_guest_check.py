import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from guest_check import is_listed_guest, is_rejected_bio, name_in_text, speaker_labels, episode_evidence
from pundit_exclusions import is_excluded_guest_appearance
import export_data


def test_name_in_title_and_fuzzy_asr():
    assert name_in_text("Ron Emmanuel", "Rahm Emanuel: Trump's Foreign Policy")
    assert name_in_text("Dr. Pushkar Ranade", "with Pushkar Ranade of Intel")
    assert not name_in_text("Bill Gross", "Bill Gates on AI")


def test_speaker_labels_line_and_colon():
    t = "Dwarkesh Patel\nHi.\nPushkar Ranade\nYes.\nSam Altman: hello\n01:01:02 – Terafab\nok"
    assert {"Dwarkesh Patel", "Pushkar Ranade", "Sam Altman"} <= speaker_labels(t)


def test_guest_kept_when_in_labels_or_notes():
    assert is_listed_guest("Pushkar Ranade", "Chips in 2045", "", ["Dwarkesh Patel", "Pushkar Ranade"]) is True
    assert is_listed_guest("Chris Auth", "Chips", "We talk with Chris Auth.", []) is True


def test_mentioned_only_is_false():
    assert is_listed_guest("Andy Jassy", "CoreWeave Crash, Bill Gates", "Besties discuss AI trade.", []) is False


def test_unverifiable_is_none():
    assert is_listed_guest("Eric Schmidt", "AI and China", "", []) is None


def test_episode_evidence_reads_meta(tmp_path):
    tp = tmp_path / "x.txt"
    tp.write_text("Host Name\nhi\nGuest Person\nyo\n")
    (tmp_path / "x.meta.json").write_text('{"show_notes": "notes here"}')
    notes, labels = episode_evidence(str(tp))
    assert notes == "notes here" and "Guest Person" in labels
    assert episode_evidence(None) == ("", set())


def test_elon_dwarkesh_excluded():
    assert is_excluded_guest_appearance("Elon Musk", "What will computer chips look like in 2045?")
    assert not is_excluded_guest_appearance("Elon Musk", "Some other episode")
    assert not is_excluded_guest_appearance("Pushkar Ranade", "What will computer chips look like in 2045?")


def test_rejected_bios():
    assert is_rejected_bio("Referenced via public comments about building Terafab")
    assert is_rejected_bio("  mentioned in passing")
    assert not is_rejected_bio("Intel CTO. Referenced often.")
    assert not is_rejected_bio(None)


def test_export_drops_mention_bios():
    obj = {"pundits": [{"name": "A", "bio": "Referenced via X"}, {"name": "B", "bio": "CEO of Y"}]}
    export_data._drop_mention_bios(obj)
    assert obj["pundits"][0]["bio"] is None and obj["pundits"][1]["bio"] == "CEO of Y"


def test_confirmed_guests_pinned_and_renamed():
    import json
    from pundit_exclusions import is_confirmed_guest_appearance, CONFIRMED_GUEST_APPEARANCES
    assert is_confirmed_guest_appearance("Adam Pervene", "Adam Foroughi, Applovin CEO: Surviving a 92% Drawdown, Ads as ML 1.0 & the $50B Game Ad Market")
    assert is_confirmed_guest_appearance("eden ha", "Why Video Agent models are next — Ethan He, xAI Grok Imagine")
    assert not is_confirmed_guest_appearance("Bill Gross", "Chamath: AGI Is Here")
    assert len(CONFIRMED_GUEST_APPEARANCES) == 9
    rules = json.loads((Path(__file__).resolve().parent / "summary_overrides.json").read_text())
    reps = dict(map(tuple, rules["global_name_replacements"]))
    for old, new in [("Adam Pervene", "Adam Foroughi"), ("Eden Ha", "Ethan He"), ("DJ Smith", "Feross Aboukhadijeh"),
                     ("Dylan Araps", "Dylan Ayrey"), ("Joel Deligarza", "Joel de la Garza"), ("Jeff Wu", "Geoffrey Woo")]:
        assert reps[old] == new


def test_name_fix_is_whole_word():
    obj = {"pundits": [{"name": "Eden Ha", "bio": "Eden Hazard is not Eden Ha."}]}
    export_data._apply_global_name_replacements(obj, [["Eden Ha", "Ethan He"]])
    assert obj["pundits"][0] == {"name": "Ethan He", "bio": "Eden Hazard is not Ethan He."}
