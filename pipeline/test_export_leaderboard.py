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
        self.out = el.build(self.src)

    def tearDown(self):
        shutil.rmtree(self.src, ignore_errors=True)

    def test_rank_balance_pnl(self):
        b = self.out["bots"]
        self.assertEqual([x["bot"] for x in b[:2]], ["Alpha", "Compound Wealth"])
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
        self.assertEqual(a["today_trades"][0]["reason"], "Exited on its stop")
        cw = [x for x in self.out["bots"] if x["bot"] == "Compound Wealth"][0]
        self.assertEqual(cw["today_trades"][0]["ticker"], "BBB")  # Ditka89 filing -> Compound Wealth
        self.assertEqual(cw["fines_usd"], 250.0)

    def test_public_text_clean(self):
        blob = json.dumps(self.out)
        for bad in ("/workspace", "proof/", ".json", "Dragonfly", "Ditka89"):
            self.assertNotIn(bad, blob)
        self.assertEqual(find_style_gate_hits(self.out), [])
        self.assertNotRegex(blob.lower(), r"\bbets?\b")
        self.assertEqual(self.out["as_of"], "2026-10-16")

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
