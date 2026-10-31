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

    def test_five_rows(self):
        # v9: the HIMS call-spread row is gone; HIMS is only in the Healthcare basket.
        self.assertEqual([r["ticker"] for r in DATA["rows"]], ["ASTS", "FRMI", "TSAT", "MU", "Basket"])
        self.assertFalse({"IREN", "MP", "TSLA", "HIMS"} & {r["ticker"] for r in DATA["rows"]})
        self.assertIn("HIMS", [l["ticker"] for l in rows(DATA)["healthcare-five"]["trade"]["legs"]])

    def test_missing_link(self):
        self.assertFails(lambda d, r: r["asts-q3"]["event"].update(link=""), "missing primary link")
        self.assertFails(lambda d, r: r["mu-cycle"]["event"].update(link="nope.html"), "not found")

    def test_long_reason(self):
        self.assertFails(lambda d, r: r["asts-q3"].update(reason="word " * 21), "over 20 words")

    def test_banned_words(self):
        self.assertFails(lambda d, r: r["frmi-q3"].update(why_we_hold="A bet on cash."), "'bet'")
        self.assertFails(lambda d, r: r["frmi-q3"].update(notes="Trading is thin."), "'thin'")

    def test_past_dated_live_row(self):
        self.assertFails(lambda d, r: r["asts-q3"]["trade"].update(grade_date="2026-10-29"), "past-dated")

    def test_non_stock_ticker(self):
        self.assertFails(lambda d, r: r["asts-q3"].update(ticker="SPY"), "non-stock")
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
                         [("2026-10-29", 769.36, 11231.5), ("2026-09-18", 761.69, 5000.0)])
        self.assertNotIn("hims-q3", DATA["benchmark"]["buys"][0]["rows"])

    def test_direction_matches_trade(self):
        self.assertEqual({r["id"]: r["direction"] for r in DATA["rows"]},
                         {"asts-q3": "Net short", "frmi-q3": "Net short", "tsat-notes": "Net short",
                          "mu-cycle": "Net short", "healthcare-five": "Long"})
        self.assertFails(lambda d, r: r["asts-q3"].update(direction="Net long"), "doesn't match the trade")
        self.assertFails(lambda d, r: r["healthcare-five"].update(direction="Net short"), "doesn't match")
        self.assertFails(lambda d, r: r["mu-cycle"].update(direction="Sideways"), "not one of")
        self.assertFails(lambda d, r: r["frmi-q3"].pop("direction"), "not one of")
        self.assertFails(lambda d, r: r["tsat-notes"]["trade"].pop("expression"), "no expression")
        self.assertFails(lambda d, r: r["asts-q3"]["trade"]["expression"].update(type="Call debit spread"), "expression")
        self.assertFails(lambda d, r: r["asts-q3"].update(lean="Positive"), "lean")
        # a call debit spread reads Net long
        def call(d, r):
            t = r["asts-q3"]["trade"]
            t["legs"] = [{"right": "C", "strike": 43, "qty": 1}, {"right": "C", "strike": 50, "qty": -1}]
            t["text"] = t["text"].replace("put spread", "call spread")
            t["expression"]["type"] = "Call debit spread"
            r["asts-q3"].update(direction="Net long", lean="Positive")
        self.assertEqual(self.errs(call), [])

    def test_healthcare_stop_is_fixed(self):
        t = rows(DATA)["healthcare-five"]["trade"]
        self.assertEqual(t["stop_rule"], {"type": "index_level_or_event", "index_below": 90,
                                          "event": "HIMS Q3 subscribers under 2.891 million", "fixed": True})
        self.assertIn("never moves", t["stop"])
        self.assertGreater(t["index_now"], t["stop_rule"]["index_below"])
        self.assertFails(lambda d, r: d["benchmark"]["buys"][0].pop("source"), "missing source")


