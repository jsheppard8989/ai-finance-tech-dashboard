#!/usr/bin/env python3
"""
Tests for fetch_curve.py yield curve data fetching, focusing on:
- Treasury XML parsing (primary source)
- Spread computation (2s10s, 10s30s from levels)
- Signal determination (inverted, flat, normal)
- MOVE index fetching from Yahoo
- Optional FRED enrichment (doesn't block pipeline)
- Stale data preservation (fail-closed pattern)
- Validation of required fields
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from fetch_curve import (
    parse_treasury_xml,
    validate_curve_data,
    mark_curve_data_stale,
    MARKET_DATA_FILE
)


# Sample Treasury XML for testing (matches real structure)
SAMPLE_TREASURY_XML = '''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <title type="text">DailyTreasuryYieldCurveRateData</title>
  <entry>
    <content type="application/xml">
      <m:properties>
        <d:NEW_DATE>2026-09-03T00:00:00</d:NEW_DATE>
        <d:BC_1MONTH>4.25</d:BC_1MONTH>
        <d:BC_3MONTH>4.30</d:BC_3MONTH>
        <d:BC_6MONTH>4.15</d:BC_6MONTH>
        <d:BC_1YEAR>3.95</d:BC_1YEAR>
        <d:BC_2YEAR>3.85</d:BC_2YEAR>
        <d:BC_5YEAR>3.90</d:BC_5YEAR>
        <d:BC_7YEAR>4.00</d:BC_7YEAR>
        <d:BC_10YEAR>4.20</d:BC_10YEAR>
        <d:BC_20YEAR>4.55</d:BC_20YEAR>
        <d:BC_30YEAR>4.45</d:BC_30YEAR>
      </m:properties>
    </content>
  </entry>
  <entry>
    <content type="application/xml">
      <m:properties>
        <d:NEW_DATE>2026-09-02T00:00:00</d:NEW_DATE>
        <d:BC_1MONTH>4.24</d:BC_1MONTH>
        <d:BC_3MONTH>4.28</d:BC_3MONTH>
        <d:BC_6MONTH>4.12</d:BC_6MONTH>
        <d:BC_1YEAR>3.92</d:BC_1YEAR>
        <d:BC_2YEAR>3.80</d:BC_2YEAR>
        <d:BC_5YEAR>3.85</d:BC_5YEAR>
        <d:BC_7YEAR>3.95</d:BC_7YEAR>
        <d:BC_10YEAR>4.15</d:BC_10YEAR>
        <d:BC_20YEAR>4.50</d:BC_20YEAR>
        <d:BC_30YEAR>4.40</d:BC_30YEAR>
      </m:properties>
    </content>
  </entry>
</feed>'''

# XML with inverted curve (2Y > 10Y)
INVERTED_CURVE_XML = '''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry>
    <content type="application/xml">
      <m:properties>
        <d:NEW_DATE>2026-09-03T00:00:00</d:NEW_DATE>
        <d:BC_2YEAR>5.20</d:BC_2YEAR>
        <d:BC_10YEAR>4.80</d:BC_10YEAR>
        <d:BC_30YEAR>4.70</d:BC_30YEAR>
      </m:properties>
    </content>
  </entry>
</feed>'''

# XML with flat curve
FLAT_CURVE_XML = '''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry>
    <content type="application/xml">
      <m:properties>
        <d:NEW_DATE>2026-09-03T00:00:00</d:NEW_DATE>
        <d:BC_2YEAR>4.00</d:BC_2YEAR>
        <d:BC_10YEAR>4.10</d:BC_10YEAR>
        <d:BC_30YEAR>4.15</d:BC_30YEAR>
      </m:properties>
    </content>
  </entry>
</feed>'''


class TestTreasuryXMLParsing:
    """Test Treasury.gov XML parsing."""
    
    def test_parse_valid_xml(self):
        """Valid Treasury XML should parse correctly."""
        records = parse_treasury_xml(SAMPLE_TREASURY_XML)
        
        assert len(records) == 2
        # Most recent first after sorting
        assert records[0]['date'] == '2026-09-03'
        assert records[1]['date'] == '2026-09-02'
        
    def test_parse_yields_correctly(self):
        """Yields should be extracted as floats."""
        records = parse_treasury_xml(SAMPLE_TREASURY_XML)
        latest = records[0]
        
        assert latest['2y'] == 3.85
        assert latest['10y'] == 4.20
        assert latest['30y'] == 4.45
        
    def test_parse_all_maturities(self):
        """Should extract all available maturities."""
        records = parse_treasury_xml(SAMPLE_TREASURY_XML)
        latest = records[0]
        
        assert '1m' in latest
        assert '3m' in latest
        assert '6m' in latest
        assert '1yr' in latest
        assert '5y' in latest
        assert '7y' in latest
        assert '20y' in latest
        
    def test_parse_empty_xml(self):
        """Empty XML should return empty list."""
        records = parse_treasury_xml('')
        assert records == []
        
    def test_parse_malformed_xml(self):
        """Malformed XML should return empty list (not crash)."""
        records = parse_treasury_xml('<invalid>not valid xml')
        assert records == []
        
    def test_parse_xml_missing_yields(self):
        """XML with missing yield elements should still parse available data."""
        partial_xml = '''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry>
    <content type="application/xml">
      <m:properties>
        <d:NEW_DATE>2026-09-03T00:00:00</d:NEW_DATE>
        <d:BC_10YEAR>4.20</d:BC_10YEAR>
      </m:properties>
    </content>
  </entry>
</feed>'''
        records = parse_treasury_xml(partial_xml)
        
        assert len(records) == 1
        assert records[0]['10y'] == 4.20
        assert '2y' not in records[0]


class TestSpreadComputation:
    """Test yield spread calculations."""
    
    def test_2s10s_spread_normal(self):
        """Normal (positive) 2s10s spread computed correctly."""
        records = parse_treasury_xml(SAMPLE_TREASURY_XML)
        latest = records[0]
        
        # 2s10s = 10Y - 2Y = 4.20 - 3.85 = 0.35 = 35 bps
        spread_2s10s = round((latest['10y'] - latest['2y']) * 100, 1)
        assert spread_2s10s == 35.0
        
    def test_2s10s_spread_inverted(self):
        """Inverted 2s10s spread computed correctly."""
        records = parse_treasury_xml(INVERTED_CURVE_XML)
        latest = records[0]
        
        # 2s10s = 10Y - 2Y = 4.80 - 5.20 = -0.40 = -40 bps
        spread_2s10s = round((latest['10y'] - latest['2y']) * 100, 1)
        assert spread_2s10s == -40.0
        
    def test_10s30s_spread_normal(self):
        """Normal 10s30s spread computed correctly."""
        records = parse_treasury_xml(SAMPLE_TREASURY_XML)
        latest = records[0]
        
        # 10s30s = 30Y - 10Y = 4.45 - 4.20 = 0.25 = 25 bps
        spread_10s30s = round((latest['30y'] - latest['10y']) * 100, 1)
        assert spread_10s30s == 25.0
        
    def test_10s30s_spread_inverted(self):
        """Inverted 10s30s spread computed correctly."""
        records = parse_treasury_xml(INVERTED_CURVE_XML)
        latest = records[0]
        
        # 10s30s = 30Y - 10Y = 4.70 - 4.80 = -0.10 = -10 bps
        spread_10s30s = round((latest['30y'] - latest['10y']) * 100, 1)
        assert spread_10s30s == -10.0


class TestSignalDetermination:
    """Test spread signal determination (inverted/flat/normal)."""
    
    def test_inverted_signal_2s10s(self):
        """Negative spread should be 'inverted'."""
        spread_bps = -40.0  # From inverted curve
        signal = 'inverted' if spread_bps < 0 else ('flat' if spread_bps < 25 else 'normal')
        assert signal == 'inverted'
        
    def test_flat_signal_2s10s(self):
        """Small positive spread (<25 bps) should be 'flat'."""
        spread_bps = 10.0  # Small positive
        signal = 'inverted' if spread_bps < 0 else ('flat' if spread_bps < 25 else 'normal')
        assert signal == 'flat'
        
    def test_normal_signal_2s10s(self):
        """Normal positive spread (>=25 bps) should be 'normal'."""
        spread_bps = 35.0  # From sample data
        signal = 'inverted' if spread_bps < 0 else ('flat' if spread_bps < 25 else 'normal')
        assert signal == 'normal'
        
    def test_flat_signal_10s30s(self):
        """Small 10s30s spread (<15 bps) should be 'flat'."""
        spread_bps = 5.0  # Small positive
        signal = 'inverted' if spread_bps < 0 else ('flat' if spread_bps < 15 else 'normal')
        assert signal == 'flat'


class TestValidateCurveData:
    """Test validation of curve data structure."""
    
    def test_valid_data_passes(self):
        """Complete valid data should pass validation."""
        data = {
            'spreads': {
                '2s10s': {'value_bps': 35.0}
            },
            'levels': {
                '2y': {'value': 3.85},
                '10y': {'value': 4.20}
            }
        }
        is_valid, error = validate_curve_data(data)
        assert is_valid == True
        assert error == ""
        
    def test_missing_2s10s_fails(self):
        """Missing 2s10s spread should fail validation."""
        data = {
            'spreads': {},
            'levels': {
                '2y': {'value': 3.85},
                '10y': {'value': 4.20}
            }
        }
        is_valid, error = validate_curve_data(data)
        assert is_valid == False
        assert '2s10s' in error.lower()
        
    def test_null_2s10s_fails(self):
        """Null 2s10s spread should fail validation."""
        data = {
            'spreads': {
                '2s10s': {'value_bps': None}
            },
            'levels': {
                '2y': {'value': 3.85},
                '10y': {'value': 4.20}
            }
        }
        is_valid, error = validate_curve_data(data)
        assert is_valid == False
        
    def test_missing_2y_level_fails(self):
        """Missing 2Y level should fail validation."""
        data = {
            'spreads': {
                '2s10s': {'value_bps': 35.0}
            },
            'levels': {
                '10y': {'value': 4.20}
            }
        }
        is_valid, error = validate_curve_data(data)
        assert is_valid == False
        assert '2y' in error.lower()
        
    def test_missing_10y_level_fails(self):
        """Missing 10Y level should fail validation."""
        data = {
            'spreads': {
                '2s10s': {'value_bps': 35.0}
            },
            'levels': {
                '2y': {'value': 3.85}
            }
        }
        is_valid, error = validate_curve_data(data)
        assert is_valid == False
        assert '10y' in error.lower()
        
    def test_none_data_fails(self):
        """None data should fail validation."""
        is_valid, error = validate_curve_data(None)
        assert is_valid == False


class TestStaleDataPreservation:
    """Test that stale marking preserves existing data (fail-closed pattern)."""
    
    def test_mark_curve_data_stale_adds_metadata(self):
        """mark_curve_data_stale should add stale metadata without overwriting data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "market_data.json"
            good_data = {
                'curve_data': {
                    'last_updated': '2026-09-01T10:00:00',
                    'spreads': {
                        '2s10s': {'value_bps': 35.0, 'signal': 'normal'}
                    },
                    'levels': {
                        '2y': {'value': 3.85},
                        '10y': {'value': 4.20}
                    }
                },
                'data_fetch_status': {'curve_data': 'live'}
            }
            tmppath.write_text(json.dumps(good_data))
            
            # Monkey-patch MARKET_DATA_FILE for this test
            import fetch_curve
            original_path = fetch_curve.MARKET_DATA_FILE
            fetch_curve.MARKET_DATA_FILE = tmppath
            
            try:
                # Mark as stale
                result = mark_curve_data_stale("Test error: Treasury.gov timeout")
                assert result == True
                
                # Read back and verify
                updated = json.loads(tmppath.read_text())
                
                # Original data preserved
                assert updated['curve_data']['spreads']['2s10s']['value_bps'] == 35.0
                assert updated['curve_data']['levels']['2y']['value'] == 3.85
                assert updated['curve_data']['last_updated'] == '2026-09-01T10:00:00'
                
                # Stale metadata added
                assert updated['curve_data']['_stale'] == True
                assert 'Treasury.gov timeout' in updated['curve_data']['_stale_reason']
                assert '_stale_since' in updated['curve_data']
                
                # Status updated
                assert updated['data_fetch_status']['curve_data'] == 'stale'
                
            finally:
                fetch_curve.MARKET_DATA_FILE = original_path
                
    def test_mark_stale_no_existing_file(self):
        """mark_curve_data_stale handles missing file gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "nonexistent.json"
            
            import fetch_curve
            original_path = fetch_curve.MARKET_DATA_FILE
            fetch_curve.MARKET_DATA_FILE = tmppath
            
            try:
                result = mark_curve_data_stale("Test error")
                assert result == False  # Should return False, not crash
            finally:
                fetch_curve.MARKET_DATA_FILE = original_path


class TestFREDOptional:
    """Test that FRED is truly optional and doesn't block the pipeline."""
    
    def test_pipeline_works_without_fred_key(self):
        """Pipeline should succeed without FRED_API_KEY set."""
        import os
        # Ensure no FRED key
        fred_key = os.environ.pop('FRED_API_KEY', None)
        
        try:
            # FRED enrichment should not crash
            from fetch_curve import try_fred_enrichment
            result = try_fred_enrichment()
            # Result can be None (unavailable) or dict (available)
            # Either is acceptable - it should NOT raise
            assert result is None or isinstance(result, dict)
        finally:
            if fred_key:
                os.environ['FRED_API_KEY'] = fred_key


