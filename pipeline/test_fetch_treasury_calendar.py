#!/usr/bin/env python3
"""Tests for fetch_treasury_calendar (no network; tmp paths via conftest.py)."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fetch_treasury_calendar as ftc


def _sec(**kw):
    base = {"securityType": "Note", "securityTerm": "3-Year", "originalSecurityTerm": "3-Year",
            "reopening": "No", "tips": "No", "floatingRate": "No", "cusip": "X",
            "auctionDate": "2026-10-06T00:00:00", "issueDate": "2026-10-15T00:00:00"}
    base.update(kw)
    return base


AUCTIONED = [
    _sec(securityType="Bond", securityTerm="29-Year 10-Month", originalSecurityTerm="30-Year",
         reopening="Yes", cusip="912810UW6", auctionDate="2026-10-08T00:00:00",
         highYield="5.6180", bidToCoverRatio="2.540000", allocationPercentage="26.770000",
         offeringAmount="22000000000", totalAccepted="22000000000", indirectBidderAccepted="15000000000"),
    _sec(cusip="91282CRQ6", highYield="4.9320", bidToCoverRatio="2.62", allocationPercentage="8.35",
         offeringAmount="58000000000"),
    _sec(securityTerm="1-Year 10-Month", originalSecurityTerm="2-Year", reopening="Yes",
         floatingRate="Yes", cusip="91282CRD5", auctionDate="2026-09-23T00:00:00",
         highDiscountMargin="0.040000", bidToCoverRatio="2.63"),
    _sec(securityType="Bill", securityTerm="4-Week", cusip="BILL", highDiscountRate="4.1"),
]

UPCOMING = [
    _sec(securityType="Bill", securityTerm="13-Week", cusip="BILL2", auctionDate="2026-10-13T00:00:00"),
    _sec(securityType="Bond", securityTerm="19-Year 10-Month", originalSecurityTerm="20-Year",
         reopening="Yes", cusip="912810UX4", auctionDate="2026-10-21T00:00:00"),
    _sec(securityTerm="5-Year", originalSecurityTerm="5-Year", tips="Yes", cusip="91282CRR4",
         auctionDate="2026-10-22T00:00:00"),
    _sec(cusip="PAST", auctionDate="2026-10-01T00:00:00"),
]


def test_recent_results_sorted_coupons_only():
    cal = ftc.build_calendar(AUCTIONED, UPCOMING, today=date(2026, 10, 9))
    r = cal["recent_auction_results"]
    assert [x["cusip"] for x in r] == ["912810UW6", "91282CRQ6", "91282CRD5"]
    assert r[0]["high_yield_pct"] == 5.618
    assert r[0]["bid_to_cover"] == 2.54
    assert r[0]["security"] == "30-Year Bond (29y10m reopening)"
    assert r[0]["size_billions"] == 22.0
    assert r[2]["high_yield_pct"] is None and r[2]["high_discount_margin_pct"] == 0.04
    assert r[2]["security"].startswith("2-Year FRN")


def test_upcoming_drops_past_and_bills():
    cal = ftc.build_calendar(AUCTIONED, UPCOMING, today=date(2026, 10, 9))
    ups = cal["upcoming_auctions"]
    assert [u["date"] for u in ups] == ["2026-10-21", "2026-10-22"]
    assert ups[0]["security"] == "20-Year Bond (19y10m reopening)"
    assert ups[1]["security"] == "5-Year TIPS"


def test_upcoming_filters_relative_to_today():
    cal = ftc.build_calendar(AUCTIONED, UPCOMING, today=date(2026, 10, 22))
    assert [u["date"] for u in cal["upcoming_auctions"]] == ["2026-10-22"]


def test_sizes_filled_from_announced():
    ann = [{"cusip": "912810UX4", "auctionDate": "2026-10-21T00:00:00", "offeringAmount": "13000000000"}]
    cal = ftc.build_calendar(AUCTIONED, UPCOMING, ann, today=date(2026, 10, 9))
    assert cal["upcoming_auctions"][0]["size_billions"] == 13.0


def test_qra_is_scheduled_nov4_and_never_past():
    assert ftc.next_qra(date(2026, 10, 9)) ["date"] == "2026-11-04"
    assert ftc.next_qra(date(2026, 10, 9))["status"] == "scheduled"
    after = ftc.next_qra(date(2026, 11, 5))
    assert after["date"] >= "2026-11-05" and after["status"] == "estimated"
    assert date.fromisoformat(after["date"]).weekday() == 2  # Wednesday


def test_validate_rejects_empty_and_past():
    ok, _ = ftc.validate_calendar({"recent_auction_results": []})
    assert not ok
    ok, _ = ftc.validate_calendar({"recent_auction_results": [{}], "as_of_date": "2026-10-09",
                                   "upcoming_auctions": [{"date": "2026-10-01"}]})
    assert not ok


def test_main_writes_tmp_market_data(monkeypatch):
    path = ftc.MARKET_DATA_FILE  # tmp via conftest
    path.write_text(json.dumps({"curve_data": {"x": 1}, "data_fetch_status": {"treasury_calendar": "stub"}}))
    payloads = {ftc.AUCTIONED_URL: AUCTIONED, ftc.UPCOMING_URL: UPCOMING, ftc.ANNOUNCED_URL: []}
    monkeypatch.setattr(ftc, "_get_json", lambda url, timeout=30: payloads[url])
    assert ftc.main() == 0
    md = json.loads(path.read_text())
    assert md["curve_data"] == {"x": 1}  # other sections preserved
    assert md["data_fetch_status"]["treasury_calendar"] == "live"
    assert md["treasury_calendar"]["recent_auction_results"][0]["cusip"] == "912810UW6"


def test_main_fetch_failure_marks_stale(monkeypatch):
    path = ftc.MARKET_DATA_FILE
    path.write_text(json.dumps({"treasury_calendar": {"last_updated": "2026-09-10"},
                                "data_fetch_status": {"treasury_calendar": "live"}}))

    def boom(url, timeout=30):
        raise OSError("network down")
    monkeypatch.setattr(ftc, "_get_json", boom)
    assert ftc.main() == 1
    md = json.loads(path.read_text())
    assert md["treasury_calendar"]["_stale"] is True
    assert md["treasury_calendar"]["last_updated"] == "2026-09-10"
    assert md["data_fetch_status"]["treasury_calendar"] == "stale"


def test_tests_never_touch_real_site_data():
    assert "site_data" in str(ftc.MARKET_DATA_FILE)
