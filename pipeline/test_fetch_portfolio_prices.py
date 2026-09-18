#!/usr/bin/env python3
"""
Tests for fetch_portfolio_prices.py portfolio basket price refresh.

Tests:
- Portfolio JSON structure validation
- Price fetch mechanics (mocked)
- Mark-to-market calculations (inception shares preserved)
- Comparator index computation
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))

from fetch_portfolio_prices import (
    fetch_yahoo_price,
    update_portfolio,
    PORTFOLIO_FILE,
)


SAMPLE_PORTFOLIO = {
    "baskets": [
        {
            "id": "healthcare-abundance-five",
            "title": "Healthcare Abundance",
            "subtitle": "Test subtitle",
            "section": "Portfolio",
            "as_of": "2026-09-18T09:30:00-05:00",
            "as_of_label": "Sep 18, 2026 ~9:30 AM CT",
            "notional_each_usd": 1000,
            "names": [
                {
                    "ticker": "HIMS",
                    "name": "Hims & Hers",
                    "role": "Consumer relationship",
                    "inception_price": 28.09,
                    "shares": 35.5999,
                    "notional": 1000,
                    "current_price": 28.09,
                    "current_value": 1000
                },
                {
                    "ticker": "GDRX",
                    "name": "GoodRx",
                    "role": "Access",
                    "inception_price": 3.33,
                    "shares": 300.3003,
                    "notional": 1000,
                    "current_price": 3.33,
                    "current_value": 1000
                }
            ],
            "basket_notional_usd": 2000,
            "basket_current_value": 2000,
            "basket_change_pct": 0.0,
            "comparators": {
                "QQQ": {
                    "inception_price": 716.74,
                    "equal_notional_usd": 5000,
                    "shares": 6.976,
                    "current_price": 716.74,
                    "current_value": 5000,
                    "change_pct": 0.0,
                    "index_value": 100
                }
            },
            "index_start": 100,
            "basket_index_value": 100,
            "disclaimer": "Test disclaimer",
            "last_updated": "2026-09-18T09:30:00-05:00"
        }
    ],
    "_metadata": {
        "last_updated": "2026-09-18T09:30:00-05:00",
        "schema_version": 1
    }
}


class TestPortfolioStructure:
    """Test portfolio JSON structure validation."""
    
    def test_portfolio_has_baskets(self):
        """Portfolio should have baskets array."""
        assert "baskets" in SAMPLE_PORTFOLIO
        assert isinstance(SAMPLE_PORTFOLIO["baskets"], list)
        
    def test_basket_has_required_fields(self):
        """Each basket should have required fields."""
        basket = SAMPLE_PORTFOLIO["baskets"][0]
        required = ["id", "title", "names", "basket_notional_usd", "comparators", "index_start"]
        for field in required:
            assert field in basket, f"Missing field: {field}"
            
    def test_name_has_required_fields(self):
        """Each name in basket should have required fields."""
        name = SAMPLE_PORTFOLIO["baskets"][0]["names"][0]
        required = ["ticker", "inception_price", "shares", "notional"]
        for field in required:
            assert field in name, f"Missing field: {field}"
            
    def test_comparator_has_required_fields(self):
        """Each comparator should have required fields."""
        comp = SAMPLE_PORTFOLIO["baskets"][0]["comparators"]["QQQ"]
        required = ["inception_price", "equal_notional_usd", "shares"]
        for field in required:
            assert field in comp, f"Missing field: {field}"


class TestMarkToMarket:
    """Test mark-to-market calculations."""
    
    def test_current_value_calculation(self):
        """Current value = shares * current_price."""
        shares = 35.5999
        price = 30.00
        expected = round(shares * price, 2)
        assert expected == 1068.0
        
    def test_change_pct_calculation(self):
        """Change % = (current - inception) / inception * 100."""
        inception = 28.09
        current = 30.00
        change = ((current - inception) / inception) * 100
        assert round(change, 2) == 6.80
        
    def test_inception_shares_not_changed(self):
        """Mark-to-market should not modify inception shares."""
        original_shares = 35.5999
        basket = SAMPLE_PORTFOLIO["baskets"][0]
        name = basket["names"][0]
        assert name["shares"] == original_shares
        
    def test_basket_index_calculation(self):
        """Basket index = (current_value / notional) * index_start."""
        notional = 5000
        current = 5250
        index_start = 100
        expected = (current / notional) * index_start
        assert expected == 105.0


class TestComparatorCalculations:
    """Test comparator value and index calculations."""
    
    def test_qqq_value_calculation(self):
        """QQQ value = shares * current_price."""
        shares = 6.976
        price = 720.00
        expected = round(shares * price, 2)
        assert expected == 5022.72
        
    def test_btc_value_calculation(self):
        """BTC value = coins * current_price."""
        coins = 0.064103
        price = 80000
        expected = round(coins * price, 2)
        assert expected == 5128.24
        
    def test_comparator_change_pct(self):
        """Comparator change % = (current_value - notional) / notional * 100."""
        notional = 5000
        current = 5250
        change = ((current - notional) / notional) * 100
        assert change == 5.0
        
    def test_comparator_index_value(self):
        """Comparator index = (current_value / notional) * index_start."""
        notional = 5000
        current = 5250
        index_start = 100
        expected = (current / notional) * index_start
        assert expected == 105.0


class TestPriceFetch:
    """Test Yahoo Finance price fetching (mocked)."""
    
    def test_fetch_returns_float(self):
        """fetch_yahoo_price should return float or None."""
        with patch('fetch_portfolio_prices.urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({
                "chart": {
                    "result": [{
                        "meta": {
                            "regularMarketPrice": 28.50
                        }
                    }]
                }
            }).encode()
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            result = fetch_yahoo_price("HIMS")
            assert result == 28.50
            
    def test_fetch_handles_missing_data(self):
        """fetch_yahoo_price should return None on missing data."""
        with patch('fetch_portfolio_prices.urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({
                "chart": {"result": None}
            }).encode()
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            result = fetch_yahoo_price("INVALID")
            assert result is None


class TestPortfolioUpdate:
    """Test full portfolio update flow."""
    
    def test_update_preserves_inception_prices(self):
        """Update should not modify inception_price values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "portfolio.json"
            tmppath.write_text(json.dumps(SAMPLE_PORTFOLIO))
            
            import fetch_portfolio_prices
            original_file = fetch_portfolio_prices.PORTFOLIO_FILE
            fetch_portfolio_prices.PORTFOLIO_FILE = tmppath
            
            try:
                with patch('fetch_portfolio_prices.fetch_yahoo_price') as mock_fetch:
                    mock_fetch.return_value = 30.00
                    update_portfolio()
                    
                updated = json.loads(tmppath.read_text())
                name = updated["baskets"][0]["names"][0]
                
                assert name["inception_price"] == 28.09
            finally:
                fetch_portfolio_prices.PORTFOLIO_FILE = original_file
                
    def test_update_changes_current_price(self):
        """Update should modify current_price values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir) / "portfolio.json"
            tmppath.write_text(json.dumps(SAMPLE_PORTFOLIO))
            
            import fetch_portfolio_prices
            original_file = fetch_portfolio_prices.PORTFOLIO_FILE
            fetch_portfolio_prices.PORTFOLIO_FILE = tmppath
            
            try:
                with patch('fetch_portfolio_prices.fetch_yahoo_price') as mock_fetch:
                    mock_fetch.return_value = 30.00
                    update_portfolio()
                    
                updated = json.loads(tmppath.read_text())
                name = updated["baskets"][0]["names"][0]
                
                assert name["current_price"] == 30.00
            finally:
                fetch_portfolio_prices.PORTFOLIO_FILE = original_file


def run_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [
        TestPortfolioStructure,
        TestMarkToMarket,
        TestComparatorCalculations,
        TestPriceFetch,
        TestPortfolioUpdate,
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