class TestBuild(unittest.TestCase):
    def test_outputs_up_to_date(self):
        self.assertEqual(build_trap_map.build(write=False), [], "run python3 pipeline/build_trap_map.py")

    def test_totals_and_changes(self):
        # v9 structure: 5 rows, $16,231.50 allocated. Values/changes move with every Actions
        # price refresh, so they are checked for internal consistency, not pinned to one snapshot.
        T = DATA["totals"]
        self.assertEqual(T["cost"], 16231.5)
        self.assertAlmostEqual(T["change"], round(T["value"] - T["cost"], 2), places=2)
        self.assertTrue(DATA["quotes_as_of"])
        self.assertEqual([r["id"] for r in DATA["rows"]],
                         ["asts-q3", "frmi-q3", "tsat-notes", "mu-cycle", "healthcare-five"])
        self.assertEqual(tc.check_computed(DATA), [])
        self.assertEqual(len(DATA["changes"]), 6)
        self.assertEqual(DATA["changes"][0]["text"][:10], "Every call")

    def test_computed_checks(self):
        d = copy.deepcopy(DATA)
        rows(d)["frmi-q3"]["trade"]["change"] = 1.0
        d["totals"]["value"] = 1.0
        e = tc.check_computed(d)
        self.assertTrue(any("frmi-q3: change" in x for x in e), e)
        self.assertTrue(any("totals.value" in x for x in e), e)

    def test_page(self):
        page = (PIPE.parent / "site" / "trap-map.html").read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>", " ", page)
        self.assertNotRegex(text, r"(?i)\b(bet|thin)\b")
        self.assertEqual(page.count("not advice"), 1)
        self.assertIn("paper trades", page)
        self.assertNotIn("Track record", page)
        self.assertNotIn("What changed", page)
        self.assertNotIn('id="row-hims-q3"', page)
        self.assertIn(f"Quotes as of {build_trap_map._fmt_full(DATA['quotes_as_of'])}", page)
        for rid in ("asts-q3", "frmi-q3", "tsat-notes", "mu-cycle", "healthcare-five"):
            self.assertRegex(page, rf'<tr class="[LS]" id="row-{rid}"')
            self.assertRegex(page, rf'<details class="ev" id="{rid}" data-dir="[LS]"')
        self.assertIn('href="index.html"', page)
        # Old #hims-q3 links land on the Healthcare basket (hidden anchor, no HIMS row).
        self.assertIn('<details class="ev" id="hims-q3" data-moved-to="healthcare-five" hidden></details>', page)
        self.assertIn('"hims-q3": "healthcare-five"', page)
        self.assertIn('href="mu-memory-cycle.html"', page)
        self.assertIn('href="healthcare.html"', page)
        idx = (PIPE.parent / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="trap-map-strip"', idx)
        self.assertEqual(idx.count("TRAP_STRIP:START"), 1)
        strip = idx[idx.index("TRAP_STRIP:START"):idx.index("TRAP_STRIP:END")]
        self.assertNotIn("hims-q3", strip)
        self.assertNotIn("Positive", strip)
        self.assertNotIn("Negative", strip)
        self.assertEqual(strip.count("Net short"), 4)
        T = DATA["totals"]
        self.assertIn("$16,231.50", strip)
        for s in (build_trap_map.money(T["value"]), build_trap_map.money(T["spy_value"]),
                  f"Quotes as of {build_trap_map.fmt_time(DATA['quotes_as_of'])}", ">Long<"):
            self.assertIn(s, strip)


class TestPricePull(unittest.TestCase):
    def test_failure_keeps_last_mid(self):
        d = copy.deepcopy(DATA)
        before = {r["id"]: dict(r["trade"]) for r in d["rows"]}
        with mock.patch.object(fp, "_get", side_effect=OSError("down")), \
             mock.patch.object(fp, "yahoo_quotes", side_effect=OSError("down")):
            warn = fp.pull(d)
        self.assertEqual(len(warn), 6)  # 5 rows + SPY
        for r in d["rows"]:
            for k in ("mid", "value", "mid_time"):
                self.assertEqual(r["trade"].get(k), before[r["id"]].get(k))
            self.assertIsNotNone(r["trade"]["mid_time"])
        self.assertEqual(d["benchmark"]["spy_close_now"], DATA["benchmark"]["spy_close_now"])

    def test_spread_mid_and_grade(self):
        d = copy.deepcopy(DATA)
        r = rows(d)["asts-q3"]
        q = {fp.occ("ASTS", "2026-11-13", "P", 43): (5.0, 5.2), fp.occ("ASTS", "2026-11-13", "P", 37): (2.0, 2.2)}
        from datetime import datetime
        now = datetime(2026, 11, 10, 18, 0, tzinfo=fp.CT)
        with mock.patch.object(fp, "cboe_quotes", return_value=(q, now)), \
             mock.patch.object(fp, "yahoo_close", side_effect=OSError("x")):
            fp.pull({"rows": [r], "benchmark": d["benchmark"]}, now=now)
        self.assertEqual(r["trade"]["mid"], 3.0)
        self.assertEqual(r["trade"]["value"], 2100.0)
        self.assertEqual((r["status"], r["outcome"]), ("graded", "Right"))

    def test_never_places_orders(self):
        src = (PIPE / "fetch_trap_map_prices.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?i)place_?order|/orders|submit_order|broker|POST")


if __name__ == "__main__":
    unittest.main()
