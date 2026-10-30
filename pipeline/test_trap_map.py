"""Trap Map v5: validator rules, build is up to date, price pull keeps last mid on failure."""
import copy
import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

PIPE = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPE))
import build_trap_map  # noqa: E402
import fetch_trap_map_prices as fp  # noqa: E402
import trap_map_check as tc  # noqa: E402

DATA = json.loads((PIPE.parent / "site" / "data" / "trap_map.json").read_text(encoding="utf-8"))
TODAY = date(2026, 10, 30)


def rows(d):
    return {r["id"]: r for r in d["rows"]}


class TestValidator(unittest.TestCase):
    def errs(self, mutate):
        d = copy.deepcopy(DATA)
        mutate(d, rows(d))
        return tc.check(d, today=TODAY)

    def assertFails(self, mutate, pat):
        e = self.errs(mutate)
        self.assertTrue(any(re.search(pat, x) for x in e), e)

    def test_repo_data_passes(self):
        self.assertEqual(tc.check(DATA, today=TODAY), [])

    def test_six_rows(self):
        self.assertEqual([r["ticker"] for r in DATA["rows"]], ["HIMS", "ASTS", "FRMI", "TSAT", "MU", "Basket"])
        self.assertFalse({"IREN", "MP", "TSLA"} & {r["ticker"] for r in DATA["rows"]})

    def test_missing_link(self):
        self.assertFails(lambda d, r: r["hims-q3"]["event"].update(link=""), "missing primary link")
        self.assertFails(lambda d, r: r["mu-cycle"]["event"].update(link="nope.html"), "not found")

    def test_long_reason(self):
        self.assertFails(lambda d, r: r["asts-q3"].update(reason="word " * 21), "over 20 words")

    def test_banned_words(self):
        self.assertFails(lambda d, r: r["frmi-q3"].update(why_we_hold="A bet on cash."), "'bet'")
        self.assertFails(lambda d, r: r["frmi-q3"].update(notes="Trading is thin."), "'thin'")

    def test_past_dated_live_row(self):
        self.assertFails(lambda d, r: r["hims-q3"]["trade"].update(grade_date="2026-10-29"), "past-dated")

    def test_non_stock_ticker(self):
        self.assertFails(lambda d, r: r["hims-q3"].update(ticker="SPY"), "non-stock")
        self.assertFails(lambda d, r: r["healthcare-five"]["trade"]["legs"][0].update(ticker="BTC"), "non-stock")

    def test_unconfirmed_date(self):
        self.assertFails(lambda d, r: r["tsat-notes"]["event"].update(date_confirmed=False), "unconfirmed")
        self.assertFails(lambda d, r: r["tsat-notes"]["event"].pop("date_source"), "unconfirmed")

    def test_grade_after_expiry(self):
        self.assertFails(lambda d, r: r["tsat-notes"]["trade"].update(grade_date="2026-12-21"), "after expiry")

    def test_expiry_past_earnings_needs_reason(self):
        self.assertFails(lambda d, r: r["mu-cycle"].pop("earnings_reason"), "earnings_reason")

    def test_holding_needs_fixed_stop(self):
        self.assertFails(lambda d, r: r["healthcare-five"]["trade"].pop("stop_rule"), "fixed stop")
        self.assertFails(lambda d, r: r["healthcare-five"]["trade"]["stop_rule"].update(fixed=False), "fixed stop")

    def test_event_only_stop_ok(self):
        e = self.errs(lambda d, r: r["healthcare-five"]["trade"]["stop_rule"].pop("index_below"))
        self.assertEqual(e, [])

    def test_grade_date_required_unless_holding(self):
        self.assertFails(lambda d, r: r["asts-q3"]["trade"].pop("grade_date"), "missing grade date")
        self.assertEqual(self.errs(lambda d, r: None), [])  # Holding row has none and passes

    def test_benchmark_buys(self):
        b = DATA["benchmark"]["buys"]
        self.assertEqual([(x["date"], x["price"], x["dollars"]) for x in b],
                         [("2026-10-29", 769.36, 12686.5), ("2026-09-18", 761.69, 5000.0)])
        self.assertFails(lambda d, r: d["benchmark"]["buys"][0].pop("source"), "missing source")


class TestBuild(unittest.TestCase):
    def test_outputs_up_to_date(self):
        self.assertEqual(build_trap_map.build(write=False), [], "run python3 pipeline/build_trap_map.py")

    def test_totals_and_changes(self):
        self.assertEqual((DATA["totals"]["cost"], DATA["totals"]["value"], DATA["totals"]["spy_value"]),
                         (17686.5, 17852.4, 17736.85))
        self.assertEqual(len(DATA["changes"]), 6)
        self.assertEqual(DATA["changes"][0]["text"][:10], "Every call")

    def test_page(self):
        page = (PIPE.parent / "site" / "trap-map.html").read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>", " ", page)
        self.assertNotRegex(text, r"(?i)\b(bet|thin)\b")
        self.assertEqual(page.count("not advice"), 1)
        self.assertIn("paper trades", page)
        self.assertNotIn("Track record", page)
        for rid in ("hims-q3", "asts-q3", "frmi-q3", "tsat-notes", "mu-cycle", "healthcare-five"):
            self.assertIn(f'<details class="ev" id="{rid}"', page)
        self.assertIn('href="mu-memory-cycle.html"', page)
        self.assertIn('href="healthcare.html"', page)
        idx = (PIPE.parent / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="trap-map-strip"', idx)
        self.assertEqual(idx.count("TRAP_STRIP:START"), 1)


class TestPricePull(unittest.TestCase):
    def test_failure_keeps_last_mid(self):
        d = copy.deepcopy(DATA)
        before = {r["id"]: dict(r["trade"]) for r in d["rows"]}
        with mock.patch.object(fp, "_get", side_effect=OSError("down")), \
             mock.patch.object(fp, "yahoo_quotes", side_effect=OSError("down")):
            warn = fp.pull(d)
        self.assertEqual(len(warn), 7)
        for r in d["rows"]:
            for k in ("mid", "value", "mid_time"):
                self.assertEqual(r["trade"].get(k), before[r["id"]].get(k))
            self.assertIsNotNone(r["trade"]["mid_time"])
        self.assertEqual(d["benchmark"]["spy_close_now"], DATA["benchmark"]["spy_close_now"])

    def test_spread_mid_and_grade(self):
        d = copy.deepcopy(DATA)
        r = rows(d)["hims-q3"]
        q = {fp.occ("HIMS", "2026-11-13", "C", 30): (3.0, 3.2), fp.occ("HIMS", "2026-11-13", "C", 35): (1.0, 1.2)}
        from datetime import datetime
        now = datetime(2026, 11, 10, 18, 0, tzinfo=fp.CT)
        with mock.patch.object(fp, "cboe_quotes", return_value=(q, now)), \
             mock.patch.object(fp, "yahoo_close", side_effect=OSError("x")):
            fp.pull({"rows": [r], "benchmark": d["benchmark"]}, now=now)
        self.assertEqual(r["trade"]["mid"], 2.0)
        self.assertEqual(r["trade"]["value"], 2000.0)
        self.assertEqual((r["status"], r["outcome"]), ("graded", "Right"))

    def test_never_places_orders(self):
        src = (PIPE / "fetch_trap_map_prices.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?i)place_?order|/orders|submit_order|broker|POST")


if __name__ == "__main__":
    unittest.main()
