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
        self.assertEqual([r["ticker"] for r in DATA["rows"]], ["ASTS", "FRMI", "TSAT", "MU", "Basket", "CEG"])
        self.assertFalse({"IREN", "MP", "TSLA", "HIMS"} & {r["ticker"] for r in DATA["rows"]})
        self.assertEqual([s["underlying"] for s in rows(DATA)["healthcare-five"]["trade"]["spreads"]], ["HIMS", "TEM", "ABT"])

    def test_missing_link(self):
        self.assertFails(lambda d, r: r["asts-q3"]["event"].update(link=""), "missing primary link")
        self.assertFails(lambda d, r: r["mu-cycle"]["event"].update(link="nope.html"), "not found")

    def test_long_reason(self):
        self.assertFails(lambda d, r: r["asts-q3"].update(reason="word " * 21), "over 20 words")

    def test_banned_words(self):
        self.assertFails(lambda d, r: r["frmi-q3"].update(why_we_hold="A bet on cash."), "'bet'")
        self.assertFails(lambda d, r: r["frmi-q3"].update(notes="Trading is thin."), "'thin'")

    def test_past_dated_live_row(self):
        self.assertFails(lambda d, r: r["asts-q3"]["trade"].update(expiry="2026-10-29") or r["asts-q3"]["trade"]["exit"].update(date="2026-10-29"), "past-dated")

    def test_non_stock_ticker(self):
        self.assertFails(lambda d, r: r["asts-q3"].update(ticker="SPY"), "non-stock")
        self.assertFails(lambda d, r: r["healthcare-five"]["trade"]["spreads"][0].update(underlying="BTC"), "non-stock")

    def test_unconfirmed_date(self):
        self.assertFails(lambda d, r: r["tsat-notes"]["event"].update(date_confirmed=False), "unconfirmed")
        self.assertFails(lambda d, r: r["tsat-notes"]["event"].pop("date_source"), "unconfirmed")

    def test_exit_is_the_expiry(self):
        self.assertFails(lambda d, r: r["tsat-notes"]["trade"]["exit"].update(date="2026-12-08"), "exit must be the option expiry")
        self.assertFails(lambda d, r: r["asts-q3"]["trade"].pop("exit"), "exit must be the option expiry")
        self.assertFails(lambda d, r: r["frmi-q3"]["trade"].pop("expiry"), "without an expiry")
        # a news date passing does not make a row stale; only the expiry does
        self.assertEqual(self.errs(lambda d, r: r["asts-q3"]["event"].update(date="2026-10-01")), [])

    def test_expiry_past_earnings_needs_reason(self):
        self.assertFails(lambda d, r: r["mu-cycle"].pop("earnings_reason"), "earnings_reason")

    def _holding(self, d, r):
        h = r["healthcare-five"]
        h["status"] = "holding"
        h["trade"]["stop"] = "Stop: index below 90."

    def test_holding_needs_fixed_stop(self):
        self.assertEqual(self.errs(self._holding), [])
        self.assertFails(lambda d, r: self._holding(d, r) or r["healthcare-five"]["trade"].pop("stop_rule"), "fixed stop")
        self.assertFails(lambda d, r: self._holding(d, r) or r["healthcare-five"]["trade"]["stop_rule"].update(fixed=False), "fixed stop")

    def test_event_only_stop_ok(self):
        e = self.errs(lambda d, r: self._holding(d, r) or r["healthcare-five"]["trade"]["stop_rule"].pop("index_below"))
        self.assertEqual(e, [])

    def test_no_grading_anywhere(self):
        self.assertFails(lambda d, r: r["asts-q3"]["trade"].update(grade_date="2026-11-10"), "grading field")
        self.assertFails(lambda d, r: d["rules"].update(grade_rule="x"), "grading field")
        self.assertFails(lambda d, r: d.update(how_we_grade="x"), "grading field")
        self.assertFails(lambda d, r: r["mu-cycle"].update(horizon="graded at expiry"), "'graded'")
        self.assertFails(lambda d, r: d["past_calls"].append({"ticker": "TSM", "outcome_text": "x", "exit_reason": "stop",
                                                            "evidence_url": "https://x", "grade": "Right"}), "grading field")
        raw = json.dumps(DATA).lower()
        self.assertNotIn("grade", raw)

    def test_past_call_required_fields(self):
        ok = {"ticker": "TSM", "outcome_text": "Closed at the stop.", "exit_reason": "stop", "evidence_url": "https://finance.yahoo.com/quote/TSM"}
        self.assertEqual(tc.check_past_calls([ok]), [])
        for k in tc.PAST_CALL_FIELDS:
            e = tc.check_past_calls([{**ok, k: ""}])
            self.assertTrue(any("missing " + k.replace("_", " ") in x for x in e), e)
        self.assertTrue(tc.check_past_calls([{**ok, "exit_reason": "Right"}]))
        self.assertTrue(tc.check_past_calls([{**ok, "evidence_url": "past_calls.md"}]))
        self.assertFails(lambda d, r: d["past_calls"].append({**ok, "evidence_url": None}), "missing evidence url")

    def test_benchmark_buys(self):
        # each SPY buy matches the money put into its rows on the same day (no snapshot pinning)
        cost = {r["id"]: r["trade"]["cost"] for r in DATA["rows"]}
        for x in DATA["benchmark"]["buys"]:
            self.assertAlmostEqual(x["dollars"], sum(cost[i] for i in x["rows"]), places=2)
            self.assertAlmostEqual(x["shares"], x["dollars"] / x["price"], places=3)
        self.assertNotIn("hims-q3", DATA["benchmark"]["buys"][0]["rows"])

    def test_direction_matches_trade(self):
        self.assertEqual({r["id"]: r["direction"] for r in DATA["rows"]},
                         {"asts-q3": "Net short", "frmi-q3": "Net short", "tsat-notes": "Net short",
                          "mu-cycle": "Net short", "healthcare-five": "Net long", "ceg-q3": "Net long"})
        self.assertFails(lambda d, r: r["asts-q3"].update(direction="Net long"), "doesn't match the trade")
        self.assertFails(lambda d, r: r["healthcare-five"].update(direction="Long"), "doesn't match")
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
        sr = t["stop_rule"]
        self.assertEqual((sr["index_below"], sr["fixed"], sr["weights"]), (90, True, "equal"))
        self.assertEqual([(l["ticker"], l["base"]) for l in sr["index_legs"]], [("HIMS", 27.68), ("TEM", 72.22), ("ABT", 106.2)])
        self.assertEqual(t["cost"], 2965.0)
        self.assertEqual(fp.equal_weight_index([(27.68, 27.68), (72.22, 72.22), (106.2, 106.2)]), 100.0)
        # equal weight: each name is one third of its own move
        self.assertEqual(fp.equal_weight_index([(27.68, 27.68 * 0.7), (72.22, 72.22), (106.2, 106.2)]), 90.0)
        self.assertFails(lambda d, r: d["benchmark"]["buys"][0].pop("source"), "missing source")