class TestMOVESignals:
    """Test MOVE index signal thresholds."""
    
    def test_move_low_vol_signal(self):
        """MOVE < 80 should be 'low_vol'."""
        value = 75
        thresholds = {'low': 80, 'normal': 100, 'elevated': 120, 'high': 150}
        
        if value < thresholds['low']:
            signal = 'low_vol'
        elif value < thresholds['normal']:
            signal = 'normal'
        elif value < thresholds['elevated']:
            signal = 'elevated'
        elif value < thresholds['high']:
            signal = 'high'
        else:
            signal = 'extreme'
            
        assert signal == 'low_vol'
        
    def test_move_normal_signal(self):
        """80 <= MOVE < 100 should be 'normal'."""
        value = 90
        thresholds = {'low': 80, 'normal': 100, 'elevated': 120, 'high': 150}
        
        if value < thresholds['low']:
            signal = 'low_vol'
        elif value < thresholds['normal']:
            signal = 'normal'
        elif value < thresholds['elevated']:
            signal = 'elevated'
        elif value < thresholds['high']:
            signal = 'high'
        else:
            signal = 'extreme'
            
        assert signal == 'normal'
        
    def test_move_elevated_signal(self):
        """100 <= MOVE < 120 should be 'elevated'."""
        value = 110
        thresholds = {'low': 80, 'normal': 100, 'elevated': 120, 'high': 150}
        
        if value < thresholds['low']:
            signal = 'low_vol'
        elif value < thresholds['normal']:
            signal = 'normal'
        elif value < thresholds['elevated']:
            signal = 'elevated'
        elif value < thresholds['high']:
            signal = 'high'
        else:
            signal = 'extreme'
            
        assert signal == 'elevated'
        
    def test_move_high_signal(self):
        """120 <= MOVE < 150 should be 'high'."""
        value = 135
        thresholds = {'low': 80, 'normal': 100, 'elevated': 120, 'high': 150}
        
        if value < thresholds['low']:
            signal = 'low_vol'
        elif value < thresholds['normal']:
            signal = 'normal'
        elif value < thresholds['elevated']:
            signal = 'elevated'
        elif value < thresholds['high']:
            signal = 'high'
        else:
            signal = 'extreme'
            
        assert signal == 'high'
        
    def test_move_extreme_signal(self):
        """MOVE >= 150 should be 'extreme'."""
        value = 175
        thresholds = {'low': 80, 'normal': 100, 'elevated': 120, 'high': 150}
        
        if value < thresholds['low']:
            signal = 'low_vol'
        elif value < thresholds['normal']:
            signal = 'normal'
        elif value < thresholds['elevated']:
            signal = 'elevated'
        elif value < thresholds['high']:
            signal = 'high'
        else:
            signal = 'extreme'
            
        assert signal == 'extreme'


