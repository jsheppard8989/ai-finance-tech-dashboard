"""Tests for export_leaderboard.py (bot game leaderboard, Oct 16 2026)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import export_leaderboard as el
from site_text_sanitize import find_style_gate_hits

REPO = Path(__file__).resolve().parent.parent

MD = """# Weekly Bot Paper Game: Scoreboard

Week 1 runs Wed Oct 14 2026 to Tue Oct 20 2026. Dragonfly Watcher keeps score.

## Standings

| Player | Ticker | Side | $ in | Fill | Last mark | Value $ | Flags |
|---|---|---|---|---|---|---|---|
| Alpha | AAA | long | 1,000 | 10, IEX, proof/2026-10-16/a.json | 11 | 1,100.00 | |
| Compound Wealth | BBB | long | 1,000 | 5 | 4 | 800.00 | |
| Ghost | — | — | — | — | — | — | |

## Trades log (round trips, one per day max)

| Received (CT) | Player | Action | Ticker | Fill | Source | Proof path |
|---|---|---|---|---|---|---|
| 2026-10-16 09:00:00 | Alpha | Exit (close long, stop) | ZZZ | 9.5 (09:01 bar) | IEX | proof/2026-10-16/x.json |
| 2026-10-16 10:00:00 | Ditka89 | Re-entry long $800 | BBB | 5.00 (10:01 bar) | IEX | proof/2026-10-16/y.json |
| 2026-10-15 10:00:00 | Alpha | Entry long $1,000 | AAA | 10 | IEX | p |

## Fines

