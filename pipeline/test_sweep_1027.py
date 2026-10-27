"""Oct 27 2026 daily site check (cos/sweep_1027/fixes.md): id-keyed export-time fixes for
insights 622-626, the Overton speaker fields (episode-gated term rules, now also applied to
archive.json), and pundits 580/583/584/538. Rules re-apply on export, stay scoped, and are idempotent."""
import copy, json
import export_data
import publish_guard
import pundit_exclusions

TITLE_615 = "Reinventing School for the AI Era | Joe Liemandt, Gagan Biyani & Erik Torenberg"
SUM_626 = ("Joel Amond says Alpha School uses a learning engine. Amond cites internal survey data. "
           "It plans a similar reinvention through AJA/Horowitz & Dresden Academy, with more.")


def _payload():
    return {
        "archive": {"insights": [
            {"id": 626, "podcast_episode_id": 615, "title": "Reinventing School", "summary": SUM_626,
             "notable_quotes": [{"speaker": "Joel Amond", "quote": "We throw a teacher in front of the classroom."}]},
            {"id": 622, "podcast_episode_id": 611, "title": "Citrini",
             "notable_quotes": [{"speaker": "Satrini", "quote": "One."}, {"speaker": "Satrini", "quote": "Two."},
                                {"speaker": "Satrini", "quote": "If you're relying on the combined lab AR to be $500 billion, that's a stretch."}]},
            {"id": 623, "podcast_episode_id": 612, "title": "OpenAI",
             "notable_quotes": [{"speaker": "James Sun", "quote": "A."}, {"speaker": "James Sun", "quote": "B."},
                                {"speaker": "James Sun", "quote": "One is, we run a business model is not in line with having agents use a product."}]},
            {"id": 624, "podcast_episode_id": 614, "title": "Leash",
             "notable_quotes": [{"speaker": "Ian Quigley", "quote": "A."}, {"speaker": "Ian Quigley", "quote": "B."},
                                {"speaker": "Ian Quigley", "quote": "But they especially abandon the lousy places fast."}]},
            {"id": 625, "podcast_episode_id": 613, "title": "Supabase", "summary": "AurionDB and Multigress ship."},
            {"id": 999, "podcast_episode_id": 998, "title": "Other", "summary": SUM_626 + " Satrini AurionDB",
             "notable_quotes": [{"speaker": "Satrini", "quote": "If you're relying on the combined lab AR to be $500 billion."}]},
        ]},
        "deepDives": {
            "626": {"id": 625, "insight_id": 626, "podcast_episode_id": 615, "insight_title": "x",
                    "catalysts": ["AJA/Horowitz & Dresden Academy publishing concrete student outcomes."],
                    "episode_evidence": "Joel Amond: We throw a teacher in front of the classroom."},
        },
    }


def test_card_fixes_by_id_and_idempotent():
    data = _payload()
    export_data._apply_summary_overrides(data)
    ins = {i["id"]: i for i in data["archive"]["insights"]}
    s = ins[626]["summary"]
    assert "Joe Liemandt says" in s and "Liemandt cites" in s
    assert "through the Horowitz and Andreessen Academy," in s and "Amond" not in s and "Dresden" not in s
    assert ins[626]["notable_quotes"][0]["speaker"] == "Joe Liemandt"
    dd = data["deepDives"]["626"]
    assert dd["catalysts"][0].startswith("Horowitz and Andreessen Academy publishing")
    assert dd["episode_evidence"].startswith("Joe Liemandt:")
    assert [q["speaker"] for q in ins[622]["notable_quotes"]] == ["Citrini", "Citrini"]
    for i in (622, 623, 624):
        assert len(ins[i]["notable_quotes"]) == 2, i
    assert ins[625]["summary"] == "OrioleDB and Multigres ship."
    # scoped: another episode with the same text is untouched
    assert ins[999]["summary"] == SUM_626 + " Satrini AurionDB"
    assert len(ins[999]["notable_quotes"]) == 1
    once = copy.deepcopy(data)
    export_data._apply_summary_overrides(data)
    assert data == once
    assert publish_guard.find_style_gate_hits({"a": ins[626], "d": dd}) == []


