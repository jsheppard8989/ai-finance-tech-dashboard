"""Tests for process_checks (Red Team Fixes 1-5, Oct 16 2026) and its publish_guard wiring."""
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

import process_checks as pc
import publish_guard as g
import ungraded_sweep as us

REPO = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 16)

CARD = ('<details class="ev" id="{id}"><summary><span class="date">{d}</span></summary><div class="body"><dl>'
        '<dt>What would prove us wrong</dt><dd>{w}</dd><dt>Date source</dt><dd>{src}</dd>{extra}</dl></div></details>')


class Site:
    def __init__(self, cards=(), traps=None, data=None, extra_json=None, html_extra=""):
        self.root = Path(tempfile.mkdtemp())
        self.site = self.root / "site"
        (self.site / "data").mkdir(parents=True)
        body = "".join(CARD.format(**{"src": "", "extra": "", **c}) for c in cards)
        (self.site / "trap-map.html").write_text(f"<html><body>{body}{html_extra}</body></html>")
        (self.site / "data" / "trap_map.json").write_text(json.dumps({"as_of": "2026-10-15", "traps": traps or []}))
        d = {"generatedAt": "x", "priceSnapshot": {"A": 1}, **(data or {})}
        (self.site / "data" / "data.js").write_text("const dashboardData = " + json.dumps(d, indent=1) + ";\n")
        for name, doc in (extra_json or {}).items():
            (self.site / "data" / name).write_text(json.dumps(doc))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class WrongIf(unittest.TestCase):
    def test_line_parts(self):
        self.assertEqual(pc.lint_line("Revenue under $318M in the Q3 10-Q, due by Nov 9"), [])
        self.assertEqual(set(pc.lint_line("A funded refinancing is filed.")), {"date", "number"})
        self.assertEqual(set(pc.lint_line("Cash burn shrinks two quarters in a row.")), {"date", "number", "source"})
        self.assertEqual(pc.lint_line("below $135 by Dec 14, 2026", extra_source="SEC 8-K"), [])
        self.assertIn("number", pc.lint_line("Falls by Oct 30 2026 per the 10-Q"))  # a date alone is not the number

    def test_report_and_pct(self):
        s = Site(cards=[{"id": "a", "d": "Wed Oct 21", "w": "Revenue under $318M in the 10-Q by Nov 9"},
                        {"id": "b", "d": "Wed Oct 21", "w": "A funded refinancing is filed."}],
                 traps=[{"id": "t", "drop_if": "PJM BRA under $100/MW-day by Dec 2026"}],
                 data={"deepDives": {"1": {"falsification_tracks": ["Share falls."]}}})
        try:
            r = pc.check_wrong_if(s.site)
            self.assertEqual((r["lines"], r["failures"], r["pct_compliant"]), (4, 2, 50.0))
            self.assertEqual(r["by_surface"]["data.js"]["failures"], 1)
        finally:
            s.close()


class Derived(unittest.TestCase):
    def test_template_and_mismatch(self):
        figs = [{"id": "l1", "total": 2430, "unit": "M", "parts": [{"value": 328.4}, {"value": 1300}, {"value": 797.6}], "tolerance": 5},
                {"id": "l1b", "total": 2430, "unit": "M", "parts": [{"value": 328.4}, {"value": 1370}, {"value": 797.6}], "tolerance": 5},
                {"id": "ref", "total": 4852, "parts": [{"value": "l1"}, {"value": "l1"}], "tolerance": 5},
                {"id": "txt", "total": 3, "parts": [1, 2], "total_text": "about 3 widgets"}]
        s = Site(extra_json={"derived_figures.json": dict(pc.DERIVED_TEMPLATE, figures=figs)})
        try:
            r = pc.check_derived(s.site)
            ids = sorted(m["id"] for m in r["mismatches"])
            self.assertEqual(ids, ["l1b", "txt"])
        finally:
            s.close()

    def test_shipped_map_is_empty_documented(self):
        doc = json.loads((REPO / "site" / "data" / "derived_figures.json").read_text())
        self.assertEqual(doc["figures"], [])
        self.assertIn("_example", doc)
        self.assertEqual(pc.check_derived(REPO / "site")["mismatches"], [])


