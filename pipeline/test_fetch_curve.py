#!/usr/bin/env python3
"""
Tests for curve data fetching, focusing on:
- FRED CSV parsing
- 10s30s spread computation
- Fail-closed behavior (preserve prior values on failure)
- Data merge logic
- Stale marking
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from fetch_curve import (
    fetch_fred_series,
    fetch_move_index,
    fetch_all_curve_data,
    has_any_data,
    merge_curve_data,
    mark_curve_stale,
    MARKET_DATA_FILE,
)


class TestFREDParsing:
    """Test FRED CSV response parsing."""
    
    def test_parse_valid_fred_csv(self):
        """Valid FRED CSV should parse correctly."""
        mock_csv = """DATE,T10Y2Y
2026-09-01,0.45
2026-09-02,0.48
2026-09-03,.
2026-09-04,0.52
"""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = mock_csv.encode('utf-8')
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            value, date = fetch_fred_series("T10Y2Y")
            
            assert value == 0.52
            assert date == "2026-09-04"
    
    def test_parse_fred_csv_with_missing_values(self):
        """FRED CSV with dots (missing values) should skip to last valid."""
        mock_csv = """DATE,DGS10
2026-09-01,4.25
2026-09-02,4.28
2026-09-03,.
"""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = mock_csv.encode('utf-8')
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            value, date = fetch_fred_series("DGS10")
            
            assert value == 4.28
            assert date == "2026-09-02"
    
    def test_parse_fred_csv_empty_response(self):
        """Empty FRED CSV should return None."""
        mock_csv = """DATE,T10Y2Y
"""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = mock_csv.encode('utf-8')
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            value, date = fetch_fred_series("T10Y2Y")
            
            assert value is None
            assert date is None
    
    def test_fred_network_error_returns_none(self):
        """Network error should return None (fail-closed)."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")
            
            value, date = fetch_fred_series("T10Y2Y")
            
            assert value is None
            assert date is None


class TestMOVEParsing:
    """Test Yahoo MOVE index response parsing."""
    
    def test_parse_valid_move_response(self):
        """Valid Yahoo response should parse correctly."""
        mock_response_data = {
            'chart': {
                'result': [{
                    'meta': {
                        'regularMarketPrice': 95.42,
                        'regularMarketTime': 1725465600  # 2024-09-04
                    }
                }]
            }
        }
        
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(mock_response_data).encode('utf-8')
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            value, date = fetch_move_index()
            
            assert value == 95.42
            assert date is not None
    
    def test_move_no_result_returns_none(self):
        """Empty Yahoo result should return None."""
        mock_response_data = {'chart': {'result': None}}
        
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(mock_response_data).encode('utf-8')
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            value, date = fetch_move_index()
            
            assert value is None
            assert date is None
    
    def test_move_network_error_returns_none(self):
        """Network error should return None (fail-closed)."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")
            
            value, date = fetch_move_index()
            
            assert value is None
            assert date is None


class TestSpreadComputation:
    """Test 10s30s spread computation."""
    
    def test_compute_10s30s_spread(self):
        """10s30s = DGS30 - DGS10."""
        mock_csvs = {
            'DGS10': """DATE,DGS10
2026-09-04,4.25""",
            'DGS30': """DATE,DGS30
2026-09-04,4.55""",
            'T10Y2Y': """DATE,T10Y2Y
2026-09-04,0.45""",
            'DGS2': """DATE,DGS2
2026-09-04,3.80""",
        }
        
        def mock_urlopen_side_effect(req, timeout=30):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            for series, csv in mock_csvs.items():
                if series in url:
                    mock_resp = MagicMock()
                    mock_resp.read.return_value = csv.encode('utf-8')
                    mock_resp.__enter__ = lambda s: s
                    mock_resp.__exit__ = MagicMock(return_value=False)
                    return mock_resp
            raise ValueError(f"Unexpected URL: {url}")
        
        with patch('urllib.request.urlopen', side_effect=mock_urlopen_side_effect):
            with patch('fetch_curve.fetch_move_index', return_value=(95.42, '2026-09-04')):
                result = fetch_all_curve_data()
        
        assert result['spreads']['10s30s']['value_bps'] == 30.0
        assert result['spreads']['10s30s']['value_pct'] == 0.3
    
    def test_10s30s_none_when_missing_dgs30(self):
        """10s30s should be None if DGS30 fetch fails."""
        mock_csvs = {
            'DGS10': """DATE,DGS10
2026-09-04,4.25""",
            'DGS30': """DATE,DGS30
""",
            'T10Y2Y': """DATE,T10Y2Y
2026-09-04,0.45""",
            'DGS2': """DATE,DGS2
