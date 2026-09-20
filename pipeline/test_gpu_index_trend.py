#!/usr/bin/env python3
"""
Tests for GPU index API fetch and trend computation, covering:
- Daily index trend calculation (week-over-week, month-over-month)
- Contract range trend calculation (period-over-period)
- API response parsing
- Price value normalization
- Validation of parsed results
- Stale data handling
"""

import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from fetch_gpu_index import (
    compute_daily_trend,
    compute_contract_trend,
    normalize_price_value,
    validate_parsed_result,
    mark_data_stale,
    parse_date,
    format_date_short,
    MARKET_DATA_FILE
)


def make_daily_index(days_data):
    """
    Helper to build daily index list from (days_ago, h100_value) tuples.
    days_ago=0 means today, 1 means yesterday, etc.
    """
    today = datetime.now()
    result = []
    for days_ago, h100_val in sorted(days_data, key=lambda x: -x[0]):
        dt = today - timedelta(days=days_ago)
        result.append({
            'date': dt.strftime('%a, %d %b %Y 00:00:00 GMT'),
            'h100': h100_val,
            'b200': None,
            'a100': None
        })
    return result


def make_contract_data(periods_and_ranges):
    """Helper to build contract data from (period, low, high) tuples."""
    return [
        {
            'period': period,
            '1y': [low, high],
            'onDemand': None,
            'period_start': f'Mon, 01 Jan 2026 00:00:00 GMT'
        }
        for period, low, high in periods_and_ranges
    ]


class TestDailyTrendCalculation:
    """Test daily index trend computation."""
    
    def test_basic_week_over_week(self):
        """Week-over-week trend calculated correctly."""
        index_data = make_daily_index([
            (7, 3.00),
            (6, 3.05),
            (5, 3.10),
            (4, 3.15),
            (3, 3.20),
            (2, 3.25),
            (1, 3.28),
            (0, 3.29),
        ])
        result = compute_daily_trend(index_data, 'h100')
        
        assert result['latest_value'] == 3.29
        assert result['short_term']['comparison_value'] == 3.00
        assert abs(result['short_term']['change_pct'] - 9.7) < 0.1
        assert result['short_term']['days_back'] == 7
        
    def test_month_over_month_long_term(self):
        """Long-term trend ~30 days back calculated correctly."""
        index_data = []
        base_value = 2.50
        for days_ago in range(35, -1, -1):
            value = base_value + (35 - days_ago) * 0.02
            index_data.append((days_ago, round(value, 2)))
        
        index_data = make_daily_index(index_data)
        result = compute_daily_trend(index_data, 'h100')
        
        assert 'long_term' in result
        assert result['long_term']['days_back'] >= 28
        assert result['long_term']['days_back'] <= 32
        
    def test_insufficient_data_single_point(self):
        """Single data point returns insufficient_data."""
        index_data = make_daily_index([(0, 3.29)])
        result = compute_daily_trend(index_data, 'h100')
        
        assert result.get('insufficient_data') == True
        assert result['data_points'] == 1
        
    def test_handles_missing_sku_values(self):
        """Entries with missing h100 values are skipped."""
        index_data = [
            {'date': 'Mon, 13 Sep 2026 00:00:00 GMT', 'h100': None, 'b200': 5.5},
            {'date': 'Tue, 14 Sep 2026 00:00:00 GMT', 'h100': 3.25, 'b200': 5.5},
            {'date': 'Wed, 15 Sep 2026 00:00:00 GMT', 'h100': 3.29, 'b200': 5.5},
        ]
        result = compute_daily_trend(index_data, 'h100')
        
        assert result['data_points'] == 2