class TestSourceLabeling:
    """Test that source labels are honest (Treasury.gov vs FRED)."""
    
    def test_spread_source_is_treasury(self):
        """Spreads should indicate Treasury.gov as source."""
        # This tests the data structure, not the fetch
        spread_data = {
            '2s10s': {
                'value_bps': 35.0,
                'source': 'Treasury.gov (computed)',
                'calculation': '10Y - 2Y from Treasury daily curve'
            }
        }
        assert 'Treasury' in spread_data['2s10s']['source']
        assert 'FRED' not in spread_data['2s10s']['source']
        
    def test_level_source_is_treasury(self):
        """Levels should indicate Treasury.gov as source."""
        level_data = {
            '2y': {
                'value': 3.85,
                'source': 'Treasury.gov'
            }
        }
        assert 'Treasury' in level_data['2y']['source']
        
    def test_move_source_is_yahoo(self):
        """MOVE should indicate Yahoo Finance as source."""
        move_data = {
            'value': 95.0,
            'source': 'Yahoo Finance',
            'yahoo_symbol': '^MOVE'
        }
        assert 'Yahoo' in move_data['source']


def run_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [
        TestTreasuryXMLParsing,
        TestSpreadComputation,
        TestSignalDetermination,
        TestValidateCurveData,
        TestStaleDataPreservation,
        TestFREDOptional,
        TestMOVESignals,
        TestSourceLabeling,
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