2026-09-04,3.80""",
        }
        
        def mock_urlopen_side_effect(req, timeout=30):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            for series, csv in mock_csvs.items():
                if series in url:
                    mock_resp = MagicMock()
                    mock_resp.read.return_value = csv.encode('utf-8')
                    mock_resp.__enter__ = lambda s: s
                    mock_resp.__exit__ = MagicMock(return_value=False)
                    return mock_resp
            raise ValueError(f"Unexpected URL: {url}")
        
        with patch('urllib.request.urlopen', side_effect=mock_urlopen_side_effect):
            with patch('fetch_curve.fetch_move_index', return_value=(None, None)):
                result = fetch_all_curve_data()
        
        assert result['spreads']['10s30s']['value_bps'] is None


class TestHasAnyData:
    """Test has_any_data validation."""
    
    def test_has_data_with_2s10s(self):
        """Should return True if 2s10s has value."""
        data = {
            'spreads': {'2s10s': {'value_bps': 45.0}},
            'move_index': {'value': None}
        }
        assert has_any_data(data) is True
    
    def test_has_data_with_move_only(self):
        """Should return True if only MOVE has value."""
        data = {
            'spreads': {'2s10s': {'value_bps': None}, '10s30s': {'value_bps': None}},
            'move_index': {'value': 95.5}
        }
        assert has_any_data(data) is True
    
    def test_has_no_data_all_none(self):
        """Should return False if all values are None."""
        data = {
            'spreads': {'2s10s': {'value_bps': None}, '10s30s': {'value_bps': None}},
            'move_index': {'value': None}
        }
        assert has_any_data(data) is False
    
    def test_has_no_data_empty(self):
        """Should return False for empty data."""
        assert has_any_data({}) is False


class TestMergeCurveData:
    """Test fail-closed merge logic."""
    
    def test_merge_preserves_existing_on_none(self):
        """New None values should not overwrite existing good values."""
        existing = {
            'spreads': {
                '2s10s': {'value_bps': 45.0, 'observation_date': '2026-09-03'},
                '10s30s': {'value_bps': 30.0}
            },
            'move_index': {'value': 95.5}
        }
        new_data = {
            'last_updated': '2026-09-04T12:00:00',
            'spreads': {
                '2s10s': {'value_bps': None},
                '10s30s': {'value_bps': 32.0, 'observation_date': '2026-09-04'}
            },
            'move_index': {'value': None}
        }
        
        merged = merge_curve_data(existing, new_data)
        
        assert merged['spreads']['2s10s']['value_bps'] == 45.0
        assert merged['spreads']['10s30s']['value_bps'] == 32.0
        assert merged['move_index']['value'] == 95.5
    
    def test_merge_updates_with_new_values(self):
        """New valid values should update existing."""
        existing = {
            'spreads': {'2s10s': {'value_bps': 45.0}},
            'move_index': {'value': 95.5}
        }
        new_data = {
            'last_updated': '2026-09-04T12:00:00',
            'spreads': {
                '2s10s': {'value_bps': 48.0, 'observation_date': '2026-09-04'},
                '10s30s': {'value_bps': 32.0}
            },
            'move_index': {'value': 98.2, 'observation_date': '2026-09-04'}
        }
        
        merged = merge_curve_data(existing, new_data)
        
        assert merged['spreads']['2s10s']['value_bps'] == 48.0
        assert merged['spreads']['10s30s']['value_bps'] == 32.0
        assert merged['move_index']['value'] == 98.2
    
    def test_merge_empty_existing(self):
        """Merge into empty existing should work."""
        new_data = {
            'last_updated': '2026-09-04T12:00:00',
            'spreads': {'2s10s': {'value_bps': 45.0}},
            'move_index': {'value': 95.5}
        }
        
        merged = merge_curve_data({}, new_data)
        
        assert merged['spreads']['2s10s']['value_bps'] == 45.0
        assert merged['move_index']['value'] == 95.5


class TestStaleMarking:
    """Test stale data preservation."""
    
    def test_mark_stale_preserves_data(self):
        """mark_curve_stale should add stale metadata without overwriting data."""
        import fetch_curve
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "market_data.json"
            good_data = {
                'curve_data': {
                    'last_updated': '2026-09-03T10:00:00',
                    'spreads': {'2s10s': {'value_bps': 45.0}}
                },
                'data_fetch_status': {'curve_data': 'live'}
            }
            tmppath.write_text(json.dumps(good_data))
            
            original_path = fetch_curve.MARKET_DATA_FILE
            fetch_curve.MARKET_DATA_FILE = tmppath
            
            try:
                result = mark_curve_stale("Test error: network timeout")
                assert result is True
                
                updated = json.loads(tmppath.read_text())
                
                assert updated['curve_data']['spreads']['2s10s']['value_bps'] == 45.0
                assert updated['curve_data']['_stale'] is True
                assert 'network timeout' in updated['curve_data']['_stale_reason']
                assert updated['data_fetch_status']['curve_data'] == 'stale'
                
            finally:
                fetch_curve.MARKET_DATA_FILE = original_path
    
    def test_mark_stale_no_file(self):
        """mark_curve_stale should handle missing file gracefully."""
        import fetch_curve
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "nonexistent.json"
            
            original_path = fetch_curve.MARKET_DATA_FILE
            fetch_curve.MARKET_DATA_FILE = tmppath
            
            try:
                result = mark_curve_stale("Test error")
                assert result is False
            finally:
                fetch_curve.MARKET_DATA_FILE = original_path


def run_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [
        TestFREDParsing,
        TestMOVEParsing,
        TestSpreadComputation,
        TestHasAnyData,
        TestMergeCurveData,
        TestStaleMarking,
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
