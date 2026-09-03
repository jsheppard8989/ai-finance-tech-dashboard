#!/usr/bin/env python3
"""
Tests for GPU index trend computation, focusing on:
- Dual-horizon calculation (short-term and long-term)
- Anchor selection rules (prefer ~6 periods back, fallback to earliest)
- Percentage calculation accuracy
- Graceful handling of insufficient history
- Non-monthly history rows (1H 2023, Q1 2024, etc.)
- Zero/invalid anchor suppression
- Malformed/partial parse validation
- Stale data preservation
- Accurate row_intervals metadata
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch_gpu_index import (
    compute_trend, 
    normalize_price_value, 
    validate_parsed_result,
    mark_data_stale,
    MARKET_DATA_FILE
)


def make_history(periods_and_values):
    """Helper to build history list from (period, value) tuples."""
    return [
        {
            'period': period,
            '1y_contract': {
                'type': 'single',
                'value': value,
                'display': f'${value:.2f}'
            }
        }
        for period, value in periods_and_values
    ]


def make_range_history(periods_and_ranges):
    """Helper to build history with range values from (period, low, high) tuples."""
    return [
        {
            'period': period,
            '1y_contract': {
                'type': 'range',
                'low': low,
                'high': high,
                'midpoint': round((low + high) / 2, 2),
                'display': f'${low:.2f}-{high:.2f}'
            }
        }
        for period, low, high in periods_and_ranges
    ]


class TestAnchorSelection:
    """Test the deterministic anchor selection rule."""
    
    def test_anchor_with_7_plus_points_uses_index_minus_7(self):
        """With ≥7 data points, anchor should be index -7 (6 row intervals back)."""
        # 8 periods
        history = make_history([
            ('Jul 2025', 1.00),
            ('Aug 2025', 1.10),
            ('Sep 2025', 1.20),
            ('Oct 2025', 1.30),
            ('Nov 2025', 1.40),
            ('Dec 2025', 1.50),
            ('Jan 2026', 1.60),
            ('Feb 2026', 1.70),
        ])
        result = compute_trend(history)
        
        # Short-term: Feb vs Jan
        assert result['short_term']['comparison_period'] == 'Jan 2026'
        
        # Long-term: Feb vs Aug (index -7)
        assert result['long_term']['anchor_period'] == 'Aug 2025'
        
    def test_anchor_with_exactly_7_points_uses_index_minus_7(self):
        """With exactly 7 points, anchor should be index -7 = index 0."""
        history = make_history([
            ('Oct 2025', 1.00),
            ('Nov 2025', 1.10),
            ('Dec 2025', 1.20),
            ('Jan 2026', 1.30),
            ('Feb 2026', 1.40),
            ('Mar 2026', 1.50),
            ('Apr 2026', 1.60),
        ])
        result = compute_trend(history)
        
        # Long-term: Apr vs Oct (index -7 = index 0)
        assert result['long_term']['anchor_period'] == 'Oct 2025'
        
    def test_anchor_with_fewer_than_7_points_uses_earliest(self):
        """With <7 data points, anchor should be earliest (index 0)."""
        history = make_history([
            ('Jan 2026', 1.00),
            ('Feb 2026', 1.20),
            ('Mar 2026', 1.40),
            ('Apr 2026', 1.60),
        ])
        result = compute_trend(history)
        
        # Short-term: Apr vs Mar
        assert result['short_term']['comparison_period'] == 'Mar 2026'
        
        # Long-term: Apr vs Jan (earliest)
        assert result['long_term']['anchor_period'] == 'Jan 2026'
        
    def test_anchor_with_3_points_has_long_term(self):
        """With 3 points, long_term anchor differs from short_term comparison."""
        history = make_history([
            ('Feb 2026', 1.00),
            ('Mar 2026', 1.10),
            ('Apr 2026', 1.20),
        ])
        result = compute_trend(history)
        
        # Short-term: Apr vs Mar
        assert result['short_term']['comparison_period'] == 'Mar 2026'
        
        # Long-term: Apr vs Feb (earliest, different from Mar)
        assert result['long_term']['anchor_period'] == 'Feb 2026'
        
    def test_anchor_with_2_points_no_long_term(self):
        """With only 2 points, no long_term (anchor would equal short_term comparison)."""
        history = make_history([
            ('Mar 2026', 1.00),
            ('Apr 2026', 1.10),
        ])
        result = compute_trend(history)
        
        assert result['short_term']['comparison_period'] == 'Mar 2026'
        assert 'long_term' not in result


class TestRowIntervalsMetadata:
    """Test that row_intervals accurately reflects the selected anchor distance."""
    
    def test_row_intervals_with_7_points(self):
        """With 7 points, anchor at index -7 means 6 row intervals to latest."""
        history = make_history([
            ('Oct 2025', 1.70),
            ('Nov 2025', 1.725),
            ('Dec 2025', 1.725),
            ('Jan 2026', 1.775),
            ('Feb 2026', 2.075),
            ('Mar 2026', 2.35),
            ('Apr 2026', 2.40),
        ])
        result = compute_trend(history)
        
        # Oct→Apr is 6 row intervals (not periods_back=10!)
        assert result['long_term']['row_intervals'] == 6
        assert result['long_term']['anchor_period'] == 'Oct 2025'
        
    def test_row_intervals_with_18_points(self):
        """With 18 points, anchor at index -7 means 6 row intervals."""
        # Build 18 points (matching real data structure)
        history = make_history([
            ('1H 2023', 1.00), ('2H 2023', 1.05), ('Q1 2024', 1.10), ('Q2 2024', 1.15),
            ('Q3 2024', 1.20), ('Q4 2024', 1.25), ('May 2025', 1.30), ('Jun 2025', 1.35),
            ('Jul 2025', 1.40), ('Aug 2025', 1.45), ('Sep 2025', 1.50),
            ('Oct 2025', 1.70),  # This is index -7 (index 11 of 18)
            ('Nov 2025', 1.725),
            ('Dec 2025', 1.725),
            ('Jan 2026', 1.775),
            ('Feb 2026', 2.075),
            ('Mar 2026', 2.35),
            ('Apr 2026', 2.40),
        ])
        result = compute_trend(history)
        
        # Anchor is at index -7, which means 6 intervals to latest
        assert result['long_term']['row_intervals'] == 6
        assert result['long_term']['anchor_period'] == 'Oct 2025'
        
    def test_row_intervals_with_4_points_uses_earliest(self):
        """With <7 points, anchor is earliest (index 0), row_intervals = n-1."""
        history = make_history([
            ('Jan 2026', 1.00),
            ('Feb 2026', 1.20),
            ('Mar 2026', 1.40),
            ('Apr 2026', 1.60),
        ])
        result = compute_trend(history)
        
        # Anchor is at index 0, latest is index 3, so 3 row intervals
        assert result['long_term']['row_intervals'] == 3
        assert result['long_term']['anchor_period'] == 'Jan 2026'


class TestNonMonthlyHistory:
    """Test handling of non-monthly periods (1H 2023, Q1 2024, etc.)."""
    
    def test_mixed_period_formats(self):
        """History with half-years, quarters, and months should work correctly."""
        history = make_history([
            ('1H 2023', 1.00),
            ('2H 2023', 1.10),
            ('Q1 2024', 1.20),
            ('Q2 2024', 1.30),
            ('Q3 2024', 1.40),
            ('Q4 2024', 1.50),
            ('Jan 2025', 1.60),
            ('Feb 2025', 1.70),
        ])
        result = compute_trend(history)
        
        # Should compute trend without assuming calendar intervals
        assert result['short_term']['comparison_period'] == 'Jan 2025'
        assert result['long_term']['anchor_period'] == '2H 2023'  # index -7
        assert result['long_term']['row_intervals'] == 6
        
    def test_quarterly_periods_reach_into_old_data(self):
        """Ensure anchor selection works when reaching into quarterly/half-year data."""
        # Real-world structure: half-years, then quarters, then monthly
        history = make_history([
            ('1H 2023', 0.80),
            ('2H 2023', 0.90),
            ('Q1 2024', 1.00),
            ('Q2 2024', 1.10),
            ('Q3 2024', 1.20),
            ('Q4 2024', 1.30),
            ('May 2025', 1.40),
            ('Jun 2025', 1.50),
            ('Jul 2025', 1.55),
            ('Aug 2025', 1.60),
            ('Sep 2025', 1.65),
            ('Oct 2025', 1.70),
            ('Nov 2025', 1.725),
            ('Dec 2025', 1.725),
            ('Jan 2026', 1.775),
            ('Feb 2026', 2.075),
            ('Mar 2026', 2.35),
            ('Apr 2026', 2.40),
        ])
        result = compute_trend(history)
        
        # With 18 points, anchor is index -7 = Oct 2025
        assert result['long_term']['anchor_period'] == 'Oct 2025'
        assert result['long_term']['row_intervals'] == 6
        
        # Verify the actual percentage calculation matches ground truth
        # Oct 2025: 1.70, Apr 2026: 2.40 => (2.40-1.70)/1.70 = 41.17...%
        assert result['long_term']['change_pct'] == 41.2


class TestPercentageCalculation:
    """Test percentage calculation accuracy with rounding."""
    
    def test_short_term_percentage_positive(self):
        """Positive short-term change calculated correctly."""
        history = make_history([
            ('Mar 2026', 2.35),
            ('Apr 2026', 2.40),
        ])
        result = compute_trend(history)
        
        # (2.40 - 2.35) / 2.35 * 100 = 2.127... → rounds to 2.1
        assert result['short_term']['change_pct'] == 2.1
        
    def test_short_term_percentage_negative(self):
        """Negative short-term change calculated correctly."""
        history = make_history([
            ('Mar 2026', 2.50),
            ('Apr 2026', 2.35),
        ])
        result = compute_trend(history)
        
        # (2.35 - 2.50) / 2.50 * 100 = -6.0
        assert result['short_term']['change_pct'] == -6.0
        
    def test_long_term_percentage_large_move(self):
        """Large long-term move calculated correctly (the +41.2% case)."""
        # Ground truth data from data owner
        history = make_range_history([
            ('Oct 2025', 1.45, 1.95),  # midpoint = 1.70
            ('Nov 2025', 1.45, 2.00),  # midpoint = 1.725
            ('Dec 2025', 1.45, 2.00),  # midpoint = 1.725
            ('Jan 2026', 1.50, 2.05),  # midpoint = 1.775
            ('Feb 2026', 1.80, 2.35),  # midpoint = 2.075
            ('Mar 2026', 2.00, 2.70),  # midpoint = 2.35
            ('Apr 2026', 2.10, 2.70),  # midpoint = 2.40
        ])
        result = compute_trend(history)
        
        # Short-term: (2.40 - 2.35) / 2.35 * 100 = 2.127... → 2.1%
        assert result['short_term']['change_pct'] == 2.1
        
        # Long-term: (2.40 - 1.70) / 1.70 * 100 = 41.17... → 41.2%
        assert result['long_term']['change_pct'] == 41.2
        assert result['long_term']['anchor_period'] == 'Oct 2025'
        assert result['long_term']['row_intervals'] == 6
        
    def test_range_values_use_midpoint(self):
        """Range values use midpoint for calculations."""
        history = make_range_history([
            ('Mar 2026', 2.00, 2.70),  # midpoint = 2.35
            ('Apr 2026', 2.10, 2.70),  # midpoint = 2.40
        ])
        result = compute_trend(history)
        
        assert result['latest_value'] == 2.4
        assert result['short_term']['comparison_value'] == 2.35
        
    def test_values_rounded_to_2_decimals(self):
        """Values are rounded to 2 decimal places to avoid float noise."""
        history = make_range_history([
            ('Mar 2026', 2.00, 2.70),  # midpoint = 2.35
            ('Apr 2026', 2.10, 2.70),  # midpoint = 2.4 (not 2.4000000000000004)
        ])
        result = compute_trend(history)
        
        # Should be clean 2.4, not 2.4000000000000004
        assert result['latest_value'] == 2.4
        assert str(result['latest_value']) == '2.4'


class TestZeroAnchorSuppression:
    """Test that zero/invalid anchors don't produce invalid percentages."""
    
    def test_zero_anchor_value_suppresses_long_term(self):
        """Zero anchor value should suppress long_term entirely."""
        history = make_history([
            ('Jan 2026', 0.0),   # Zero anchor - invalid!
            ('Feb 2026', 1.00),
            ('Mar 2026', 1.50),
            ('Apr 2026', 2.00),
        ])
        result = compute_trend(history)
        
        # Short-term should work (Mar→Apr, both positive)
        assert result['short_term']['comparison_period'] == 'Mar 2026'
        
        # Long-term should be OMITTED because anchor is zero
        assert 'long_term' not in result
        
    def test_negative_anchor_value_suppresses_long_term(self):
        """Negative anchor value should suppress long_term entirely."""
        history = make_history([
            ('Jan 2026', -1.0),  # Negative anchor - invalid!
            ('Feb 2026', 1.00),
            ('Mar 2026', 1.50),
            ('Apr 2026', 2.00),
        ])
        result = compute_trend(history)
        
        # Long-term should be OMITTED because anchor is negative
        assert 'long_term' not in result
        
    def test_zero_previous_value_returns_insufficient_data(self):
        """Zero previous value should return insufficient_data (can't compute short_term)."""
        history = make_history([
            ('Mar 2026', 0.0),   # Zero - can't be comparison for short-term
            ('Apr 2026', 2.00),
        ])
        result = compute_trend(history)
        
        assert result.get('insufficient_data') == True
        assert 'previous period value is zero' in result.get('reason', '')


