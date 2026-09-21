#!/usr/bin/env python3
"""
Tests for CFTC COT data fetching, focusing on:
- Parse logic for disaggregated text format
- Validation of parsed results
- Fail-closed behavior (preserve prior good data on failure)
- Net position formatting
- Contract pattern matching
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch_cot import (
    parse_disaggregated_txt,
    validate_cot_data,
    build_cot_result,
    format_net_display,
    mark_cot_stale,
    _run_curl_fetch,
    compute_change_1w,
    load_prior_nets,
    save_prior_nets,
    parse_finfut_nets_for_date,
    CONTRACT_PATTERNS,
    MARKET_DATA_FILE,
    COT_PRIOR_NETS_FILE,
)


# Sample CFTC disaggregated data (simplified header + rows)
SAMPLE_DISAGG_TXT = """Market_and_Exchange_Names,Report_Date_as_YYYY-MM-DD,Lev_Money_Positions_Long_All,Lev_Money_Positions_Short_All,Asset_Mgr_Positions_Long_All,Asset_Mgr_Positions_Short_All,Dealer_Positions_Long_All,Dealer_Positions_Short_All
"10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",2026-09-01,250000,150000,800000,600000,100000,200000
"2-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",2026-09-01,120000,80000,400000,350000,50000,75000
"U.S. TREASURY BONDS - CHICAGO BOARD OF TRADE",2026-09-01,180000,220000,500000,480000,80000,90000
"BITCOIN - CHICAGO MERCANTILE EXCHANGE",2026-09-01,15000,8000,25000,20000,5000,7000
"NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",2026-09-01,50000,80000,120000,100000,30000,40000
"""

SAMPLE_DISAGG_EMPTY = """Market_and_Exchange_Names,Report_Date_as_YYYY-MM-DD,Lev_Money_Positions_Long_All,Lev_Money_Positions_Short_All
"""


class TestParseDisaggregatedTxt:
    """Test parsing of CFTC disaggregated text format."""
    
    def test_parse_all_contracts(self):
        """All five target contracts should be parsed."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        assert '10y_note' in result
        assert '2y_note' in result
        assert '30y_bond' in result
        assert 'cme_btc' in result
        assert 'cme_nq' in result
    
    def test_parse_nq_positions(self):
        """NQ (Nasdaq-100) leveraged funds net should be calculated correctly."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        nq = result['cme_nq']
        # Net = Long - Short = 50000 - 80000 = -30000
        assert nq['leveraged_funds_net'] == -30000
        assert nq['leveraged_funds_long'] == 50000
        assert nq['leveraged_funds_short'] == 80000
    
    def test_parse_10y_note_positions(self):
        """10Y note leveraged funds net should be calculated correctly."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        ty = result['10y_note']
        # Net = Long - Short = 250000 - 150000 = 100000
        assert ty['leveraged_funds_net'] == 100000
        assert ty['leveraged_funds_long'] == 250000
        assert ty['leveraged_funds_short'] == 150000
    
    def test_parse_30y_bond_negative_net(self):
        """30Y bond with negative net should be calculated correctly."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        us = result['30y_bond']
        # Net = Long - Short = 180000 - 220000 = -40000
        assert us['leveraged_funds_net'] == -40000
    
    def test_parse_btc_positions(self):
        """Bitcoin positions should be parsed."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        btc = result['cme_btc']
        # Net = Long - Short = 15000 - 8000 = 7000
        assert btc['leveraged_funds_net'] == 7000
    
    def test_parse_report_date(self):
        """Report date should be extracted from parsed rows."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        assert result['10y_note']['report_date'] == '2026-09-01'
    
    def test_parse_asset_manager_positions(self):
        """Asset manager positions should also be parsed."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        ty = result['10y_note']
        # AM Net = 800000 - 600000 = 200000
        assert ty['asset_manager_net'] == 200000
    
    def test_parse_dealer_positions(self):
        """Dealer positions should also be parsed."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_TXT)
        
        ty = result['10y_note']
        # Dealer Net = 100000 - 200000 = -100000
        assert ty['dealer_net'] == -100000
    
    def test_parse_empty_returns_empty(self):
        """Empty data should return empty dict."""
        result = parse_disaggregated_txt(SAMPLE_DISAGG_EMPTY)
        assert result == {}
    
    def test_parse_none_returns_empty(self):
        """None input should return empty dict."""
        result = parse_disaggregated_txt(None)
        assert result == {}
    
    def test_parse_malformed_row_skipped(self):
        """Malformed rows should be skipped without crashing."""
        malformed = """Market_and_Exchange_Names,Report_Date_as_YYYY-MM-DD,Lev_Money_Positions_Long_All,Lev_Money_Positions_Short_All