class Ungraded(unittest.TestCase):
    def test_sweep(self):
        s = Site(cards=[{"id": "past", "d": "Fri Oct 9", "w": "x"}, {"id": "future", "d": "Wed Oct 21", "w": "x"},
                        {"id": "done", "d": "Thu Oct 1", "w": "x", "extra": "<dt>Outcome</dt><dd>happened</dd>"}],
                 traps=[{"id": "t", "next_datapoint": {"expected_date": "2026-09-30"}},
                        {"id": "g", "next_datapoint": {"expected_date": "2026-09-30"}, "outcome": "didn't, 10-Q"}],
                 extra_json={"trap_map_home.json": {"upcoming_watches": [{"trap_id": "h", "date_label": "Tue Oct 13", "what": "w"}]}})
        try:
            got = sorted(i["where"] for i in pc.ungraded_items(s.site, TODAY))
            self.assertEqual(got, ["trap-map.html#past", "trap_map.json t.next_datapoint", "trap_map_home.json upcoming_watches h"])
            out = Path(tempfile.mkdtemp())
            us.main(["--site", str(s.site), "--out-dir", str(out), "--date", "2026-10-16"])
            md = (out / "ungraded_guard_2026-10-16.md").read_text()
            self.assertIn("## Ungraded: 3", md)
            self.assertFalse((out / "ungraded_2026-10-16.md").exists())  # G's file is never written
        finally:
            s.close()


class FactGate(unittest.TestCase):
    def run_guard(self, s, today):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok, reasons = g.run_publish_guard(s.site, REPO / "pipeline", s.root, baselines={}, today=today)
        return ok, reasons, buf.getvalue()

    def test_fact_without_url_blocks(self):
        s = Site(html_extra="<ul><li>FACT: SpaceX has 15 planned pads.</li></ul>")
        try:
            ok, reasons, out = self.run_guard(s, TODAY)
            self.assertFalse(ok)
            self.assertTrue(any("FACT gate" in r for r in reasons))
            self.assertIn("ALERT publish guard: FACT gate", out)
        finally:
            s.close()

    def test_fact_with_url_or_pending_passes(self):
        s = Site(html_extra='<ul><li>FACT: 15 pads (<a href="https://sec.gov/x">SEC</a>)</li>'
                           '<li>FACT: 2 GW goal. PENDING owner: Scout due: 2026-10-17 12:00 CT</li></ul>',
                 data={"items": [{"label": "FACT", "text": "x", "url": "https://a.b/c"}]})
        try:
            self.assertEqual(pc.check_fact_gate(s.site), [])
        finally:
            s.close()

    def test_json_fact_label(self):
        s = Site(data={"items": [{"label": "FACT", "text": "26B of rentals"}]})
        try:
            self.assertEqual(len(pc.check_fact_gate(s.site)), 1)
            b, w, _ = pc.run_process_checks(s.site, date(2026, 10, 15), emit=lambda *_: None)
            self.assertEqual(b, [])  # before FACT_GATE_BLOCK_FROM: warn only
            self.assertTrue(any("blocks from" in x for x in w))
        finally:
            s.close()

    def test_lowercase_fact_word_is_not_a_label(self):
        s = Site(html_extra="<p>In fact, the stock fell.</p>")
        try:
            self.assertEqual(pc.check_fact_gate(s.site), [])
        finally:
            s.close()

    def test_live_site_has_zero_fact_violations(self):
        self.assertEqual(pc.check_fact_gate(REPO / "site"), [])


class Stale(unittest.TestCase):
    def test_cards_and_tickets(self):
        s = Site(traps=[{"id": "old", "updated_at": "2026-09-01"}, {"id": "new", "updated_at": "2026-10-10"},
                        {"id": "exp", "updated_at": "2026-09-01", "expiry": "2026-11-01"}],
                 extra_json={"tickets.json": {"tickets": [{"id": "k", "as_of": "2026-10-01"}, {"id": "k2", "as_of": "2026-10-14"}]}})
        try:
            got = sorted((x["where"], x["label"]) for x in pc.check_stale(s.site, TODAY))
            self.assertEqual(got, [("tickets.json k", "STALE"), ("trap_map.json old", "STALE")])
        finally:
            s.close()


class Wiring(unittest.TestCase):
    def test_warn_only_checks_never_block(self):
        s = Site(cards=[{"id": "b", "d": "Fri Oct 9", "w": "A refinancing is filed."}],
                 traps=[{"id": "old", "updated_at": "2026-09-01"}])
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok, reasons = g.run_publish_guard(s.site, REPO / "pipeline", s.root, baselines={}, today=TODAY)
            self.assertEqual([r for r in reasons if "process" in r or "FACT" in r], [])
            self.assertIn("WARN publish guard process: wrong-if lint", buf.getvalue())
            self.assertIn("WARN publish guard process: ungraded", buf.getvalue())
            self.assertIn("WARN publish guard process: STALE card", buf.getvalue())
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