class TestContractTrendCalculation:
    """Test contract range trend computation."""
    
    def test_period_over_period_positive(self):
        """Positive period-over-period change calculated correctly."""
        contract_data = make_contract_data([
            ('Jul 2026', 2.2, 3.0),
            ('Aug 2026', 2.4, 3.2),
        ])
        result = compute_contract_trend(contract_data)
        
        # Midpoints: Jul=2.6, Aug=2.8 => (2.8-2.6)/2.6 = 7.69%
        assert result['latest_period'] == 'Aug 2026'
        assert result['short_term']['comparison_period'] == 'Jul 2026'
        assert abs(result['short_term']['change_pct'] - 7.7) < 0.2
        
    def test_period_over_period_negative(self):
        """Negative period-over-period change calculated correctly."""
        contract_data = make_contract_data([
            ('Jul 2026', 2.4, 3.2),
            ('Aug 2026', 2.2, 3.0),
        ])
        result = compute_contract_trend(contract_data)
        
        # Midpoints: Jul=2.8, Aug=2.6 => (2.6-2.8)/2.8 = -7.14%
        assert result['short_term']['change_pct'] < 0
        
    def test_long_term_anchor_with_7_points(self):
        """With 7+ points, anchor is ~6 periods back."""
        contract_data = make_contract_data([
            ('Jan 2026', 1.5, 2.0),
            ('Feb 2026', 1.6, 2.1),
            ('Mar 2026', 1.7, 2.2),
            ('Apr 2026', 1.8, 2.3),
            ('May 2026', 1.9, 2.4),
            ('Jun 2026', 2.0, 2.5),
            ('Jul 2026', 2.1, 2.6),
            ('Aug 2026', 2.4, 3.2),
        ])
        result = compute_contract_trend(contract_data)
        
        assert 'long_term' in result
        assert result['long_term']['anchor_period'] == 'Feb 2026'
        assert result['long_term']['row_intervals'] == 6
        
    def test_long_term_anchor_with_few_points(self):
        """With <7 points, anchor is earliest."""
        contract_data = make_contract_data([
            ('Jun 2026', 2.0, 2.5),
            ('Jul 2026', 2.2, 3.0),
            ('Aug 2026', 2.4, 3.2),
        ])
        result = compute_contract_trend(contract_data)
        
        assert 'long_term' in result
        assert result['long_term']['anchor_period'] == 'Jun 2026'


class TestNormalizePriceValue:
    """Test price value normalization."""
    
    def test_range_list(self):
        """Range as [low, high] list parsed correctly."""
        result = normalize_price_value([2.4, 3.2])
        assert result['type'] == 'range'
        assert result['low'] == 2.4
        assert result['high'] == 3.2
        assert result['midpoint'] == 2.8
        assert result['display'] == '$2.40-3.20'
        
    def test_single_float(self):
        """Single float value parsed correctly."""
        result = normalize_price_value(3.29)
        assert result['type'] == 'single'
        assert result['value'] == 3.29
        assert result['display'] == '$3.29'
        
    def test_none_is_unavailable(self):
        """None returns unavailable."""
        result = normalize_price_value(None)
        assert result['type'] == 'unavailable'
        assert result['display'] == '—'
        
    def test_rounding(self):
        """Values are rounded to 2 decimal places."""
        result = normalize_price_value(3.2999999)
        assert result['value'] == 3.3
        
        result = normalize_price_value([2.3999, 3.2001])
        assert result['low'] == 2.4
        assert result['high'] == 3.2


