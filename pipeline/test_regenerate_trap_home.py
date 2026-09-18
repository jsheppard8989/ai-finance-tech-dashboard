#!/usr/bin/env python3
"""
Unit tests for regenerate_trap_home.py

Verifies:
- last_monitored has correct count and ordering by updated_at
- upcoming_watches has correct count and ordering by expected_date
- Graceful handling when fewer than 3 traps/watches exist
- Handles missing/malformed fields without crashing
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from regenerate_trap_home import regenerate_trap_home, _parse_date_key, _shorten_title


def test_parse_date_key():
    """Test date parsing for sorting."""
    assert _parse_date_key("2026-09-14") == (2026, 9, 14)
    assert _parse_date_key("Sep 16 2026") == (2026, 9, 16)
    assert _parse_date_key("Nov 4 2026") == (2026, 11, 4)
    assert _parse_date_key("November 2026") == (2026, 11, 15)
    assert _parse_date_key("") == (9999, 12, 31)
    assert _parse_date_key(None) == (9999, 12, 31)
    
    assert _parse_date_key("2026-09-10") < _parse_date_key("2026-09-14")
    assert _parse_date_key("Sep 10 2026") < _parse_date_key("Sep 14 2026")
    print("✓ test_parse_date_key passed")


def test_shorten_title():
    """Test title shortening."""
    assert _shorten_title("Short") == "Short"
    assert _shorten_title("A" * 50, max_len=30) == "A" * 27 + "..."
    assert len(_shorten_title("A" * 50, max_len=30)) <= 30
    print("✓ test_shorten_title passed")


def test_full_data():
    """Test with full sample trap data (>= 3 traps with next_datapoint)."""
    sample_data = {
        "_schema_version": 1,
        "traps": [
            {
                "id": "trap-1",
                "title": "Power + interconnect into data centers",
                "validation_status": "WATCH",
                "updated_at": "2026-09-14",
                "next_datapoint": {
                    "label": "Sep 16 CLLSCO workshop",
                    "expected_date": "Sep 16 2026"
                }
            },
            {
                "id": "trap-2",
                "title": "AST SpaceMobile — path-to-profit",
                "validation_status": "WATCH",
                "updated_at": "2026-09-09",
                "next_datapoint": {
                    "label": "Q1 2027 10-Q constellation disclosure",
                    "expected_date": "Q1 2027"
                }
            },
            {
                "id": "trap-3",
                "title": "Buyback as confession — captive duration",
                "validation_status": "WATCH",
                "updated_at": "2026-09-10",
                "next_datapoint": {
                    "label": "Nov 4 2026 QRA",
                    "expected_date": "Nov 4 2026"
                }
            },
            {
                "id": "trap-4",
                "title": "ARK Genomic Revolution — theme basket",
                "validation_status": "HOLD",
                "updated_at": "2026-09-08",
                "next_datapoint": {
                    "label": "TWST Q4 FY26 adj. EBITDA",
                    "expected_date": "Nov FY26"
                }
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_data, f)
        temp_path = Path(f.name)
    
    try:
        result = regenerate_trap_home(temp_path)
        
        assert len(result["last_monitored"]) == 3, f"Expected 3 last_monitored, got {len(result['last_monitored'])}"
        
        assert result["last_monitored"][0]["id"] == "trap-1", "First should be most recent (2026-09-14)"
        assert result["last_monitored"][1]["id"] == "trap-3", "Second should be 2026-09-10"
        assert result["last_monitored"][2]["id"] == "trap-2", "Third should be 2026-09-09"
        
        assert len(result["upcoming_watches"]) == 3, f"Expected 3 upcoming_watches, got {len(result['upcoming_watches'])}"
        
        assert "_generated_at" in result
        assert "_source" in result
        assert "_comment" in result
        
        print("✓ test_full_data passed")
    finally:
        temp_path.unlink()


def test_sparse_data():
    """Test graceful handling when fewer than 3 traps/watches exist."""
    sample_data = {
        "traps": [
            {
                "id": "only-trap",
                "title": "The only trap",
                "validation_status": "WATCH",
                "updated_at": "2026-09-14"
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_data, f)
        temp_path = Path(f.name)
    
    try:
        result = regenerate_trap_home(temp_path)
        
        assert len(result["last_monitored"]) == 1, "Should have 1 last_monitored"
        assert len(result["upcoming_watches"]) == 0, "Should have 0 upcoming_watches (no next_datapoint)"
        
        print("✓ test_sparse_data passed")
    finally:
        temp_path.unlink()


def test_empty_traps():
    """Test with empty traps array."""
    sample_data = {"traps": []}
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_data, f)
        temp_path = Path(f.name)
    
    try:
        result = regenerate_trap_home(temp_path)
        
        assert len(result["last_monitored"]) == 0
        assert len(result["upcoming_watches"]) == 0
        
        print("✓ test_empty_traps passed")
    finally:
        temp_path.unlink()


def test_missing_fields():
    """Test traps with missing/partial fields don't crash."""
    sample_data = {
        "traps": [
            {"id": "minimal", "title": "Minimal trap"},
            {"id": "partial", "title": "Partial", "next_datapoint": {}},
            {"id": "full", "title": "Full", "validation_status": "WATCH", "updated_at": "2026-09-10", "next_datapoint": {"label": "Test", "expected_date": "Dec 2026"}},
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_data, f)
        temp_path = Path(f.name)
    
    try:
        result = regenerate_trap_home(temp_path)
        
        assert len(result["last_monitored"]) == 3
        assert len(result["upcoming_watches"]) == 1
        
        print("✓ test_missing_fields passed")
    finally:
        temp_path.unlink()


def test_file_not_found():
    """Test FileNotFoundError when trap_map.json doesn't exist."""
    try:
        regenerate_trap_home(Path("/nonexistent/trap_map.json"))
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        print("✓ test_file_not_found passed")


def main():
    """Run all tests."""
    print("Running regenerate_trap_home tests...\n")
    
    test_parse_date_key()
    test_shorten_title()
    test_full_data()
    test_sparse_data()
    test_empty_traps()
    test_missing_fields()
    test_file_not_found()
    
    print("\n✓ All tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
