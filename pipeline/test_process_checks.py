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
# Never read the real box tickets file (/workspace/cos/tickets.json) from tests.
pc.TICKETS_BOX_PATH = Path(tempfile.mkdtemp()) / "no_box_tickets.json"

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
            # nothing carries a publish date >= 2026-10-19: all backlog, scope N/A
            self.assertEqual((r["lines"], r["pct_compliant"]), (0, None))
            self.assertEqual((r["backlog"]["lines"], r["backlog"]["failures"], r["backlog"]["pct_compliant"]), (4, 2, 50.0))
            self.assertEqual(r["backlog"]["by_surface"]["data.js"]["failures"], 1)
        finally:
            s.close()

    def test_scope_counts_only_new_items(self):
        page = ('<details class="ev" id="n" data-published="2026-10-19"><summary></summary><dl>'
                '<dt>What would prove us wrong</dt><dd>A refinancing is filed.</dd></dl></details>')
        s = Site(html_extra=page,
                 traps=[{"id": "old", "updated_at": "2026-10-01", "drop_if": "vibes"},
                        {"id": "new", "updated_at": "2026-10-20", "drop_if": "PJM BRA under $100/MW-day by Dec 2026"}],
                 data={"deepDives": {"1": {"created_at": "2026-10-19T05:00:00", "falsification_tracks": ["Share falls."]},
                                     "2": {"created_at": "2026-10-10T05:00:00", "falsification_tracks": ["x"]}}})
        try:
            r = pc.check_wrong_if(s.site)
            self.assertEqual((r["lines"], r["failures"], r["pct_compliant"]), (3, 2, 33.3))
            self.assertEqual(r["backlog"]["lines"], 2)
            b, w, rep = pc.run_process_checks(s.site, TODAY, emit=lambda *_: None)
            self.assertTrue(any("in-scope lines" in x for x in w))
            self.assertTrue(any("backlog (info only)" in x for x in rep["info"]))
        finally:
            s.close()

    def test_backlog_only_is_info_not_warning(self):
        s = Site(traps=[{"id": "old", "updated_at": "2026-10-01", "drop_if": "vibes"}])
        try:
            b, w, rep = pc.run_process_checks(s.site, TODAY, emit=lambda *_: None)
            self.assertFalse(any("wrong-if" in x for x in w))
            self.assertTrue(any("(N/A)" in x for x in rep["info"]))
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
    def setUp(self):
        self._box = pc.TICKETS_BOX_PATH
        pc.TICKETS_BOX_PATH = Path(tempfile.mkdtemp()) / "missing_tickets.json"

    def tearDown(self):
        pc.TICKETS_BOX_PATH = self._box

    def test_cards_and_tickets(self):
        tickets = {"tickets": [
            {"id": "k", "created": "2026-10-01"},                                        # no exit fields, 15d -> STALE
            {"id": "k2", "created": "2026-10-14"},                                       # young
            {"id": "k3", "created": "2026-10-10", "exit": "close < $5", "exit_date": "2026-10-20", "expiry": "2026-10-15"},  # expired
            {"id": "k4", "created": "2026-10-10", "exit": "x", "exit_date": "2026-10-20", "expiry": "2026-10-17"},  # fine
            {"id": "k5", "created": "2026-09-01", "status": "CLOSED"}]}                  # closed: skipped
        s = Site(traps=[{"id": "old", "updated_at": "2026-09-01"}, {"id": "new", "updated_at": "2026-10-10"},
                        {"id": "exp", "updated_at": "2026-09-01", "exit": "x", "exit_date": "2026-11-01", "expiry": "2026-11-01"}],
                 extra_json={"tickets.json": tickets})
        try:
            got = sorted((x["where"], x["label"]) for x in pc.check_stale(s.site, TODAY))
            self.assertEqual(got, [("tickets.json k", "STALE"), ("tickets.json k3", "STALE"), ("trap_map.json old", "STALE")])
        finally:
            s.close()

    def test_bare_list_and_env_path(self):
        p = Path(tempfile.mkdtemp()) / "jg.json"
        p.write_text(json.dumps([{"ticker": "BE", "as_of": "2026-10-01"}]))
        s = Site()
        try:
            import os
            os.environ["TICKETS_JSON"] = str(p)
            got = [x["where"] for x in pc.check_stale(s.site, TODAY)]
            self.assertEqual(got, ["jg.json BE"])
        finally:
            os.environ.pop("TICKETS_JSON", None)
            s.close()

    def test_missing_tickets_is_silent_info(self):
        s = Site()
        try:
            b, w, rep = pc.run_process_checks(s.site, TODAY, emit=lambda *_: None)
            self.assertEqual(b, [])
            self.assertFalse(any("ticket" in x for x in w))
            self.assertTrue(any("tickets.json not found" in x for x in rep["info"]))
        finally:
            s.close()

    def test_portfolio_positions(self):
        pf = {"baskets": [{"id": "b", "as_of": "2026-09-18T09:30:00-05:00", "names": [
            {"ticker": "A", "exit": None, "exit_date": None, "expiry": None},
            {"ticker": "B", "exit": "close < $10", "exit_date": "2026-11-01", "expiry": "2026-11-01"},
            {"ticker": "C", "exit": "x", "exit_date": "2026-10-10", "expiry": "2026-10-09"}]}]}
        s = Site(extra_json={"portfolio.json": pf})
        try:
            got = sorted(x["where"] for x in pc.check_stale(s.site, TODAY))
            self.assertEqual(got, ["portfolio.json b/A", "portfolio.json b/C"])
        finally:
            s.close()

    def test_shipped_portfolio_has_exit_fields(self):
        pf = json.loads((REPO / "site" / "data" / "portfolio.json").read_text())
        for b in pf["baskets"]:
            for n in b["names"]:
                for k in ("exit", "exit_date", "expiry"):
                    self.assertIn(k, n)

    def test_price_update_keeps_exit_fields(self):
        import fetch_portfolio_prices as fpp
        from unittest import mock
        d = Path(tempfile.mkdtemp()) / "portfolio.json"
        d.write_text(json.dumps({"_metadata": {}, "baskets": [{"names": [
            {"ticker": "A", "shares": 1, "inception_price": 10, "exit": "close < $8", "exit_date": "2026-11-01", "expiry": None},
            {"ticker": "B", "shares": 1, "inception_price": 10}]}]}))
        with mock.patch.object(fpp, "PORTFOLIO_FILE", d), mock.patch.object(fpp, "fetch_yahoo_price", return_value=11.0), \
                redirect_stdout(io.StringIO()):
            fpp.update_portfolio()
        names = json.loads(d.read_text())["baskets"][0]["names"]
        self.assertEqual(names[0]["exit"], "close < $8")
        self.assertEqual({k: names[1][k] for k in ("exit", "exit_date", "expiry")}, {"exit": None, "exit_date": None, "expiry": None})


class Wiring(unittest.TestCase):
    def test_warn_only_checks_never_block(self):
        s = Site(cards=[{"id": "b", "d": "Fri Oct 9", "w": "A refinancing is filed."}],
                 traps=[{"id": "old", "updated_at": "2026-09-01"}])
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok, reasons = g.run_publish_guard(s.site, REPO / "pipeline", s.root, baselines={}, today=TODAY)
            self.assertEqual([r for r in reasons if "process" in r or "FACT" in r], [])
            self.assertIn("INFO publish guard process: wrong-if lint scope", buf.getvalue())
            self.assertIn("WARN publish guard process: ungraded", buf.getvalue())
            self.assertIn("WARN publish guard process: STALE card", buf.getvalue())
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