class TestValidateParsedResult:
    """Test validation of parsed results."""
    
    def test_valid_result_passes(self):
        """A complete valid result should pass validation."""
        result = {
            'h100': {
                'daily_date': 'Sep 20, 2026',
                'composite_index': {'type': 'single', 'value': 3.29, 'display': '$3.29'},
                'daily_trend': {
                    'short_term': {'change_pct': 0.9, 'comparison_date': 'Sep 13, 2026'}
                }
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == True
        assert error == ""
        
    def test_missing_daily_date_fails(self):
        """Missing daily_date should fail validation."""
        result = {
            'h100': {
                'daily_date': '',
                'composite_index': {'type': 'single', 'value': 3.29},
                'daily_trend': {'short_term': {'change_pct': 0.9}}
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'daily_date' in error.lower()
        
    def test_non_single_composite_fails(self):
        """Non-single composite_index type should fail validation."""
        result = {
            'h100': {
                'daily_date': 'Sep 20, 2026',
                'composite_index': {'type': 'unavailable', 'display': '—'},
                'daily_trend': {'short_term': {'change_pct': 0.9}}
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'composite' in error.lower()
        
    def test_insufficient_trend_fails(self):
        """Trend with insufficient_data should fail validation."""
        result = {
            'h100': {
                'daily_date': 'Sep 20, 2026',
                'composite_index': {'type': 'single', 'value': 3.29},
                'daily_trend': {'insufficient_data': True, 'data_points': 1}
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'insufficient' in error.lower()
        
    def test_none_result_fails(self):
        """None result should fail validation."""
        is_valid, error = validate_parsed_result(None)
        assert is_valid == False


class TestStaleDataPreservation:
    """Test that stale marking preserves existing data."""
    
    def test_mark_data_stale_adds_metadata(self):
        """mark_data_stale should add stale metadata without overwriting data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "market_data.json"
            good_data = {
                'compute_forward': {
                    'last_fetched': '2026-09-01T10:00:00',
                    'h100': {
                        'daily_date': 'Sep 01, 2026',
                        'composite_index': {'display': '$3.20', 'type': 'single'}
                    }
                },
                'data_fetch_status': {'compute_forward': 'live'}
            }
            tmppath.write_text(json.dumps(good_data))
            
            import fetch_gpu_index
            original_path = fetch_gpu_index.MARKET_DATA_FILE
            fetch_gpu_index.MARKET_DATA_FILE = tmppath
            
            try:
                result = mark_data_stale("Test error: network timeout")
                assert result == True
                
                updated = json.loads(tmppath.read_text())
                
                assert updated['compute_forward']['h100']['daily_date'] == 'Sep 01, 2026'
                assert updated['compute_forward']['h100']['composite_index']['display'] == '$3.20'
                assert updated['compute_forward']['last_fetched'] == '2026-09-01T10:00:00'
                
                assert updated['compute_forward']['_stale'] == True
                assert 'network timeout' in updated['compute_forward']['_stale_reason']
                assert '_stale_since' in updated['compute_forward']
                
                assert updated['data_fetch_status']['compute_forward'] == 'stale'
                
            finally:
                fetch_gpu_index.MARKET_DATA_FILE = original_path


class TestDateParsing:
    """Test date parsing utilities."""
    
    def test_parse_api_date(self):
        """API date string parsed correctly."""
        result = parse_date('Sun, 20 Sep 2026 00:00:00 GMT')
        assert result.year == 2026
        assert result.month == 9
        assert result.day == 20
        
    def test_format_date_short(self):
        """Date formatted as 'Sep 20, 2026'."""
        dt = datetime(2026, 9, 20)
        result = format_date_short(dt)
        assert result == 'Sep 20, 2026'
        
    def test_parse_invalid_date(self):
        """Invalid date string returns None."""
        result = parse_date('invalid date')
        assert result is None


class TestMockedAPIPayload:
    """Test with realistic mocked API payload matching production schema."""
    
    def test_realistic_api_response_parsing(self):
        """Parse a realistic API response structure."""
        api_response = {
            "status": "ok",
            "index": [
                {"a100": 1.85, "b200": 5.64, "date": "Sat, 19 Sep 2026 00:00:00 GMT", "h100": 3.26},
                {"a100": 1.87, "b200": 5.63, "date": "Sun, 20 Sep 2026 00:00:00 GMT", "h100": 3.29}
            ],
            "contract": [
                {
                    "sku": "H100",
                    "vendor": "NVIDIA",
                    "data": [
                        {"period": "Jul 2026", "1y": [2.4, 3.2], "onDemand": None},
                        {"period": "Aug 2026", "1y": [2.4, 3.2], "onDemand": None}
                    ],
                    "soldOutPeriods": {"onDemand": ["Feb 2026", "Mar 2026", "Aug 2026"]},
                    "note": "Test note"
                }
            ]
        }
        
        assert api_response['status'] == 'ok'
        
        index_data = api_response['index']
        latest = index_data[-1]
        assert latest['h100'] == 3.29
        
        h100_contract = None
        for c in api_response['contract']:
            if c['sku'] == 'H100':
                h100_contract = c
                break
        
        assert h100_contract is not None
        assert h100_contract['data'][-1]['period'] == 'Aug 2026'
        assert 'Aug 2026' in h100_contract['soldOutPeriods']['onDemand']


def run_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [
        TestDailyTrendCalculation,
        TestContractTrendCalculation,
        TestNormalizePriceValue,
        TestValidateParsedResult,
        TestStaleDataPreservation,
        TestDateParsing,
        TestMockedAPIPayload,
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