OVERTON = {281: (615, "Joe Liemandt, Gagan Biyani, Erik Torenberg"), 313: (611, "Citrini"),
           300: (611, "Citrini"), 254: (611, "Citrini"), 57: (611, "Citrini"),
           264: (612, "James Sun, Ari Weinstein"), 114: (612, "James Sun, Ari Weinstein"),
           312: (597, "Chamath Palihapitiya"), 43: (597, "Chamath Palihapitiya"), 10: (597, "Chamath Palihapitiya")}


def _overton(ep_shift=0):
    return {"overton": [{"id": i, "term": f"t{i}", "last_mentioned_episode_id": ep + ep_shift,
                         "last_mentioned_speaker": "Satrini (not provided in transcript)"}
                        for i, (ep, _) in OVERTON.items()]}


def test_overton_speakers_gated_on_episode():
    c = _overton()
    export_data._apply_overton_term_overrides(c)
    assert {t["id"]: t["last_mentioned_speaker"] for t in c["overton"]} == {i: v for i, (_, v) in OVERTON.items()}
    once = copy.deepcopy(c)
    export_data._apply_overton_term_overrides(c)
    assert c == once
    # a newer mention (different episode) keeps the export's own speaker
    c = _overton(ep_shift=1000)
    export_data._apply_overton_term_overrides(c)
    assert all(t["last_mentioned_speaker"].startswith("Satrini") for t in c["overton"])


def test_archive_json_gets_overton_rules(tmp_path):
    (tmp_path / "archive.json").write_text(json.dumps(_overton()))
    export_data._apply_summary_overrides_to_files(tmp_path)
    got = json.loads((tmp_path / "archive.json").read_text())
    assert {t["id"]: t["last_mentioned_speaker"] for t in got["overton"]} == {i: v for i, (_, v) in OVERTON.items()}


def _pundits():
    def p(pid, title, **kw):
        return dict({"id": pid, "name": f"p{pid}", "slug": f"p{pid}", "mention_score": 1, "last_episode_title": title,
                     "last_proof_snippet": "Some words.", "last_proof_cite": "Show • date • ep"}, **kw)
    return [p(583, TITLE_615, bio="Co-founder of Horowitz and Dresden Academy.",
              supporting_takeaway="Joel Amond reported that 90% love school."),
            p(584, TITLE_615, supporting_takeaway="Joel Amond reported it."),
            p(580, "OpenAI: When AI Agents Use Computers Faster Than You"),
            p(538, "anything"),
            p(5830, "Other episode")]


def test_pundit_fixes():
    rows = {"pundits": _pundits()}
    export_data._apply_summary_overrides(rows)
    by = {p["id"]: p for p in rows["pundits"]}
    assert 584 not in by  # host hidden (#10)
    assert by[583]["bio"] == "Co-founder of Horowitz and Andreessen Academy."
    assert by[583]["supporting_takeaway"] == "Joe Liemandt reported that 90% love school."
    for pid in (583, 580, 538):
        assert not by[pid].get("last_proof_snippet") and not by[pid].get("last_proof_cite"), pid
    assert by[5830]["last_proof_snippet"] == "Some words."
    assert 584 in pundit_exclusions.EXCLUDED_PUNDIT_IDS


def test_pundit_gate_holds_for_new_episode():
    rows = {"pundits": [{"id": 583, "name": "x", "slug": "x", "mention_score": 1, "last_episode_title": "A later episode",
                         "last_proof_snippet": "New words.", "last_proof_cite": "c"},
                        {"id": 580, "name": "y", "slug": "y", "mention_score": 1, "last_episode_title": "A later episode",
                         "last_proof_snippet": "New words.", "last_proof_cite": "c"}]}
    export_data._apply_summary_overrides(rows)
    assert all(p["last_proof_snippet"] == "New words." for p in rows["pundits"])