| Day | Player | Fine | Value after |
|---|---|---|---|
| 2026-10-16 | Compound Wealth | $250 | 800 |
"""
MARKS = {"date": "2026-10-16", "captured_ct": "2026-10-16T15:14:00-05:00",
         "source": "yfinance close; file /workspace/cos/bot_game/proof/x.json",
         "positions": [
             {"player": "Alpha", "ticker": "AAA", "side": "long", "entry": 10, "close": 11, "value": 1100.0, "day_pl": 5,
              "note": "big bet paid; see proof/2026-10-16/a.json and Dragonfly book"},
             {"player": "Compound Wealth", "ticker": "FLAT", "side": "cash", "entry": None, "close": None, "value": 800.0, "day_pl": -1}]}


class Export(unittest.TestCase):
    def setUp(self):
        self.src = Path(tempfile.mkdtemp())
        (self.src / "scoreboard.md").write_text(MD, encoding="utf-8")
        (self.src / "proof" / "2026-10-16").mkdir(parents=True)
        (self.src / "proof" / "2026-10-16" / "daily_close_marks_2026-10-16.json").write_text(json.dumps(MARKS))
        (self.src / "reasons").mkdir()
        (self.src / "reasons" / "2026-10-15_Alpha_AAA_entry.md").write_text(
            "# Alpha AAA long\n(Rebuilt from his state file at /workspace/cos/x.json.)\n"
            "- Why: A lean on demand. Dragonfly book says more. Extra sentence here.\n"
            "- Stop: 9.50. Target: 12.00. Must be out by Tue 10/20.\n- Wrong if: it closes below 9.50.\n"
            "- Source: Alpha message.\n", encoding="utf-8")
        (self.src / "reasons" / "2026-10-16_Ditka89_BBB_entry.md").write_text(
            "# Ditka89 BBB\n- Why: Fallback so the slot isn't flat.\n- Stop / exit: exit on a 3% drop.\n", encoding="utf-8")
        self.out = el.build(self.src)

    def tearDown(self):
        shutil.rmtree(self.src, ignore_errors=True)

    def test_rank_balance_pnl(self):
        b = self.out["bots"]
        self.assertEqual([x["bot"] for x in b[:2]], ["Alpha", "Ditka89"])
        self.assertEqual(b[0]["rank"], 1)
        self.assertEqual(b[0]["pnl_usd"], 100.0)
        self.assertEqual(b[0]["pnl_pct"], 10.0)
        self.assertEqual(b[1]["position"]["side"], "flat")

    def test_missing_is_null_with_reason(self):
        ghost = [x for x in self.out["bots"] if x["bot"] == "Ghost"][0]
        self.assertIsNone(ghost["balance_usd"])
        self.assertIsNone(ghost["rank"])
        self.assertIn("balance_reason", ghost)
        self.assertIn("position_reason", ghost)

    def test_today_trades_alias_and_reason(self):
        a = [x for x in self.out["bots"] if x["bot"] == "Alpha"][0]
        self.assertEqual(len(a["today_trades"]), 1)  # Oct 15 entry excluded
        self.assertIsNone(a["today_trades"][0]["reason"])  # no reason file -> not filed, no generic text
        self.assertFalse(a["today_trades"][0]["reason_filed"])
        self.assertTrue(a["today_trades"][0]["reason_missing"])
        cw = [x for x in self.out["bots"] if x["bot"] == "Ditka89"][0]
        self.assertEqual(cw["today_trades"][0]["ticker"], "BBB")  # group chat name Compound Wealth -> Ditka89
        self.assertEqual(cw["fines_usd"], 250.0)

    def test_public_text_clean(self):
        blob = json.dumps(self.out)
        for bad in ("/workspace", "proof/", ".json", "Dragonfly", "Compound Wealth"):
            self.assertNotIn(bad, blob)
        self.assertEqual(find_style_gate_hits(self.out), [])
        self.assertNotRegex(blob.lower(), r"\bbets?\b")
        self.assertEqual(self.out["as_of"], "2026-10-16")

    def test_reasons_from_channel(self):
        a = [x for x in self.out["bots"] if x["bot"] == "Alpha"][0]
        r = a["position"]["reason"]
        self.assertTrue(r["why"].startswith("A lean on demand."))
        self.assertEqual(r["stop"], "9.50.")
        self.assertIn("10/20", r["target"])
        self.assertEqual(r["wrong_if"], "it closes below 9.50.")
        cw = [x for x in self.out["bots"] if x["bot"] == "Ditka89"][0]
        self.assertEqual(cw["today_trades"][0]["reason"], "Fallback so the slot isn't flat.")
        self.assertEqual(cw["today_trades"][0]["stop"], "exit on a 3% drop.")

    def test_reason_missing_is_null_with_reason(self):
        shutil.rmtree(self.src / "reasons")
        out2 = el.build(self.src)
        a = [x for x in out2["bots"] if x["bot"] == "Alpha"][0]
        self.assertIsNone(a["position"]["reason"])
        self.assertTrue(a["position"]["reason_missing"])

    def test_no_marks_as_of_null_with_reason(self):
        src = Path(tempfile.mkdtemp())
        try:
            out = el.build(src)
            self.assertIsNone(out["as_of"])
            self.assertTrue(out["as_of_reason"])
        finally:
            shutil.rmtree(src, ignore_errors=True)


class Site(unittest.TestCase):
    def test_nav_links_every_page(self):
        for p in (REPO / "site").glob("*.html"):
            if p.name == "leaderboard.html":
                continue
            self.assertIn('href="leaderboard.html"', p.read_text(encoding="utf-8"), p.name)

    def test_published_leaderboard_json_clean(self):
        p = REPO / "site" / "data" / "leaderboard.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue(d["bots"])
        self.assertEqual(find_style_gate_hits(d), [])
        blob = json.dumps(d)
        for bad in ("/workspace", "proof/", "Dragonfly"):
            self.assertNotIn(bad, blob)


if __name__ == "__main__":
    unittest.main()


class Wording(unittest.TestCase):
    CASES = [
        ("Jared's approved SATA fallback. He was flat.", "The game's fallback rule. He was flat."),
        ("Jared's fallback so the slot isn't flat", "The game's fallback rule so the slot isn't flat"),
        ("so he used Jared's SATA fallback. SATA pays", "so he used the game's fallback rule. SATA pays"),
        ("voided by Jared\u2019s 9:16 PM CT rule", "voided by the game's 9:16 PM CT rule"),
        ("The Department of War guarantees a floor", "The Department of War (Defense) guarantees a floor"),
        ("The Department of War (Defense) guarantees", "The Department of War (Defense) guarantees"),
    ]

    def test_cases(self):
        for src, want in self.CASES:
            self.assertEqual(el.clean(src), want)

    def test_idempotent_and_no_jared(self):
        for src, _ in self.CASES:
            once = el.clean(src)
            self.assertEqual(el.clean(once), once)
            self.assertNotIn("Jared", once)

    def test_real_source_export_has_no_jared(self):
        if not Path(el.DEFAULT_SOURCE).is_dir():
            self.skipTest("bot game source not on this machine")
        out = el.build(Path(el.DEFAULT_SOURCE))
        blob = json.dumps(out, ensure_ascii=False)
        self.assertNotRegex(blob, r"(?i)\bjared\b")
        self.assertNotRegex(blob, r"Department of War(?!\s*\(Defense\))")


class V2Fields(unittest.TestCase):
    """history, trades, closed_positions, open P&L, fees, timed reasons, week archive (Oct 16 v2)."""

    def setUp(self):
        self.src = Path(tempfile.mkdtemp())
        md = """# Scoreboard

Week 2 runs Wed Oct 21 2026 to Tue Oct 27 2026. Watcher keeps score.

## Standings

| Player | Ticker | Side | $ in | Fill | Last mark | Value $ | Flags |
|---|---|---|---|---|---|---|---|
| Ditka89 | CIFR | long | 1,000 | x | x | 850 | |
| Shorty | ZZ | short | 1,000 | x | x | 1,100 | |

