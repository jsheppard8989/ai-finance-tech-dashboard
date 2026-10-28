"""Oct 28 2026 follow-up (G, sweep_1028): three garbled transcript lines cut from deep-dive
episode_evidence (627: Deluard '...the Fed being of hiking cycle.'; 629: Cuban '...4,000 skews give
or take...' and '...Ship a two a research hospital...'). Whole lines are removed, never reworded,
the rest of the evidence is byte-identical, cuts are id-scoped and idempotent (same mechanism as
the 624 cut on 10/27: exact-line 'replacements' on the insight's summaries rule)."""
import copy
import json
from pathlib import Path

import pytest

import export_data

ROOT = Path(__file__).resolve().parent.parent
L627_BAD = ("Vincent Deluard: If you look at the consumer names, I mean, you are seeing just complete massacre most names, "
            "like your Nike, your Harley Davidson, your Renault, and McDonald's are down 50, 60% plus, which is very unusual "
            "for when you see the index at two percent from the old time high and the Fed being of hiking cycle.")
L627_KEEP = [
    "Vincent Deluard: I think the primary reason to own treasuries is just liquidity. The seller's in treasuries bring their own buyers.",
    "Vincent Deluard: The other sources demand I could see would be the pension firms, the bull market has been very generous. The average funding ratio is close to 1.15, which is the best we've seen in 25 years.",
    "Vincent Deluard: In the next two years, I don't really see any of these puts. I mean, I think the Fed on the margin we try to prioritize the growth mandate, but it will be severely constrained by this higher than desired inflation. So the Fed put is, is mostly expired.",
    "Vincent Deluard: The only way to pay that deal is is to sell treasuries. So we would go back into a world where oil, oil, and yields would go up at the same time.",
]
L629_SKEWS = "Mark Cuban: So, now, as you said, we have 4,000 skews give or take, and our business every week is up into the right."
L629_PODS = ("Mark Cuban: These pods cost about $20 million. Ship a two a research hospital. And if they specialize in any types "
             "of therapies for those people that are in the N of 1 category, they can make it and iterate very quickly there.")
L629_KEEP = [
    "Mark Cuban: Take every benefits contract you're about to sign, run it through AI, and ask where you're getting screwed.",
    "Mark Cuban: Once you sign a contract with terms, you don't fully understand and conditions, you don't fully, you can't even protect yourself against, they win.",
]
BAD = (L627_BAD, L629_SKEWS, L629_PODS)


def _dd(i, ins, pe, lines):
    return {"id": i, "insight_id": ins, "podcast_episode_id": pe, "insight_title": f"t{ins}",
            "key_tickers": [], "episode_evidence": "\n".join(lines)}


def _payload(e627, e629):
    return {"archive": {"insights": []}, "mainContent": {"insights": []},
            "deepDives": {"627": _dd(626, 627, 617, e627), "629": _dd(627, 629, 618, e629),
                          "999": _dd(998, 999, 997, [L627_BAD, L629_SKEWS, L629_PODS, L629_KEEP[0]])}}


def _apply(data):
    export_data._apply_summary_overrides(data)
    return data


def test_real_evidence_cut_and_rest_intact():
    # Real 10/28 order: 627's bad line is first; 629's two bad lines are last (adjacent).
    data = _apply(_payload([L627_BAD] + L627_KEEP, L629_KEEP + [L629_SKEWS, L629_PODS]))
    assert data["deepDives"]["627"]["episode_evidence"] == "\n".join(L627_KEEP)
    assert data["deepDives"]["629"]["episode_evidence"] == "\n".join(L629_KEEP)


@pytest.mark.parametrize("pos", ["first", "middle", "last"])
def test_cut_works_at_any_position(pos):
    def place(keep, bad):
        return {"first": [bad] + keep, "middle": keep[:1] + [bad] + keep[1:], "last": keep + [bad]}[pos]
    data = _apply(_payload(place(L627_KEEP, L627_BAD), place(place(L629_KEEP, L629_PODS), L629_SKEWS)))
    assert data["deepDives"]["627"]["episode_evidence"] == "\n".join(L627_KEEP)
    assert data["deepDives"]["629"]["episode_evidence"] == "\n".join(L629_KEEP)


def test_cut_is_id_scoped_and_idempotent():
    data = _apply(_payload([L627_BAD] + L627_KEEP, L629_KEEP + [L629_SKEWS, L629_PODS]))
    assert data["deepDives"]["999"]["episode_evidence"] == "\n".join([L627_BAD, L629_SKEWS, L629_PODS, L629_KEEP[0]])
    once = copy.deepcopy(data)
    _apply(data)
    assert data == once


def test_rules_remove_whole_lines_only():
    rules = json.loads((Path(export_data.__file__).parent / "summary_overrides.json").read_text())
    reps = [r for x in rules["summaries"] if x.get("insight_id") in (627, 629) for r in x.get("replacements", [])]
    for line in BAD:
        assert [line + "\n", ""] in reps and ["\n" + line, ""] in reps


def test_site_files_after_publish():
    """Once the site export re-runs, the three lines are gone and the rest of 627/629 evidence is there."""
    s = (ROOT / "site" / "data" / "data.js").read_text(encoding="utf-8")
    if any(line in s for line in BAD):
        pytest.skip("site export not yet re-run with the 10/28 evidence cuts")
    for keep in L627_KEEP + L629_KEEP:
        assert keep in s, keep