class TestInsufficientHistory:
    """Test graceful handling when history is insufficient."""
    
    def test_empty_history(self):
        """Empty history returns insufficient_data flag."""
        result = compute_trend([])
        assert result.get('insufficient_data') == True
        assert result['data_points'] == 0
        
    def test_single_point(self):
        """Single point returns insufficient_data flag."""
        history = make_history([('Apr 2026', 2.40)])
        result = compute_trend(history)
        
        assert result.get('insufficient_data') == True
        assert result['data_points'] == 1
        
    def test_missing_field_skipped(self):
        """History entries missing the field are skipped."""
        history = [
            {'period': 'Feb 2026'},  # missing 1y_contract
            {'period': 'Mar 2026', '1y_contract': {'type': 'single', 'value': 2.35, 'display': '$2.35'}},
            {'period': 'Apr 2026', '1y_contract': {'type': 'single', 'value': 2.40, 'display': '$2.40'}},
        ]
        result = compute_trend(history)
        
        # Only 2 valid points
        assert result['data_points'] == 2
        assert result['short_term']['comparison_period'] == 'Mar 2026'
        
    def test_unavailable_type_skipped(self):
        """History entries with type 'unavailable' are skipped."""
        history = [
            {'period': 'Feb 2026', '1y_contract': {'type': 'unavailable', 'display': '—'}},
            {'period': 'Mar 2026', '1y_contract': {'type': 'single', 'value': 2.35, 'display': '$2.35'}},
            {'period': 'Apr 2026', '1y_contract': {'type': 'single', 'value': 2.40, 'display': '$2.40'}},
        ]
        result = compute_trend(history)
        
        assert result['data_points'] == 2


