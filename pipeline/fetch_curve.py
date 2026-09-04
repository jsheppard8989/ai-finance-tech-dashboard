#!/usr/bin/env python3
"""
Fetch yield curve data: spreads, levels, and MOVE volatility index.

Sources:
- FRED (Federal Reserve Economic Data): Treasury yields and spreads
  - T10Y2Y: 10-Year minus 2-Year spread (2s10s) - direct series
  - DGS2, DGS10, DGS30: Treasury constant maturity rates
  - 10s30s computed as DGS30 - DGS10
- Yahoo Finance: ^MOVE (ICE BofA MOVE Index - bond volatility)

FRED allows CSV fetches without an API key for basic series. Optional FRED_API_KEY
from environment enables higher rate limits and JSON responses.

FAIL-CLOSED: On fetch failure, preserve prior good values or leave nulls.
Never invent numbers. The UI shows "Coming soon" when values are null.
"""

import json
import os
import re
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from workspace_paths import SITE_DATA_DIR

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"

FRED_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

FRED_SERIES = {
    "T10Y2Y": "2s10s spread (direct)",
    "DGS2": "2-Year Treasury",
    "DGS10": "10-Year Treasury",
    "DGS30": "30-Year Treasury",
}


def fetch_fred_series(series_id: str, api_key: Optional[str] = None) -> Tuple[Optional[float], Optional[str]]:
    """
    Fetch the latest value for a FRED series.
    Returns (value, observation_date) or (None, None) on failure.
    
    Uses CSV endpoint (no key required for basic usage).
    """
    try:
        url = f"{FRED_BASE_URL}?id={series_id}"
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read().decode('utf-8')
        
        lines = content.strip().split('\n')
        if len(lines) < 2:
            print(f"  ✗ FRED {series_id}: No data rows in response")
            return None, None
        
        latest_value = None
        latest_date = None
        for line in reversed(lines[1:]):
            parts = line.strip().split(',')
            if len(parts) >= 2:
                date_str = parts[0].strip()
                value_str = parts[1].strip()
                if value_str and value_str != '.' and value_str != '':
                    try:
                        latest_value = float(value_str)
                        latest_date = date_str
                        break
                    except ValueError:
                        continue
        
        if latest_value is not None:
            print(f"  ✓ FRED {series_id}: {latest_value:.3f} (as of {latest_date})")
            return latest_value, latest_date
        else:
            print(f"  ✗ FRED {series_id}: No valid values found")
            return None, None
            
    except Exception as e:
        print(f"  ✗ FRED {series_id} fetch error: {e}")
        return None, None


def fetch_move_index() -> Tuple[Optional[float], Optional[str]]:
    """
    Fetch MOVE Index (^MOVE) from Yahoo Finance.
    Returns (value, observation_date) or (None, None) on failure.
    """
    try:
        url = f"{YAHOO_CHART_URL}/^MOVE?interval=1d&range=5d"
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
        
        if not data.get('chart', {}).get('result'):
            print("  ✗ Yahoo ^MOVE: No result in response")
            return None, None
        
        result = data['chart']['result'][0]
        meta = result.get('meta', {})
        
        current_price = meta.get('regularMarketPrice') or meta.get('previousClose')
        
        if current_price is not None:
            trade_time = meta.get('regularMarketTime')
            if trade_time:
                obs_date = datetime.fromtimestamp(trade_time).strftime('%Y-%m-%d')
            else:
                obs_date = datetime.now().strftime('%Y-%m-%d')
            
            current_price = round(current_price, 2)
            print(f"  ✓ Yahoo ^MOVE: {current_price:.2f} (as of {obs_date})")
            return current_price, obs_date
        else:
            print("  ✗ Yahoo ^MOVE: No price found")
            return None, None
            
    except Exception as e:
        print(f"  ✗ Yahoo ^MOVE fetch error: {e}")
        return None, None