class TestBuild(unittest.TestCase):
    def test_outputs_up_to_date(self):
        self.assertEqual(build_trap_map.build(write=False), [], "run python3 pipeline/build_trap_map.py")

    def test_totals_and_changes(self):
        # v9 structure: 5 rows, $16,231.50 allocated. Values/changes move with every Actions
        # price refresh, so they are checked for internal consistency, not pinned to one snapshot.
        T = DATA["totals"]
        self.assertAlmostEqual(T["cost"], sum(r["trade"]["cost"] for r in DATA["rows"] if r["status"] != "closed"), places=2)
        self.assertAlmostEqual(T["change"], round(T["value"] - T["cost"], 2), places=2)
        self.assertTrue(DATA["quotes_as_of"])
        self.assertEqual([r["id"] for r in DATA["rows"]],
                         ["asts-q3", "frmi-q3", "tsat-notes", "mu-cycle", "healthcare-five", "ceg-q3"])
        self.assertEqual(tc.check_computed(DATA), [])
        self.assertTrue(any(c["text"].startswith("Exits are now only") for c in DATA["changes"]))

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
        self.assertNotRegex(text, r"(?i)grad(e|ed|es|ing)\b")
        self.assertEqual(page.count("not advice"), 1)
        self.assertIn("paper trades", page)
        self.assertNotIn("Track record", page)
        self.assertNotIn("What changed", page)
        self.assertNotIn('id="row-hims-q3"', page)
        self.assertIn(f"Quotes as of {build_trap_map._fmt_full(DATA['quotes_as_of'])}", page)
        for rid in ("asts-q3", "frmi-q3", "tsat-notes", "mu-cycle", "healthcare-five", "ceg-q3"):
            self.assertRegex(page, rf'<tr class="[LS]" id="row-{rid}"')
            self.assertRegex(page, rf'<details class="ev" id="{rid}" data-dir="[LS]"')
        self.assertIn('href="index.html"', page)
        # Old #hims-q3 links land on the Healthcare basket (hidden anchor, no HIMS row).
        self.assertIn('<details class="ev" id="hims-q3" data-moved-to="healthcare-five" hidden></details>', page)
        self.assertIn('"hims-q3": "healthcare-five"', page)
        self.assertIn('href="mu-memory-cycle.html"', page)
        self.assertIn("healthcare.html", page)
        self.assertIn("Nov 13 expiry", page)
        idx = (PIPE.parent / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="trap-map-strip"', idx)
        self.assertEqual(idx.count("TRAP_STRIP:START"), 1)
        strip = idx[idx.index("TRAP_STRIP:START"):idx.index("TRAP_STRIP:END")]
        self.assertNotIn("hims-q3", strip)
        self.assertNotIn("Positive", strip)
        self.assertNotIn("Negative", strip)
        self.assertEqual(strip.count("Net short"), 4)
        T = DATA["totals"]
        self.assertNotRegex(strip, r"(?i)grade")
        self.assertIn("Held to Nov 13 expiry", strip)
        for s in (build_trap_map.money(T["cost"]), build_trap_map.money(T["value"]), build_trap_map.money(T["spy_value"]),
                  f"Quotes as of {build_trap_map.fmt_time(DATA['quotes_as_of'])}", ">Net long<"):
            self.assertIn(s, strip)


class TestPricePull(unittest.TestCase):
    def test_failure_keeps_last_mid(self):
        d = copy.deepcopy(DATA)
        before = {r["id"]: dict(r["trade"]) for r in d["rows"]}
        with mock.patch.object(fp, "_get", side_effect=OSError("down")), \
             mock.patch.object(fp, "yahoo_quotes", side_effect=OSError("down")):
            warn = fp.pull(d)
        self.assertEqual(len(warn), len(d["rows"]) + 1)  # each row + SPY
        for r in d["rows"]:
            for k in ("mid", "mark", "value", "mid_time"):
                self.assertEqual(r["trade"].get(k), before[r["id"]].get(k))
            self.assertIsNotNone(r["trade"]["mid_time"])
        self.assertEqual(d["benchmark"]["spy_close_now"], DATA["benchmark"]["spy_close_now"])

    def _pull(self, quotes, now, rid="asts-q3"):
        d = copy.deepcopy(DATA)
        r = rows(d)[rid]
        with mock.patch.object(fp, "cboe_quotes", return_value=(quotes, now)), \
             mock.patch.object(fp, "yahoo_quotes", side_effect=OSError("x")), \
             mock.patch.object(fp, "yahoo_close", side_effect=OSError("x")):
            warn = fp.pull({"rows": [r], "benchmark": d["benchmark"]}, now=now)
        return r, warn

    def _asts(self, long_q, short_q):
        return {fp.occ("ASTS", "2026-11-13", "P", 43): fp._q(*long_q),
                fp.occ("ASTS", "2026-11-13", "P", 37): fp._q(*short_q)}

    def test_bottom_third_rule(self):
        self.assertAlmostEqual(fp.bottom_third(3.0, 3.6), 3.2)
        self.assertAlmostEqual(fp.bottom_third(1.0, 1.0), 1.0)

    def test_spread_marked_at_bottom_third(self):
        from datetime import datetime
        now = datetime(2026, 11, 2, 10, 0, tzinfo=fp.CT)
        r, warn = self._pull(self._asts((5.0, 5.3, 10, 100, now), (2.0, 2.3, 10, 100, now)), now)
        self.assertEqual([w for w in warn if not w.startswith("SPY")], [])
        self.assertAlmostEqual(r["trade"]["mark"], (5.0 + 0.1) - (2.0 + 0.1))
        self.assertEqual(r["trade"]["value"], 2100.0)
        self.assertNotIn("mid", r["trade"])
        self.assertNotIn("quote_flags", r["trade"])
        self.assertEqual(r["status"], "live")  # priced only; no grading
        self.assertEqual(r["trade"]["priced"], "bottom_third")

    def test_unrealistic_quotes_keep_last_good_price(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 11, 2, 10, 0, tzinfo=fp.CT)
        good = (2.0, 2.3, 10, 100, now)
        cases = {
            "no bid": ((0, 5.3, 10, 100, now), good),
            "zero volume and zero open interest": ((5.0, 5.3, 0, 0, now), good),
            "stale": ((5.0, 5.3, 10, 100, now - timedelta(days=5)), good),
            "wider than 50% of mid": ((5.0, 5.3, 10, 100, now), (20.0, 40.0, 10, 2, now)),  # like TSAT's $40 leg
        }
        for want, (lq, sq) in cases.items():
            before = dict(rows(DATA)["asts-q3"]["trade"])
            r, warn = self._pull(self._asts(lq, sq), now)
            self.assertTrue(any(want in f for f in r["trade"]["quote_flags"]), (want, r["trade"].get("quote_flags")))
            for k in ("mid", "value", "mid_time"):
                self.assertEqual(r["trade"].get(k), before.get(k), want)
            self.assertTrue(warn)

    def test_exit_at_expiry_and_stop(self):
        from datetime import datetime
        now = datetime(2026, 11, 13, 16, 0, tzinfo=fp.CT)
        r, _ = self._pull(self._asts((5.0, 5.3, 10, 100, now), (2.0, 2.3, 10, 100, now)), now)
        self.assertEqual(r["status"], "closed")
        self.assertEqual(r["exit"], {"reason": "expiry", "date": "2026-11-13", "value": 2100.0, "result": round(2100.0 - r["trade"]["cost"], 2)})
        self.assertNotIn("outcome", r)
        self.assertNotRegex(json.dumps(r["exit"]), r"(?i)grade|right|wrong")
        # basket-style index stop closes the whole row
        d = copy.deepcopy(DATA)
        h = rows(d)["healthcare-five"]
        h["trade"]["index_now"] = 89.0
        fp.close_row(h, "stop", now) if h["trade"]["index_now"] < 90 else None
        self.assertEqual((h["status"], h["exit"]["reason"]), ("closed", "stop"))

    def test_no_grading_in_fetcher(self):
        src = (PIPE / "fetch_trap_map_prices.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"def _grade|\"graded\"|outcome")


    def test_never_places_orders(self):
        src = (PIPE / "fetch_trap_map_prices.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?i)place_?order|/orders|submit_order|broker|POST")


if __name__ == "__main__":
    unittest.main()


class TestMidpointLabel(unittest.TestCase):
    def setUp(self):
        self.d = build_trap_map.compute(copy.deepcopy(DATA))

    def test_midpoint_totals_labeled(self):
        self.assertTrue(self.d["totals"]["midpoint_rows"])
        note = build_trap_map.midpoint_note(self.d)
        self.assertRegex(note, r"^Midpoint marks as of [A-Z][a-z]{2} \d+; bid \+ 1/3 repricing Monday")
        self.assertIn(note, build_trap_map.render_page(self.d))
        strip = build_trap_map.render_strip(self.d)
        self.assertIn(note, strip)
        self.assertIn("at midpoint, not final", strip)
        page = build_trap_map.render_page(self.d)
        self.assertNotIn("(bottom third of bid", page)
        n_mid = len(self.d["totals"]["midpoint_rows"])
        self.assertEqual(page.count("Midpoint, not final (bid + 1/3"), 2 * n_mid)  # desktop row + phone card

    def test_label_goes_away_after_bottom_third_pull(self):
        for r in self.d["rows"]:
            (r.get("trade") or {})["priced"] = "bottom_third"
        self.assertEqual(build_trap_map.midpoint_note(self.d), "")
        self.assertNotIn("midpoint-note", build_trap_map.render_page(self.d))