class TestValidateParsedResult:
    """Test validation of parsed results to prevent partial overwrites."""
    
    def test_valid_result_passes(self):
        """A complete valid result should pass validation."""
        result = {
            'h100': {
                'period': 'Apr 2026',
                '1y_contract': {'type': 'range', 'low': 2.10, 'high': 2.70, 'display': '$2.10-2.70'},
                'trend': {
                    'short_term': {'change_pct': 2.1, 'comparison_period': 'Mar 2026'}
                }
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == True
        assert error == ""
        
    def test_missing_period_fails(self):
        """Missing period should fail validation."""
        result = {
            'h100': {
                'period': '',  # Empty period
                '1y_contract': {'type': 'range', 'display': '$2.10-2.70'},
                'trend': {'short_term': {'change_pct': 2.1}}
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'period' in error.lower()
        
    def test_unknown_period_fails(self):
        """'unknown' period should fail validation."""
        result = {
            'h100': {
                'period': 'unknown',
                '1y_contract': {'type': 'range', 'display': '$2.10-2.70'},
                'trend': {'short_term': {'change_pct': 2.1}}
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'unknown' in error.lower()
        
    def test_unavailable_contract_type_fails(self):
        """Unavailable 1y_contract type should fail validation."""
        result = {
            'h100': {
                'period': 'Apr 2026',
                '1y_contract': {'type': 'unavailable', 'display': '—'},
                'trend': {'short_term': {'change_pct': 2.1}}
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'contract' in error.lower()
        
    def test_insufficient_trend_fails(self):
        """Trend with insufficient_data should fail validation."""
        result = {
            'h100': {
                'period': 'Apr 2026',
                '1y_contract': {'type': 'range', 'display': '$2.10-2.70'},
                'trend': {'insufficient_data': True, 'data_points': 1}
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'insufficient' in error.lower()
        
    def test_missing_short_term_fails(self):
        """Missing short_term in trend should fail validation."""
        result = {
            'h100': {
                'period': 'Apr 2026',
                '1y_contract': {'type': 'range', 'display': '$2.10-2.70'},
                'trend': {'data_points': 5}  # No short_term
            }
        }
        is_valid, error = validate_parsed_result(result)
        assert is_valid == False
        assert 'short_term' in error.lower()
        
    def test_none_result_fails(self):
        """None result should fail validation."""
        is_valid, error = validate_parsed_result(None)
        assert is_valid == False


class TestStaleDataPreservation:
    """Test that stale marking preserves existing data."""
    
    def test_mark_data_stale_adds_metadata(self):
        """mark_data_stale should add stale metadata without overwriting data."""
        import tempfile
        import shutil
        
        # Create a temp directory and market_data.json with good data
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "market_data.json"
            good_data = {
                'compute_forward': {
                    'last_fetched': '2026-09-01T10:00:00',
                    'h100': {
                        'period': 'Apr 2026',
                        '1y_contract': {'display': '$2.10-2.70', 'type': 'range'}
                    }
                },
                'data_fetch_status': {'compute_forward': 'live'}
            }
            tmppath.write_text(json.dumps(good_data))
            
            # Monkey-patch MARKET_DATA_FILE for this test
            import fetch_gpu_index
            original_path = fetch_gpu_index.MARKET_DATA_FILE
            fetch_gpu_index.MARKET_DATA_FILE = tmppath
            
            try:
                # Mark as stale
                result = mark_data_stale("Test error: network timeout")
                assert result == True
                
                # Read back and verify
                updated = json.loads(tmppath.read_text())
                
                # Original data preserved
                assert updated['compute_forward']['h100']['period'] == 'Apr 2026'
                assert updated['compute_forward']['h100']['1y_contract']['display'] == '$2.10-2.70'
                assert updated['compute_forward']['last_fetched'] == '2026-09-01T10:00:00'
                
                # Stale metadata added
                assert updated['compute_forward']['_stale'] == True
                assert 'network timeout' in updated['compute_forward']['_stale_reason']
                assert '_stale_since' in updated['compute_forward']
                
                # Status updated
                assert updated['data_fetch_status']['compute_forward'] == 'stale'
                
            finally:
                fetch_gpu_index.MARKET_DATA_FILE = original_path


class TestNormalizePriceValue:
    """Test price value normalization for edge cases."""
    
    def test_sold_out(self):
        """'Sold Out' is recognized."""
        result = normalize_price_value('Sold Out')
        assert result['type'] == 'sold_out'
        assert result['display'] == 'Sold Out'
        
    def test_sold_out_with_symbol(self):
        """'✕ Sold Out' is recognized."""
        result = normalize_price_value('✕ Sold Out')
        assert result['type'] == 'sold_out'
        
    def test_range_with_dollar_signs(self):
        """Range with dollar signs parsed correctly."""
        result = normalize_price_value('$2.10-$2.70')
        assert result['type'] == 'range'
        assert result['low'] == 2.10
        assert result['high'] == 2.70
        assert result['midpoint'] == 2.40
        
    def test_range_without_dollar_signs(self):
        """Range without dollar signs parsed correctly."""
        result = normalize_price_value('2.10-2.70')
        assert result['type'] == 'range'
        assert result['low'] == 2.10
        assert result['high'] == 2.70
        
    def test_single_value(self):
        """Single value parsed correctly."""
        result = normalize_price_value('$2.82')
        assert result['type'] == 'single'
        assert result['value'] == 2.82
        
    def test_dash_is_unavailable(self):
        """Dash character means unavailable."""
        result = normalize_price_value('—')
        assert result['type'] == 'unavailable'
        
    def test_em_dash_is_unavailable(self):
        """Em-dash (common in real data) means unavailable."""
        result = normalize_price_value('–')
        assert result['type'] == 'unavailable'


class TestLegacyCompatibility:
    """Test that legacy fields are still present for backward compatibility."""
    
    def test_legacy_fields_present(self):
        """Legacy change_pct and comparison_period at top level."""
        history = make_history([
            ('Mar 2026', 2.35),
            ('Apr 2026', 2.40),
        ])
        result = compute_trend(history)
        
        # Legacy fields at top level (same as short_term)
        assert 'change_pct' in result
        assert 'comparison_period' in result
        assert result['change_pct'] == result['short_term']['change_pct']
        assert result['comparison_period'] == result['short_term']['comparison_period']


def run_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [
        TestAnchorSelection,
        TestRowIntervalsMetadata,
        TestNonMonthlyHistory,
        TestPercentageCalculation,
        TestZeroAnchorSuppression,
        TestInsufficientHistory,
        TestValidateParsedResult,
        TestStaleDataPreservation,
        TestNormalizePriceValue,
        TestLegacyCompatibility,
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