def fetch_all_curve_data() -> Dict[str, Any]:
    """
    Fetch all curve data: spreads, levels, MOVE.
    Returns structured data for curve_data section.
    """
    print("\nFetching FRED series...")
    
    api_key = os.environ.get('FRED_API_KEY', '').strip() or None
    if api_key:
        print("  (Using FRED_API_KEY from environment)")
    
    t10y2y, t10y2y_date = fetch_fred_series("T10Y2Y", api_key)
    dgs2, dgs2_date = fetch_fred_series("DGS2", api_key)
    dgs10, dgs10_date = fetch_fred_series("DGS10", api_key)
    dgs30, dgs30_date = fetch_fred_series("DGS30", api_key)
    
    print("\nFetching MOVE Index...")
    move_value, move_date = fetch_move_index()
    
    spread_10s30s = None
    spread_10s30s_date = None
    if dgs10 is not None and dgs30 is not None:
        spread_10s30s = round(dgs30 - dgs10, 3)
        spread_10s30s_date = dgs30_date or dgs10_date
        print(f"  ✓ Computed 10s30s: {spread_10s30s:.3f}% ({spread_10s30s * 100:.1f}bp)")
    
    result = {
        "last_updated": datetime.now().isoformat(),
        "spreads": {
            "2s10s": {
                "value_bps": round(t10y2y * 100, 1) if t10y2y is not None else None,
                "value_pct": round(t10y2y, 3) if t10y2y is not None else None,
                "observation_date": t10y2y_date,
                "fred_series": "T10Y2Y",
            },
            "10s30s": {
                "value_bps": round(spread_10s30s * 100, 1) if spread_10s30s is not None else None,
                "value_pct": round(spread_10s30s, 3) if spread_10s30s is not None else None,
                "observation_date": spread_10s30s_date,
                "calculation": "DGS30 - DGS10",
            },
        },
        "levels": {
            "2y": {
                "value": round(dgs2, 3) if dgs2 is not None else None,
                "observation_date": dgs2_date,
                "fred_series": "DGS2",
            },
            "10y": {
                "value": round(dgs10, 3) if dgs10 is not None else None,
                "observation_date": dgs10_date,
                "fred_series": "DGS10",
            },
            "30y": {
                "value": round(dgs30, 3) if dgs30 is not None else None,
                "observation_date": dgs30_date,
                "fred_series": "DGS30",
            },
        },
        "move_index": {
            "value": move_value,
            "observation_date": move_date,
            "yahoo_symbol": "^MOVE",
        },
    }
    
    return result


def has_any_data(curve_data: Dict[str, Any]) -> bool:
    """Check if any meaningful data was fetched."""
    spreads = curve_data.get("spreads", {})
    move = curve_data.get("move_index", {})
    
    has_2s10s = spreads.get("2s10s", {}).get("value_bps") is not None
    has_10s30s = spreads.get("10s30s", {}).get("value_bps") is not None
    has_move = move.get("value") is not None
    
    return has_2s10s or has_10s30s or has_move


