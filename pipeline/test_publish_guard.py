"""Tests for publish_guard.py (evening publish guard, c11bf113 regression)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import publish_guard as g

REPO = Path(__file__).resolve().parent.parent

SCRIPT = ("<script>(function(){function o(){var h=decodeURIComponent((location.hash||'').slice(1));"
          "if(!h)return;var e=document.getElementById(h);if(e&&e.tagName==='DETAILS'){e.open=true;"
          "e.scrollIntoView();}}window.addEventListener('hashchange',o);o();})();</script>")


def page(ids=("tsla", "frmi"), script=True, extra=""):
    cards = "".join(f'<details class="ev" id="{i}"><summary>{i} We expect: lower</summary>{extra}</details>' for i in ids)
    return f"<html><body>{cards}{SCRIPT if script else ''}</body></html>"


def data_js(generated='"2026-10-14T05:20:54"', snap='{"QQQ": {"price": 1}}', summary="A fine plan."):
    return ("// Auto-generated data file\n\nconst dashboardData = {\n  schemaVersion: 2,\n"
            f"  generatedAt: {generated},\n  priceSnapshot: {snap},\n"
            "  // tickerScores retired\n  tickerScores: [],\n"
            f'  archive: {{"insights": [{{"title": "x", "summary": "{summary}"}}]}}\n}};\n')


class Site:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        self.site = self.root / "site"
        self.pipe = self.root / "pipeline"
        (self.site / "data").mkdir(parents=True)
        self.pipe.mkdir()
        self.write(page(), data_js())
        (self.pipe / "summary_overrides.json").write_text(json.dumps({
            "name_replacements": [["Jim Weederhold", "Jim Wiederhold"]],
            "global_replacements": [["infrastructure bets.", "infrastructure choices."]],
            "summaries": [{"insight_id": 585, "replacements": [["Dahlia provides", "Dalio provides"]]}],
        }))
        (self.pipe / "guest_overrides.json").write_text(json.dumps({
            "fixes": {"Ben Kulandian": "Ben Pouladian"},
            "episode_title_guest": {"Cathie Wood on X | EP #296 | Moonshots Live": "Cathie Wood"},
        }))
        (self.pipe / "trap_home_override.json").write_text(json.dumps({
            "last_monitored": [{"id": "frmi"}], "upcoming_watches": [{"trap_id": "tsla"}]}))
        (self.site / "data" / "podcast_guests.json").write_text(json.dumps([
            {"name": "Cathie Wood", "last_episode_title": "Cathie Wood on X | EP #296 | Moonshots Live"},
            {"name": "Palmer Luckey", "last_episode_title": "Palmer Luckey | Moonshots Live | EP #295"}]))
        self.baseline = {"HEAD": self.snapshot()}

    def write(self, html=None, js=None):
        if html is not None:
            (self.site / "trap-map.html").write_text(html)
        if js is not None:
            (self.site / "data" / "data.js").write_text(js)

    def snapshot(self):
        out = {"trap-map.html": (self.site / "trap-map.html").read_text()}
        for p in (self.site / "data").iterdir():
            out[f"data/{p.name}"] = p.read_text()
        return out

    def run(self):
        return g.run_publish_guard(self.site, self.pipe, baselines=self.baseline)


class TestPublishGuard(unittest.TestCase):
    def setUp(self):
        self.s = Site()

    def tearDown(self):
        shutil.rmtree(self.s.root, ignore_errors=True)

    def assertBlocked(self, needle):
        ok, reasons = self.s.run()
        self.assertFalse(ok)
        self.assertTrue(any(needle in r for r in reasons), reasons)

    def test_clean_site_passes(self):
        self.assertEqual(self.s.run(), (True, []))

    def test_alert_line_printed(self):
        import io, contextlib
        self.s.write(html=page(ids=("frmi",)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.s.run()
        self.assertIn("ALERT publish guard: Trap Map card ids dropped", buf.getvalue())

    def test_dropped_baseline_card_id_blocks(self):
        self.s.baseline = {"HEAD": dict(self.s.baseline["HEAD"], **{"trap-map.html": page(ids=("tsla", "frmi", "tsat"))})}
        self.assertBlocked("#tsat")

    def test_dropped_pinned_card_id_blocks_without_baseline(self):
        self.s.baseline = {}
        self.s.write(html=page(ids=("tsla",)))
        self.assertBlocked("#frmi")

    def test_c11bf113_shape_ids_stripped_blocks(self):
        self.s.write(html=page().replace(' id="tsla"', "").replace(' id="frmi"', ""))
        self.assertBlocked("Trap Map card ids dropped")

    def test_missing_open_linked_card_script_blocks(self):
        self.s.write(html=page(script=False))
        self.assertBlocked("open-linked-card script")

    def test_name_replacement_undone_blocks(self):
        self.s.write(js=data_js(summary="Jim Weederhold said so."))
        self.assertBlocked("name_replacements 'Jim Weederhold'")

    def test_global_replacement_undone_blocks(self):
        self.s.write(js=data_js(summary="model releases and infrastructure bets."))
        self.assertBlocked("global_replacements")

    def test_summaries_replacement_undone_blocks(self):
        self.s.write(js=data_js(summary="Dahlia provides context."))
        self.assertBlocked("summaries[585]")

    def test_preexisting_old_text_in_baseline_is_not_a_regression(self):
        self.s.write(js=data_js(summary="Jim Weederhold said so."))
        self.s.baseline = {"HEAD": self.s.snapshot()}
        self.assertEqual(self.s.run(), (True, []))

    def test_global_moonshots_guest_fix_blocks(self):
        (self.s.pipe / "guest_overrides.json").write_text(json.dumps({"fixes": {"Moonshots Live": "Cathie Wood"}}))
        self.assertBlocked("Moonshots fix undone")

    def test_cathie_on_other_moonshots_episode_blocks(self):
        (self.s.site / "data" / "podcast_guests.json").write_text(json.dumps([
            {"name": "Cathie Wood", "last_episode_title": "Palmer Luckey | Moonshots Live | EP #295"}]))
        self.assertBlocked("Moonshots fix undone")

    def test_bet_wording_in_data_blocks(self):
        self.s.baseline = {}
        self.s.write(js=data_js(summary="He is betting on chips."))
        self.assertBlocked("style gate")

    def test_bet_wording_in_trap_card_blocks(self):
        self.s.write(html=page(extra="<p>Our bet: it falls.</p>"))
        self.assertBlocked("style gate")

    def test_other_bets_and_quotes_allowed(self):
        self.s.write(js=data_js(summary="Alphabet Other Bets grew."))
        self.assertEqual(self.s.run(), (True, []))

    def test_empty_generated_at_blocks(self):
        self.s.write(js=data_js(generated='""'))
        self.assertBlocked("generatedAt")

    def test_empty_price_snapshot_blocks(self):
        self.s.write(js=data_js(snap="{}"))
        self.assertBlocked("priceSnapshot")

    def test_live_site_passes(self):
        """The committed site on this branch (= live main) must pass, so the 10:55 PM ship check isn't blocked."""
        if subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True).returncode != 0:
            self.skipTest("not a git checkout")
        ok, reasons = g.run_publish_guard(REPO / "site", REPO / "pipeline", REPO, baselines=g.load_baselines(REPO, refs=["HEAD"]))
        self.assertTrue(ok, reasons)


class TestPublishPathWiring(unittest.TestCase):
    def test_publish_site_calls_guard_before_push(self):
        src = (REPO / "pipeline" / "publish_site.py").read_text()
        self.assertLess(src.index("run_publish_guard("), src.index("git_push(commit"))
        self.assertLess(src.index("run_publish_guard("), src.index("if args.dry_run:"))

    def test_git_push_runs_guard_before_commit(self):
        src = (REPO / "pipeline" / "auto_pipeline.py").read_text()
        body = src[src.index("def git_push("):]
        self.assertLess(body.index("run_publish_guard("), body.index('["git", "commit"'))


if __name__ == "__main__":
    unittest.main()