"10-YEAR U.S. TREASURY NOTES",2026-09-01,not_a_number,150000
"BITCOIN - CHICAGO MERCANTILE EXCHANGE",2026-09-01,15000,8000
"""
        result = parse_disaggregated_txt(malformed)
        
        # Bitcoin should still parse
        assert 'cme_btc' in result
        assert result['cme_btc']['leveraged_funds_net'] == 7000


class TestContractPatternMatching:
    """Test contract name pattern matching."""
    
    def test_10y_patterns_match_variations(self):
        """10Y note patterns should match various CFTC naming conventions."""
        patterns = CONTRACT_PATTERNS['10y_note']
        test_names = [
            "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
            "10 YEAR U.S. TREASURY NOTES",
            "10-YR U.S. TREASURY NOTES - CBOT",
        ]
        
        for name in test_names:
            matched = False
            for pattern in patterns:
                if pattern.upper() in name.upper():
                    matched = True
                    break
            assert matched, f"Pattern should match: {name}"
    
    def test_btc_patterns_match_cme(self):
        """Bitcoin patterns should match CME contract names."""
        patterns = CONTRACT_PATTERNS['cme_btc']
        test_names = [
            "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
            "CME BITCOIN FUTURES",
        ]
        
        for name in test_names:
            matched = False
            for pattern in patterns:
                if pattern.upper() in name.upper():
                    matched = True
                    break
            assert matched, f"Pattern should match: {name}"
    
    def test_nq_patterns_match_cme(self):
        """NQ (Nasdaq-100) patterns should match CME contract names."""
        patterns = CONTRACT_PATTERNS['cme_nq']
        test_names = [
            "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
            "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
            "E-MINI NASDAQ-100 INDEX",
        ]
        
        for name in test_names:
            matched = False
            for pattern in patterns:
                if pattern.upper() in name.upper():
                    matched = True
                    break
            assert matched, f"Pattern should match: {name}"


class TestValidateCotData:
    """Test validation of parsed COT data."""
    
    def test_valid_data_passes(self):
        """Data with at least one leveraged_funds_net should pass."""
        data = {
            '10y_note': {'leveraged_funds_net': 100000},
            'cme_btc': {'leveraged_funds_net': None}
        }
        is_valid, error = validate_cot_data(data)
        assert is_valid == True
        assert error == ""
    
    def test_empty_data_fails(self):
        """Empty data should fail validation."""
        is_valid, error = validate_cot_data({})
        assert is_valid == False
        assert 'No COT data' in error
    
    def test_none_data_fails(self):
        """None data should fail validation."""
        is_valid, error = validate_cot_data(None)
        assert is_valid == False
    
    def test_all_null_nets_fails(self):
        """Data where all leveraged_funds_net are None should fail."""
        data = {
            '10y_note': {'leveraged_funds_net': None},
            'cme_btc': {'leveraged_funds_net': None}
        }
        is_valid, error = validate_cot_data(data)
        assert is_valid == False
        assert 'leveraged_funds_net' in error


class TestBuildCotResult:
    """Test building structured result from parsed data."""
    
    def test_build_result_structure(self):
        """Result should have correct structure."""
        parsed = {
            '10y_note': {'leveraged_funds_net': 100000, 'asset_manager_net': 200000},
            'cme_btc': {'leveraged_funds_net': 7000}
        }
        result = build_cot_result(parsed, '2026-09-01')
        
        assert 'rates_positioning' in result
        assert 'btc_positioning' in result
        assert '10y_note' in result['rates_positioning']
        assert 'cme_btc' in result['btc_positioning']
    
    def test_build_result_values(self):
        """Result should contain correct values."""
        parsed = {
            '10y_note': {'leveraged_funds_net': 100000, 'asset_manager_net': 200000},
        }
        result = build_cot_result(parsed, '2026-09-01')
        
        ty = result['rates_positioning']['10y_note']
        assert ty['leveraged_funds_net'] == 100000
        assert ty['asset_manager_net'] == 200000
        assert ty['contract'] == 'TY'
    
    def test_build_result_missing_contract_has_nulls(self):
        """Missing contracts should have null values, not missing keys."""
        parsed = {'10y_note': {'leveraged_funds_net': 100000}}
        result = build_cot_result(parsed, '2026-09-01')
        
        # 2Y and 30Y should exist but with null values
        assert '2y_note' in result['rates_positioning']
        assert result['rates_positioning']['2y_note']['leveraged_funds_net'] is None
    
    def test_build_result_metadata(self):
        """Result should include metadata fields."""
        parsed = {'10y_note': {'leveraged_funds_net': 100000}}
        result = build_cot_result(parsed, '2026-09-01')
        
        assert result['report_date'] == '2026-09-01'
        assert 'last_updated' in result
        assert '_comment' in result
    
    def test_build_result_includes_equity_positioning(self):
        """Result should include equity_positioning section with NQ."""
        parsed = {
            '10y_note': {'leveraged_funds_net': 100000},
            'cme_nq': {'leveraged_funds_net': -30000}
        }
        result = build_cot_result(parsed, '2026-09-01')
        
        assert 'equity_positioning' in result
        assert 'cme_nq' in result['equity_positioning']
        nq = result['equity_positioning']['cme_nq']
        assert nq['leveraged_funds_net'] == -30000
        assert nq['contract'] == 'NQ'
        assert nq['label'] == 'CME E-mini Nasdaq-100'


class TestChange1wComputation:
    """Test week-over-week change computation."""
    
    def test_compute_change_positive(self):
        """Positive change should be computed correctly."""
        change = compute_change_1w(150000, 100000)
        assert change == 50000
    
    def test_compute_change_negative(self):
        """Negative change should be computed correctly."""
        change = compute_change_1w(80000, 100000)
        assert change == -20000
    
    def test_compute_change_zero(self):
        """Zero change should be computed when nets are equal."""
        change = compute_change_1w(100000, 100000)
        assert change == 0
    
    def test_compute_change_none_current(self):
        """None current net should return None."""
        change = compute_change_1w(None, 100000)
        assert change is None
    
    def test_compute_change_none_prior(self):
        """None prior net should return None."""
        change = compute_change_1w(100000, None)
        assert change is None
    
    def test_compute_change_both_none(self):
        """Both None should return None."""
        change = compute_change_1w(None, None)
        assert change is None


class TestPriorNetsPersistence:
    """Test saving and loading of prior week nets."""
    
    def test_save_and_load_prior_nets(self):
        """Prior nets should be saved and loaded correctly."""
        import fetch_cot
        original_path = fetch_cot.COT_PRIOR_NETS_FILE
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "cot_prior_nets.json"
            fetch_cot.COT_PRIOR_NETS_FILE = tmppath
            
            try:
                test_nets = {
                    '10y_note': 100000,
                    'cme_btc': 7000,
                    'cme_nq': -30000
                }
                result = save_prior_nets('2026-09-01', test_nets)
                assert result == True
                
                loaded = load_prior_nets()
                assert loaded['report_date'] == '2026-09-01'
                assert loaded['nets']['10y_note'] == 100000
                assert loaded['nets']['cme_btc'] == 7000
                assert loaded['nets']['cme_nq'] == -30000
            finally:
                fetch_cot.COT_PRIOR_NETS_FILE = original_path
    
    def test_load_nonexistent_returns_empty(self):
        """Loading from nonexistent file should return empty dict."""
        import fetch_cot
        original_path = fetch_cot.COT_PRIOR_NETS_FILE
        fetch_cot.COT_PRIOR_NETS_FILE = Path("/nonexistent/path/cot_prior_nets.json")
        
        try:
            result = load_prior_nets()
            assert result == {}
        finally:
            fetch_cot.COT_PRIOR_NETS_FILE = original_path



class TestSameWeekRefetchNoFakeZero:
    """Same-week re-fetch must not yield change_1w=0 from identical prior."""

    def test_same_week_without_hist_prior_yields_null_change(self):
        """Legacy self-saved prior (same report_date) → change_1w None, not 0."""
        import fetch_cot
        original_path = fetch_cot.COT_PRIOR_NETS_FILE

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "cot_prior_nets.json"
            fetch_cot.COT_PRIOR_NETS_FILE = tmppath
            try:
                # Simulate bug state: prior file holds THIS week's nets only
                save_prior_nets('2026-09-15', {
                    '10y_note': -1868126,
                    'cme_btc': -6354,
                    'cme_nq': -13052,
                })
                parsed = {
                    '10y_note': {'leveraged_funds_net': -1868126},
                    'cme_btc': {'leveraged_funds_net': -6354},
                    'cme_nq': {'leveraged_funds_net': -13052},
                }
                result = build_cot_result(parsed, '2026-09-15')

                ty = result['rates_positioning']['10y_note']
                btc = result['btc_positioning']['cme_btc']
                nq = result['equity_positioning']['cme_nq']

                assert ty['change_1w'] is None, f"expected None, got {ty['change_1w']}"
                assert btc['change_1w'] is None
                assert nq['change_1w'] is None
                assert ty['prior_week_net'] is None
                assert result['prior_report_date'] is None
                # Must NOT be the fake-zero pattern
                assert ty['change_1w'] != 0
            finally:
                fetch_cot.COT_PRIOR_NETS_FILE = original_path

    def test_same_week_with_hist_prior_keeps_real_delta(self):
        """Two-week state: same-week re-fetch still shows Sep 8 → Sep 15 delta."""
        import fetch_cot
        original_path = fetch_cot.COT_PRIOR_NETS_FILE

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "cot_prior_nets.json"
            fetch_cot.COT_PRIOR_NETS_FILE = tmppath
            try:
                save_prior_nets(
                    '2026-09-15',
                    {
                        '10y_note': -1868126,
                        'cme_btc': -6354,
                        'cme_nq': -13052,
                    },
                    prior_report_date='2026-09-08',
                    prior_nets={
                        '10y_note': -1938754,
                        'cme_btc': -7892,
                        'cme_nq': -36884,
                    },
                )
                parsed = {
                    '10y_note': {'leveraged_funds_net': -1868126},
                    'cme_btc': {'leveraged_funds_net': -6354},
                    'cme_nq': {'leveraged_funds_net': -13052},
                }
                result = build_cot_result(parsed, '2026-09-15')

                assert result['prior_report_date'] == '2026-09-08'
                ty = result['rates_positioning']['10y_note']
                btc = result['btc_positioning']['cme_btc']
                nq = result['equity_positioning']['cme_nq']
                assert ty['prior_week_net'] == -1938754
                assert ty['change_1w'] == (-1868126) - (-1938754)  # +70628
                assert btc['change_1w'] == (-6354) - (-7892)  # +1538
                assert nq['change_1w'] == (-13052) - (-36884)  # +23832
                assert ty['change_1w'] != 0
            finally:
                fetch_cot.COT_PRIOR_NETS_FILE = original_path

    def test_new_week_advances_and_computes_delta(self):
        """When report_date advances, delta uses previous stored week."""
        import fetch_cot
        original_path = fetch_cot.COT_PRIOR_NETS_FILE

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "cot_prior_nets.json"
            fetch_cot.COT_PRIOR_NETS_FILE = tmppath
            try:
                save_prior_nets('2026-09-08', {
                    '10y_note': -1938754,
                    'cme_btc': -7892,
                    'cme_nq': -36884,
                })
                parsed = {
                    '10y_note': {'leveraged_funds_net': -1868126},
                    'cme_btc': {'leveraged_funds_net': -6354},
                    'cme_nq': {'leveraged_funds_net': -13052},
                }
                result = build_cot_result(parsed, '2026-09-15')

                assert result['prior_report_date'] == '2026-09-08'
                assert result['rates_positioning']['10y_note']['change_1w'] == 70628

                # State now has two-week history
                loaded = load_prior_nets()
                assert loaded['report_date'] == '2026-09-15'
                assert loaded['prior_report_date'] == '2026-09-08'
                assert loaded['prior_nets']['10y_note'] == -1938754
            finally:
                fetch_cot.COT_PRIOR_NETS_FILE = original_path


class TestParseFinfutNetsForDate:
    """Historical FinFutYY parser prefers classic contracts over MICRO/ULTRA."""

    SAMPLE = (
        "Market_and_Exchange_Names,Report_Date_as_YYYY-MM-DD,"
        "Lev_Money_Positions_Long_All,Lev_Money_Positions_Short_All\n"
        '"UST 10Y NOTE - CHICAGO BOARD OF TRADE",2026-09-08,391836,2330590\n'
        '"BITCOIN - CHICAGO MERCANTILE EXCHANGE",2026-09-08,5146,13038\n'
        '"MICRO BITCOIN - CHICAGO MERCANTILE EXCHANGE",2026-09-08,19259,24665\n'
        '"NASDAQ-100 CONSOLIDATED - CHICAGO MERCANTILE EXCHANGE",2026-09-08,42041,78925\n'
        '"NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",2026-09-08,47674,79546\n'
        '"UST BOND - CHICAGO BOARD OF TRADE",2026-09-08,133029,409994\n'
        '"ULTRA UST BOND - CHICAGO BOARD OF TRADE",2026-09-08,86352,950623\n'
    )

    def test_prefers_classic_contracts(self):
        nets = parse_finfut_nets_for_date(self.SAMPLE, '2026-09-08')
        assert nets['10y_note'] == 391836 - 2330590
        assert nets['cme_btc'] == 5146 - 13038  # not MICRO
        assert nets['cme_nq'] == 42041 - 78925  # CONSOLIDATED
        assert nets['30y_bond'] == 133029 - 409994  # not ULTRA


class TestFormatNetDisplay:
    """Test formatting of net positions for display."""
    
    def test_positive_large_net(self):
        """Large positive net should show +123K format."""
        display = format_net_display(123456)
        assert display == '+123K'
    
    def test_negative_large_net(self):
        """Large negative net should show -45K format."""
        display = format_net_display(-45678)
        assert display == '-46K'
    
    def test_small_positive_net(self):
        """Small positive net should not use K suffix."""
        display = format_net_display(500)
        assert display == '+500'
    
    def test_small_negative_net(self):
        """Small negative net should not use K suffix."""
        display = format_net_display(-800)
        assert display == '-800'
    
    def test_zero_net(self):
        """Zero net should show 0."""
        display = format_net_display(0)
        assert display == '0'
    
    def test_none_returns_none(self):
        """None input should return None."""
        display = format_net_display(None)
        assert display is None


class TestStaleDataPreservation:
    """Test that stale marking preserves existing data."""
    
    def test_mark_data_stale_adds_metadata(self):
        """mark_cot_stale should add stale metadata without overwriting data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "market_data.json"
            good_data = {
                'cftc_cot': {
                    'last_updated': '2026-09-01T10:00:00',
                    'report_date': '2026-08-27',
                    'rates_positioning': {
                        '10y_note': {
                            'leveraged_funds_net': 100000
                        }
                    }
                },
                'data_fetch_status': {'cftc_cot': 'live'}
            }
            tmppath.write_text(json.dumps(good_data))
            
            # Monkey-patch MARKET_DATA_FILE for this test
            import fetch_cot
            original_path = fetch_cot.MARKET_DATA_FILE
            fetch_cot.MARKET_DATA_FILE = tmppath
            
            try:
                # Mark as stale
                result = mark_cot_stale("Test error: network timeout")
                assert result == True
                
                # Read back and verify
                updated = json.loads(tmppath.read_text())
                
                # Original data preserved
                assert updated['cftc_cot']['report_date'] == '2026-08-27'
                assert updated['cftc_cot']['rates_positioning']['10y_note']['leveraged_funds_net'] == 100000
                assert updated['cftc_cot']['last_updated'] == '2026-09-01T10:00:00'
                
                # Stale metadata added
                assert updated['cftc_cot']['_stale'] == True
                assert 'network timeout' in updated['cftc_cot']['_stale_reason']
                assert '_stale_since' in updated['cftc_cot']
                
                # Status updated
                assert updated['data_fetch_status']['cftc_cot'] == 'stale'
                
            finally:
                fetch_cot.MARKET_DATA_FILE = original_path
    
    def test_mark_stale_no_file_returns_false(self):
        """mark_cot_stale should return False if no file exists."""
        import fetch_cot
        original_path = fetch_cot.MARKET_DATA_FILE
        fetch_cot.MARKET_DATA_FILE = Path("/nonexistent/path/market_data.json")
        
        try:
            result = mark_cot_stale("Test error")
            assert result == False
        finally:
            fetch_cot.MARKET_DATA_FILE = original_path


