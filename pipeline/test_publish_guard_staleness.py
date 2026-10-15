"""Tests for publish_guard staleness checks (Oct 15 2026, warn-only; contract age blocks from 2026-10-29)."""
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

import publish_guard as g

REPO = Path(__file__).resolve().parent.parent
BEFORE = date(2026, 10, 20)
AFTER = date(2026, 10, 29)


class Tmp:
    def __init__(self, contract=None, trap="", home=None):
        self.root = Path(tempfile.mkdtemp())
        self.site = self.root / "site"
        (self.site / "audio").mkdir(parents=True)
        (self.site / "data").mkdir()
        if contract is not None:
            (self.site / "audio" / "debate_contract.json").write_text(json.dumps(contract))
        (self.site / "trap-map.html").write_text(f"<html><body><p>{trap}</p></body></html>")
        if home is not None:
            (self.site / "data" / "trap_map_home.json").write_text(json.dumps(home))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


OPEN = {"friday_iso": "2026-10-02", "resolution_status": "", "resolved_at": ""}
RESOLVED = {"friday_iso": "2026-09-04", "resolution_status": "yes", "resolved_at": "2026-09-15"}


class ContractAge(unittest.TestCase):
    def run_case(self, contract, today):
        t = Tmp(contract)
        try:
            return g.check_staleness(t.site, today)
        finally:
            t.close()

    def test_resolved_last_contract_passes(self):
        self.assertEqual(self.run_case(RESOLVED, AFTER), ([], []))
        self.assertEqual(self.run_case(RESOLVED, BEFORE), ([], []))

    def test_resolved_status_variants(self):
        for st in ("no", "void", "resolved", "YES"):
            self.assertEqual(self.run_case({"friday_iso": "2026-09-04", "resolution_status": st}, AFTER), ([], []))

    def test_open_stale_warns_before_block_date(self):
        block, warn = self.run_case(OPEN, BEFORE)
        self.assertEqual(block, [])
        self.assertEqual(len(warn), 1)
        self.assertIn("not resolved", warn[0])

    def test_open_stale_blocks_from_oct_29(self):
        block, warn = self.run_case(OPEN, AFTER)
        self.assertEqual(len(block), 1)
        self.assertEqual(warn, [])

    def test_fresh_open_contract_passes(self):
        self.assertEqual(self.run_case({"friday_iso": "2026-10-16"}, date(2026, 10, 22)), ([], []))

    def test_paused_flag_passes(self):
        self.assertEqual(self.run_case(dict(OPEN, paused=True), AFTER), ([], []))

    def test_block_date_constant(self):
        self.assertEqual(g.CONTRACT_AGE_BLOCK_FROM, date(2026, 10, 29))


class AsOfAndPct(unittest.TestCase):
    def test_old_check_date_warns_never_blocks(self):
        t = Tmp(RESOLVED, trap="As of Oct 12, Telesat hasn't filed anything new.")
        try:
            block, warn = g.check_staleness(t.site, date(2026, 11, 5))
            self.assertEqual(block, [])
            self.assertTrue(any("As of Oct 12" in w for w in warn))
            self.assertEqual(g.check_staleness(t.site, date(2026, 10, 20)), ([], []))
        finally:
            t.close()

    def test_reference_dates_ignored(self):
        t = Tmp(RESOLVED, trap="Cash as of Jun 30 was $1.2B. Debt as of Oct 1 is $300M.")
        try:
            self.assertEqual(g.check_staleness(t.site, AFTER), ([], []))
        finally:
            t.close()

    def test_undated_pct_warns_dated_pct_ok(self):
        t = Tmp(RESOLVED, trap="Shares moved -12.4% on heavy volume.", home={"a": "+3.1% since Sep 18"})
        try:
            block, warn = g.check_staleness(t.site, AFTER)
            self.assertEqual(block, [])
            self.assertEqual(len(warn), 1)
            self.assertIn("-12.4%", warn[0])
        finally:
            t.close()

    def test_run_guard_prints_warn_prefix_and_passes(self):
        t = Tmp(OPEN, trap="Shares moved -12.4% on heavy volume.")
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                stale_block, stale_warn = g.check_staleness(t.site, BEFORE)
            self.assertEqual(stale_block, [])
            self.assertEqual(len(stale_warn), 2)
        finally:
            t.close()


class LiveData(unittest.TestCase):
    def test_current_live_data_no_block_even_after_block_date(self):
        for today in (date(2026, 10, 15), AFTER, date(2026, 12, 1)):
            block, _ = g.check_staleness(REPO / "site", today)
            self.assertEqual(block, [], today)

    def test_full_guard_passes_on_repo(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok, reasons = g.run_publish_guard(REPO / "site", REPO / "pipeline", REPO, today=AFTER)
        self.assertTrue(ok, reasons)


if __name__ == "__main__":
    unittest.main()