## Trades log

| Received (CT) | Player | Action | Ticker | Fill | Source | Proof path |
|---|---|---|---|---|---|---|
| 2026-10-21 09:47:18 | Compound Wealth | Entry long $1,000 | CIFR | 10.65 (09:48 bar) | IEX | proof/2026-10-21/c_entry.json |
| 2026-10-22 08:39:29 | Ditka89 | Exit (close long) | CIFR | 9.065 | IEX | proof/2026-10-22/c_exit.json |
| 2026-10-22 10:00:00 | Ditka89 | Re-entry long $849.82 | CIFR | 9.10 | IEX | proof/2026-10-22/c2.json |
| 2026-10-22 11:00:00 | Ditka89 | Exit (close long) | CIFR | 9.20 | IEX | proof/2026-10-22/c3.json |
| 2026-10-22 12:00:00 | Ditka89 | Re-entry long $850 | CIFR | 9.30 | IEX | missing.json |
| 2026-10-21 09:00:00 | Shorty | Entry short $1,000 | ZZ | 20.875 | IEX | proof/2026-10-21/z.json |
| 2026-10-14 09:00:00 | Shorty | Entry long $1,000 | OLD | 5 | IEX | p |
"""
        (self.src / "scoreboard.md").write_text(md, encoding="utf-8")
        P = self.src / "proof"
        for d in ("2026-10-14", "2026-10-21", "2026-10-22"):
            (P / d).mkdir(parents=True)
        (P / "2026-10-21" / "c_entry.json").write_text(json.dumps({"fill_price": 10.65, "notional_usd": 1000.0, "fee_usd": 0.5, "fee_rate": 0.0005, "bar_start_ct": "2026-10-21T09:48:00-05:00"}))
        # Stored on the $1,000 basis (the CIFR 10/15 error): must be recomputed to 0.85.
        (P / "2026-10-22" / "c_exit.json").write_text(json.dumps({"fill_price": 9.065, "notional_usd": 1000.0, "fee_usd": 1.0, "fee_rate": 0.001}))
        (P / "2026-10-21" / "z.json").write_text(json.dumps({"fill_price": 20.875, "notional_usd": 1000.0, "fee_usd": 0.0}))
        for d, vals in (("2026-10-14", {"Ditka89": 1.0}), ("2026-10-21", {"Compound Wealth": 990.0, "Shorty": 1010.0}),
                        ("2026-10-22", {"Ditka89": 850.0, "Shorty": 1100.0})):
            pos = [{"player": k, "ticker": "CIFR" if "89" in k or "Comp" in k else "ZZ",
                    "side": "long" if "89" in k or "Comp" in k else "short", "entry": 9.3 if "89" in k else 20.875,
                    "close": 9.0 if "89" in k else 18.0, "value": v} for k, v in vals.items()]
            (P / d / f"daily_close_marks_{d}.json").write_text(json.dumps({"date": d, "positions": pos}))
        R = self.src / "reasons"
        R.mkdir()
        (R / "2026-10-21_Ditka89_CIFR_entry.md").write_text("- Why: First entry.\n- Stop: under the low. He moved it up later. Target: 12.\n")
        (R / "2026-10-22_1000_Ditka89_CIFR_entry.md").write_text("- Why: Timed re-entry.\n")
        (R / "2026-10-22_Ditka89_CIFR_exit.md").write_text("- Why: First exit, untimed.\n")
        (R / "2026-10-22_1100_Ditka89_CIFR_exit.md").write_text("- Why: Second exit, timed.\n")
        self.out = el.build(self.src)

    def tearDown(self):
        shutil.rmtree(self.src, ignore_errors=True)

    def bot(self, n):
        return [b for b in self.out["bots"] if b["bot"] == n][0]

    def test_week_number_any_and_filter(self):
        self.assertEqual(self.out["week_number"], 2)
        self.assertEqual(self.out["week"], "Wed Oct 21 2026 to Tue Oct 27 2026")
        self.assertEqual([h["date"] for h in self.out["history"]], ["2026-10-21", "2026-10-22"])
        self.assertNotIn("OLD", [t["ticker"] for t in self.out["trades"]])

    def test_history_canon_names(self):
        self.assertEqual(self.out["history"][0]["values"], {"Ditka89": 990.0, "Shorty": 1010.0})

    def test_exit_fee_recomputed_and_closed_position(self):
        fees = [t["fee_usd"] for t in self.out["trades"] if t["ticker"] == "CIFR"]
        self.assertEqual(fees[:2], [0.5, 0.85])
        c = self.bot("Ditka89")["closed_positions"][0]
        self.assertEqual((c["fees_usd"], c["realized_pnl_usd"], c["realized_pnl_pct"]), (1.35, -150.18, -15.01))
        self.assertEqual(c["entry_time_ct"], "2026-10-21 09:47:18")

    def test_missing_proof_falls_back_to_log_text(self):
        last = [t for t in self.out["trades"] if t["time_ct"] == "12:00"][0]
        self.assertEqual(last["fill"], 9.30)

    def test_short_open_pnl(self):
        p = self.bot("Shorty")["position"]
        self.assertEqual(p["amount_usd"], 1000.0)
        # 1000 x (2 - 18/20.875) - 1000 = 137.72
        self.assertEqual(p["open_pnl_usd"], 137.72)
        self.assertEqual(p["mark_time_ct"], "2026-10-22T15:00:00-05:00")

    def test_timed_reasons_and_collisions(self):
        t = {(x["time_ct"], x["action"]): x for x in self.out["trades"] if x["ticker"] == "CIFR"}
        self.assertEqual(t[("09:47", "buy")]["why"], "First entry.")
        self.assertEqual(t[("10:00", "buy")]["why"], "Timed re-entry.")
        self.assertEqual(t[("08:39", "sell")]["why"], "First exit, untimed.")
        self.assertEqual(t[("11:00", "sell")]["why"], "Second exit, timed.")
        self.assertFalse(t[("12:00", "buy")]["reason_filed"])
        self.assertTrue(all("reason_filed" in x for x in self.out["trades"]))

    def test_full_stop_bullet_kept(self):
        first = [x for x in self.out["trades"] if x["time_ct"] == "09:47"][0]
        self.assertEqual(first["stop"], "under the low. He moved it up later.")
        self.assertEqual(first["target"], "12.")

    def test_week_archive_written_once(self):
        d = Path(tempfile.mkdtemp())
        try:
            path = d / "leaderboard.json"
            path.write_text(json.dumps({"week": "Wed Oct 14 2026 to Tue Oct 20 2026", "bots": []}))
            el.write(self.out, path)
            arch = d / "leaderboard_archive" / "week-1.json"
            self.assertTrue(arch.exists())
            self.assertEqual(json.loads(arch.read_text())["week"], "Wed Oct 14 2026 to Tue Oct 20 2026")
            arch.write_text("{}")
            el.write(dict(self.out, week_number=3), path)  # week 2 -> 3 archives week-2 only
            self.assertEqual(arch.read_text(), "{}")
            self.assertTrue((d / "leaderboard_archive" / "week-2.json").exists())
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_sanitized(self):
        blob = json.dumps(self.out)
        for bad in ("proof/", "Compound Wealth", "Dragonfly", "Jared"):
            self.assertNotIn(bad, blob)


class Corrections(unittest.TestCase):
    """corrections.json overrides display fields of one logged trade; fills/P&L untouched."""

    def setUp(self):
        self.src = Path(tempfile.mkdtemp())
        (self.src / "scoreboard.md").write_text(MD, encoding="utf-8")
        (self.src / "proof" / "2026-10-16").mkdir(parents=True)
        (self.src / "proof" / "2026-10-16" / "daily_close_marks_2026-10-16.json").write_text(json.dumps(MARKS))
        (self.src / "reasons").mkdir()
        (self.src / "reasons" / "2026-10-16_Ditka89_BBB_entry.md").write_text(
            "# Ditka89 BBB\n- Why: Fallback so the slot isn't flat.\n- Stop: not recorded.\n", encoding="utf-8")
        self.base = el.build(self.src)

    def tearDown(self):
        shutil.rmtree(self.src, ignore_errors=True)

    def _row(self, out):
        return [t for t in out["trades"] if t["ticker"] == "BBB"][0]

    def test_time_and_stop_corrected(self):
        (self.src / "corrections.json").write_text(json.dumps({"corrections": [{
            "bot": "Ditka89", "date": "2026-10-16", "ticker": "BBB", "kind": "entry", "received_hhmm": "10:00",
            "set": {"time_ct": "10:01", "stop": "the original stop was 4.85."}}]}))
        out = el.build(self.src)
        before, after = self._row(self.base), self._row(out)
        self.assertEqual(after["time_ct"], "10:01")
        self.assertIn("4.85", after["stop"])
        self.assertEqual(after["fill"], before["fill"])
        self.assertEqual(after["fee_usd"], before["fee_usd"])
        self.assertEqual([(b["bot"], b["balance_usd"], b.get("pnl_usd")) for b in out["bots"]],
                         [(b["bot"], b["balance_usd"], b.get("pnl_usd")) for b in self.base["bots"]])

    def test_fill_cannot_be_corrected(self):
        (self.src / "corrections.json").write_text(json.dumps({"corrections": [{
            "bot": "Ditka89", "date": "2026-10-16", "ticker": "BBB", "set": {"fill": 1.0}}]}))
        with self.assertRaises(SystemExit):
            el.build(self.src)
