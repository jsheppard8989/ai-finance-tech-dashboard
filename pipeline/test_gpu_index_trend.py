#!/usr/bin/env python3
"""
Tests for GPU index trend computation, focusing on:
- Dual-horizon calculation (short-term and long-term)
- Anchor selection rules (prefer ~6 periods back, fallback to earliest)
- Percentage calculation accuracy
- Graceful handling of insufficient history
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch_gpu_index import compute_trend, normalize_price_value


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
        """With ≥7 data points, anchor should be index -7 (6 periods back)."""
        # 8 periods: Oct, Nov, Dec, Jan, Feb, Mar, Apr (latest)
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
        """Large long-term move calculated correctly (the +41% case)."""
        # Simulating Oct 2025 → Apr 2026 with ~41% increase
        history = make_history([
            ('Oct 2025', 1.70),  # midpoint of $1.45-1.95
            ('Nov 2025', 1.80),
            ('Dec 2025', 1.90),
            ('Jan 2026', 2.00),
            ('Feb 2026', 2.10),
            ('Mar 2026', 2.20),
            ('Apr 2026', 2.40),  # midpoint of $2.10-2.70
        ])
        result = compute_trend(history)
        
        # Long-term: (2.40 - 1.70) / 1.70 * 100 = 41.17... → 41.2%
        assert result['long_term']['change_pct'] == 41.2
        
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
        TestPercentageCalculation,
        TestInsufficientHistory,
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