class TestFailClosedBehavior:
    """Test fail-closed behavior: never invent data, preserve prior good."""
    
    def test_parse_failure_leaves_nulls(self):
        """Parse failure should result in null values, not fabricated data."""
        # Malformed data that can't be parsed properly
        bad_data = "completely invalid data that cannot be parsed"
        result = parse_disaggregated_txt(bad_data)
        
        # Should return empty dict, not fabricated values
        assert result == {}
    
    def test_missing_columns_handled_gracefully(self):
        """Missing columns should not crash, just leave nulls."""
        incomplete = """Market_and_Exchange_Names,Report_Date_as_YYYY-MM-DD
"10-YEAR U.S. TREASURY NOTES",2026-09-01
"""
        result = parse_disaggregated_txt(incomplete)
        
        # Should parse but without position data (no lev_long/lev_short columns)
        if '10y_note' in result:
            # If contract matched, leveraged_funds_net should be None
            assert result['10y_note'].get('leveraged_funds_net') is None


class TestCurlPreference:
    """
    Test curl preference logic for Mac Anaconda SSL workaround.
    
    DOCUMENTED BEHAVIOR:
    When fetching CFTC data, the system prefers /usr/bin/curl (macOS system curl)
    over PATH curl (which may be Anaconda curl with outdated SSL certs).
    This prevents SSL certificate failures (http=000 / returncode 60/35) on
    Macs with Anaconda installed.
    
    The preference order is:
    1. /usr/bin/curl or /bin/curl (system curl)
    2. PATH curl (may be Anaconda)
    3. urllib fallback
    """
    
    def test_run_curl_fetch_returns_none_on_missing_binary(self):
        """_run_curl_fetch should return None if binary doesn't exist."""
        result = _run_curl_fetch('/nonexistent/curl', 'http://example.com', 'test')
        assert result is None
    
    def test_system_curl_paths_exist_on_unix(self):
        """On Unix systems, system curl should be at /usr/bin/curl."""
        import platform
        if platform.system() in ('Darwin', 'Linux'):
            system_curl = Path('/usr/bin/curl')
            # On most Unix systems, system curl exists
            # This test documents the expected path
            assert system_curl.exists() or Path('/bin/curl').exists(), \
                "System curl expected at /usr/bin/curl or /bin/curl on Unix"
    
    def test_curl_preference_order_documented(self):
        """
        Verify the documented preference order in fetch_cot_page docstring.
        This is a documentation test - verifying the order is correct.
        
        Expected order:
        1. System curl (/usr/bin/curl) - uses macOS Keychain certs
        2. PATH curl - may be Anaconda curl with outdated certs
        3. urllib - Python ssl fallback
        
        This ordering ensures Mac users with Anaconda get working fetches.
        """
        import shutil
        from fetch_cot import fetch_cot_page
        
        # Verify the docstring documents the preference
        docstring = fetch_cot_page.__doc__ or ""
        assert '/usr/bin/curl' in docstring, "Docstring should mention system curl path"
        assert 'Anaconda' in docstring, "Docstring should explain Anaconda SSL issue"
        assert 'SSL' in docstring, "Docstring should mention SSL certificates"


def run_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [
        TestParseDisaggregatedTxt,
        TestContractPatternMatching,
        TestValidateCotData,
        TestBuildCotResult,
        TestChange1wComputation,
        TestPriorNetsPersistence,
        TestSameWeekRefetchNoFakeZero,
        TestParseFinfutNetsForDate,
        TestFormatNetDisplay,
        TestStaleDataPreservation,
        TestFailClosedBehavior,
        TestCurlPreference,
    ]
    
    total = 0
    passed = 0
    failed = 0
    
    for test_class in test_classes:
        print(f"\n{test_class.__name__}")
        print("-" * len(test_class.__name__))
        
        instance = test_class()
        for method_name in dir(instance):
            if not method_name.startswith('test_'):
                continue
            
            total += 1
            method = getattr(instance, method_name)
            try:
                method()
                print(f"  ✓ {method_name}")
                passed += 1
            except AssertionError as e:
                print(f"  ✗ {method_name}: {e}")
                traceback.print_exc()
                failed += 1
            except Exception as e:
                print(f"  ✗ {method_name}: {type(e).__name__}: {e}")
                traceback.print_exc()
                failed += 1
    
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(run_tests())