def merge_curve_data(existing: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge new curve data into existing, preserving values on partial fetch failure.
    Fail-closed: never overwrite good data with None.
    """
    if not existing:
        existing = {}
    
    merged = dict(existing)
    merged["last_updated"] = new_data.get("last_updated")
    
    for spread_key in ["2s10s", "10s30s"]:
        new_spread = new_data.get("spreads", {}).get(spread_key, {})
        if new_spread.get("value_bps") is not None:
            if "spreads" not in merged:
                merged["spreads"] = {}
            if spread_key not in merged["spreads"]:
                merged["spreads"][spread_key] = {}
            merged["spreads"][spread_key]["value_bps"] = new_spread["value_bps"]
            merged["spreads"][spread_key]["value_pct"] = new_spread.get("value_pct")
            merged["spreads"][spread_key]["observation_date"] = new_spread.get("observation_date")
    
    for level_key in ["2y", "10y", "30y"]:
        new_level = new_data.get("levels", {}).get(level_key, {})
        if new_level.get("value") is not None:
            if "levels" not in merged:
                merged["levels"] = {}
            if level_key not in merged["levels"]:
                merged["levels"][level_key] = {}
            merged["levels"][level_key]["value"] = new_level["value"]
            merged["levels"][level_key]["observation_date"] = new_level.get("observation_date")
    
    new_move = new_data.get("move_index", {})
    if new_move.get("value") is not None:
        if "move_index" not in merged:
            merged["move_index"] = {}
        merged["move_index"]["value"] = new_move["value"]
        merged["move_index"]["observation_date"] = new_move.get("observation_date")
    
    return merged


def mark_curve_stale(error_reason: str) -> bool:
    """
    Mark existing curve_data as stale without overwriting it.
    Called on complete fetch failure.
    """
    try:
        if not MARKET_DATA_FILE.exists():
            print(f"  ⚠ No existing market_data.json to mark stale")
            return False
        
        with open(MARKET_DATA_FILE, 'r') as f:
            market_data = json.load(f)
        
        if 'curve_data' in market_data:
            market_data['curve_data']['_stale'] = True
            market_data['curve_data']['_stale_since'] = datetime.now().isoformat()
            market_data['curve_data']['_stale_reason'] = error_reason
        
        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['curve_data'] = 'stale'
        
        with open(MARKET_DATA_FILE, 'w') as f:
            json.dump(market_data, f, indent=2)
        
        print(f"  ⚠ Marked curve_data as stale: {error_reason}")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to mark data stale: {e}")
        return False


def update_market_data(curve_data: Dict[str, Any]) -> bool:
    """Update market_data.json with the new curve data."""
    try:
        if MARKET_DATA_FILE.exists():
            with open(MARKET_DATA_FILE, 'r') as f:
                market_data = json.load(f)
        else:
            market_data = {}
        
        existing_curve = market_data.get('curve_data', {})
        static_fields = {k: v for k, v in existing_curve.items() if k.startswith('_') and k not in ['_stale', '_stale_since', '_stale_reason']}
        
        merged_curve = merge_curve_data(existing_curve, curve_data)
        merged_curve.update(static_fields)
        
        if '_stale' in merged_curve:
            del merged_curve['_stale']
        if '_stale_since' in merged_curve:
            del merged_curve['_stale_since']
        if '_stale_reason' in merged_curve:
            del merged_curve['_stale_reason']
        
        market_data['curve_data'] = merged_curve
        
        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['curve_data'] = 'live'
        
        market_data['_updated'] = datetime.now().strftime('%Y-%m-%d')
        
        with open(MARKET_DATA_FILE, 'w') as f:
            json.dump(market_data, f, indent=2)
        
        print(f"  ✓ Updated {MARKET_DATA_FILE}")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to update market_data.json: {e}")
        return False


def main():
    print("=" * 60)
    print("Fetch Yield Curve Data")
    print("Sources: FRED (spreads/levels), Yahoo Finance (MOVE)")
    print(f"Started: {datetime.now()}")
    print("=" * 60)
    
    curve_data = fetch_all_curve_data()
    
    if has_any_data(curve_data):
        if not update_market_data(curve_data):
            mark_curve_stale("Failed to write market_data.json")
            return 1
        
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        
        spreads = curve_data.get("spreads", {})
        s2s10s = spreads.get("2s10s", {})
        s10s30s = spreads.get("10s30s", {})
        move = curve_data.get("move_index", {})
        
        v2s10s = f"{s2s10s['value_bps']}bp" if s2s10s.get('value_bps') is not None else "N/A"
        v10s30s = f"{s10s30s['value_bps']}bp" if s10s30s.get('value_bps') is not None else "N/A"
        vmove = f"{move['value']:.2f}" if move.get('value') is not None else "N/A"
        
        print(f"2s10s Spread: {v2s10s}")
        print(f"10s30s Spread: {v10s30s}")
        print(f"MOVE Index: {vmove}")
        
        levels = curve_data.get("levels", {})
        for tenor in ["2y", "10y", "30y"]:
            level = levels.get(tenor, {})
            val = f"{level['value']:.3f}%" if level.get('value') is not None else "N/A"
            print(f"{tenor.upper()} Yield: {val}")
        
        return 0
    else:
        mark_curve_stale("All fetches failed - no data retrieved")
        print("\n✗ Failed to fetch any curve data")
        print("  (existing data preserved, marked stale if present)")
        return 1


if __name__ == "__main__":
    exit(main())
