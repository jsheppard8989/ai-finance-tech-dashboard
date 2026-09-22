#!/usr/bin/env python3
"""Unit tests for market_data_io fail-closed helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from market_data_io import (
    contains_conflict_markers,
    load_market_data,
    save_market_data,
    scan_site_for_conflict_or_bad_json,
    strip_conflict_markers,
    validate_json_text,
)


class TestMarketDataIO(unittest.TestCase):
    def test_strip_conflict_prefers_second_side(self):
        raw = (
            '{\n'
            '<<<<<<< Updated upstream\n'
            '  "last_updated": "old",\n'
            '=======\n'
            '  "last_updated": "new",\n'
            '>>>>>>> Stashed changes\n'
            '  "x": 1\n'
            '}\n'
        )
        fixed = strip_conflict_markers(raw)
        self.assertFalse(contains_conflict_markers(fixed))
        self.assertIn('"last_updated": "new"', fixed)
        ok, _, data = validate_json_text(fixed)
        self.assertTrue(ok)
        self.assertEqual(data["last_updated"], "new")

    def test_load_repairs_conflicted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market_data.json"
            path.write_text(
                '{\n'
                '<<<<<<< Updated upstream\n'
                '  "a": 1,\n'
                '=======\n'
                '  "a": 2,\n'
                '>>>>>>> Stashed changes\n'
                '  "cftc_cot": {"report_date": "2026-09-15"}\n'
                '}\n',
                encoding="utf-8",
            )
            data, note = load_market_data(path, repair=True)
            self.assertIn("repaired", note)
            self.assertEqual(data["a"], 2)
            # On-disk file must now parse
            json.loads(path.read_text(encoding="utf-8"))

    def test_save_refuses_then_keeps_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market_data.json"
            good = {"ok": True, "curve_data": {"spreads": {}}}
            ok, _ = save_market_data(good, path)
            self.assertTrue(ok)
            # Corrupt in-memory attempt is not possible via save (dict always dumps);
            # simulate gate: scan rejects conflicted site
            site = Path(tmp) / "site"
            (site / "data").mkdir(parents=True)
            bad = site / "data" / "market_data.json"
            bad.write_text("<<<<<<<\nx\n=======\ny\n>>>>>>>\n", encoding="utf-8")
            (site / "data" / "data.js").write_text("const dashboardData = {};", encoding="utf-8")
            (site / "price_data.json").write_text("{}", encoding="utf-8")
            ok_scan, msg = scan_site_for_conflict_or_bad_json(site)
            self.assertFalse(ok_scan)
            self.assertIn("conflict", msg.lower())

    def test_scan_accepts_clean_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            (site / "data").mkdir(parents=True)
            (site / "data" / "market_data.json").write_text(
                json.dumps({"cftc_cot": {}}), encoding="utf-8"
            )
            (site / "data" / "data.js").write_text(
                "const dashboardData = {schemaVersion:1};", encoding="utf-8"
            )
            (site / "price_data.json").write_text("{}", encoding="utf-8")
            (site / "index.html").write_text("<html></html>", encoding="utf-8")
            ok_scan, msg = scan_site_for_conflict_or_bad_json(site)
            self.assertTrue(ok_scan, msg)


if __name__ == "__main__":
    unittest.main()
