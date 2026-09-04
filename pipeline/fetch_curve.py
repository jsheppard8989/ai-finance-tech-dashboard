#!/usr/bin/env python3
"""
Fetch yield curve data: Treasury levels, spreads, and MOVE index.

PRIMARY SOURCE: Treasury.gov daily yield curve XML (no API key required)
  - Endpoint: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml
  - Provides: 2Y, 10Y, 30Y Treasury yields (and other maturities)
  - Spreads computed: 2s10s (10Y - 2Y), 10s30s (30Y - 10Y)

OPTIONAL ENRICHMENT: FRED (when reachable, no key required for <500 calls/day)
  - Series: T10Y2Y (precomputed 2s10s spread for validation)
  - NOT required for pipeline to function

MOVE INDEX: Yahoo Finance ^MOVE (unchanged from original design)

FAIL-CLOSED: On fetch failure, existing data is marked stale but preserved.
The UI shows last-known-good values with a staleness indicator.
"""

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from workspace_paths import SITE_DATA_DIR

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"

# Treasury.gov daily yield curve XML endpoint (no API key required)
TREASURY_XML_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
TREASURY_SOURCE_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"

# FRED series (optional enrichment, no key required for basic usage)
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_SERIES = {
    'T10Y2Y': '10-Year minus 2-Year Treasury spread (precomputed)',
    'DGS2': '2-Year Treasury Constant Maturity',
    'DGS10': '10-Year Treasury Constant Maturity',
    'DGS30': '30-Year Treasury Constant Maturity',
}

# Yahoo Finance for MOVE index
YAHOO_MOVE_SYMBOL = "^MOVE"


def fetch_treasury_xml(year: int = None) -> Optional[str]:
    """
    Fetch Treasury.gov daily yield curve XML for a given year.
    Uses current year if not specified.
    """
    if year is None:
        year = datetime.now().year
    
    url = f"{TREASURY_XML_URL}?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
    
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"  ✗ Failed to fetch Treasury.gov XML: {e}")
        return None


def parse_treasury_xml(xml_content: str) -> List[Dict[str, Any]]:
    """
    Parse Treasury.gov yield curve XML into a list of daily records.
    Each record has: date, and yields for various maturities.
    
    XML structure uses namespace: http://www.w3.org/2005/Atom
    Entry content has fields like: d:BC_2YEAR, d:BC_10YEAR, d:BC_30YEAR, d:NEW_DATE
    """
    records = []
    
    try:
        root = ET.fromstring(xml_content)
        
        # Define namespaces used in Treasury XML
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'm': 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata',
            'd': 'http://schemas.microsoft.com/ado/2007/08/dataservices'
        }
        
        # Find all entry elements
        for entry in root.findall('.//atom:entry', ns):
            content = entry.find('.//atom:content', ns)
            if content is None:
                continue
            
            properties = content.find('.//m:properties', ns)
            if properties is None:
                continue
            
            record = {}
            
            # Extract date
            date_elem = properties.find('d:NEW_DATE', ns)
            if date_elem is not None and date_elem.text:
                # Date format: 2026-01-02T00:00:00
                date_str = date_elem.text.split('T')[0]
                record['date'] = date_str
            
            # Extract yields (BC_ prefix for bond-equivalent yields)
            yield_map = {
                'd:BC_2YEAR': '2y',
                'd:BC_10YEAR': '10y',
                'd:BC_30YEAR': '30y',
                'd:BC_1MONTH': '1m',
                'd:BC_3MONTH': '3m',
                'd:BC_6MONTH': '6m',
                'd:BC_1YEAR': '1yr',
                'd:BC_5YEAR': '5y',
                'd:BC_7YEAR': '7y',
                'd:BC_20YEAR': '20y',
            }
            
            for xml_key, our_key in yield_map.items():
                elem = properties.find(xml_key, ns)
                if elem is not None and elem.text:
                    try:
                        record[our_key] = float(elem.text)
                    except ValueError:
                        pass
            
            if 'date' in record and ('2y' in record or '10y' in record or '30y' in record):
                records.append(record)
        
        # Sort by date descending (most recent first)
        records.sort(key=lambda x: x.get('date', ''), reverse=True)
        
    except ET.ParseError as e:
        print(f"  ✗ XML parse error: {e}")
        return []
    except Exception as e:
        print(f"  ✗ Error parsing Treasury XML: {e}")
        return []
    
    return records


def fetch_treasury_yields() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Fetch and parse Treasury.gov yield curve data.
    Returns (data_dict, error_reason) tuple.
    """
    print("Fetching Treasury.gov daily yield curve...")
    
    xml_content = fetch_treasury_xml()
    if not xml_content:
        return None, "Network error: failed to fetch Treasury.gov XML"
    
    records = parse_treasury_xml(xml_content)
    if not records:
        return None, "Parse error: no valid records found in Treasury XML"
    
    # Get most recent record
    latest = records[0]
    
    # Validate we have the yields we need
    if '2y' not in latest or '10y' not in latest:
        return None, f"Parse error: missing required yields (2y={latest.get('2y')}, 10y={latest.get('10y')})"
    
    # Build result with levels and computed spreads
    result = {
        'date': latest.get('date'),
        'source': 'Treasury.gov',
        'source_url': TREASURY_SOURCE_URL,
        'levels': {
            '2y': latest.get('2y'),
            '10y': latest.get('10y'),
            '30y': latest.get('30y'),
        },
        'spreads': {}
    }
    
    # Compute 2s10s spread (10Y - 2Y) in basis points
    y2 = latest.get('2y')
    y10 = latest.get('10y')
    y30 = latest.get('30y')
    
    if y2 is not None and y10 is not None:
        spread_2s10s = round((y10 - y2) * 100, 1)  # Convert to bps
        result['spreads']['2s10s'] = {
            'value_bps': spread_2s10s,
            'calculation': '10Y - 2Y',
            'signal': 'inverted' if spread_2s10s < 0 else ('flat' if spread_2s10s < 25 else 'normal')
        }
        print(f"  ✓ 2s10s spread: {spread_2s10s:+.1f} bps")
    
    # Compute 10s30s spread (30Y - 10Y) in basis points
    if y10 is not None and y30 is not None:
        spread_10s30s = round((y30 - y10) * 100, 1)  # Convert to bps
        result['spreads']['10s30s'] = {
            'value_bps': spread_10s30s,
            'calculation': '30Y - 10Y',
            'signal': 'inverted' if spread_10s30s < 0 else ('flat' if spread_10s30s < 15 else 'normal')
        }
        print(f"  ✓ 10s30s spread: {spread_10s30s:+.1f} bps")
    
    # Get previous day for change calculation (if available)
    if len(records) >= 2:
        prev = records[1]
        result['previous_date'] = prev.get('date')
        
        # Calculate 1-day changes
        for key in ['2y', '10y', '30y']:
            if key in latest and key in prev:
                change = round((latest[key] - prev[key]) * 100, 1)  # Convert to bps
                result['levels'][key] = {
                    'value': latest[key],
                    'change_1d_bps': change
                }
    else:
        # No previous day, just store values
        for key in ['2y', '10y', '30y']:
            if key in latest:
                result['levels'][key] = {
                    'value': latest[key],
                    'change_1d_bps': None
                }
    
    print(f"  ✓ Treasury data as of {latest.get('date')}: 2Y={y2}%, 10Y={y10}%, 30Y={y30}%")
    
    return result, ""


def fetch_fred_series(series_id: str, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch a FRED series. No API key required for <500 calls/day (uses demo mode).
    This is OPTIONAL enrichment - pipeline works without it.
    """
    import os
    
    # Use provided key, env var, or omit (FRED allows limited keyless access)
    key = api_key or os.environ.get('FRED_API_KEY', '')
    
    # FRED requires an API key for programmatic access, but we can try without
    # If no key, try a simple direct download approach
    if not key:
        # Try direct CSV download (sometimes works without key)
        csv_url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        try:
            req = urllib.request.Request(
                csv_url,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read().decode('utf-8')
                lines = content.strip().split('\n')
                if len(lines) >= 2:
                    # Parse CSV: DATE,VALUE
                    last_line = lines[-1]
                    parts = last_line.split(',')
                    if len(parts) >= 2 and parts[1] not in ('', '.'):
                        return {
                            'series_id': series_id,
                            'date': parts[0],
                            'value': float(parts[1])
                        }
        except Exception as e:
            print(f"  ⚠ FRED {series_id} fetch failed (optional): {e}")
            return None
    else:
        # Use official API with key
        url = f"{FRED_BASE_URL}?series_id={series_id}&api_key={key}&file_type=json&sort_order=desc&limit=1"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read())
                obs = data.get('observations', [])
                if obs:
                    return {
                        'series_id': series_id,
                        'date': obs[0].get('date'),
                        'value': float(obs[0].get('value')) if obs[0].get('value') not in ('', '.') else None
                    }
        except Exception as e:
            print(f"  ⚠ FRED {series_id} fetch failed (optional): {e}")
            return None
    
    return None


def try_fred_enrichment() -> Optional[Dict[str, Any]]:
    """
    Attempt FRED enrichment. Returns data if successful, None otherwise.
    This is OPTIONAL - the pipeline works without FRED.
    """
    print("Attempting FRED enrichment (optional)...")
    
    enrichment = {}
    
    # Try to get T10Y2Y (precomputed spread) for validation
    t10y2y = fetch_fred_series('T10Y2Y')
    if t10y2y and t10y2y.get('value') is not None:
        enrichment['T10Y2Y'] = t10y2y
        print(f"  ✓ FRED T10Y2Y: {t10y2y['value']} (as of {t10y2y['date']})")
    
    if enrichment:
        return enrichment
    
    print("  ⚠ FRED enrichment unavailable (pipeline continues without it)")
    return None


def fetch_move_index() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Fetch MOVE index from Yahoo Finance.
    Returns (data_dict, error_reason) tuple.
    """
    print(f"Fetching MOVE index ({YAHOO_MOVE_SYMBOL})...")
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{YAHOO_MOVE_SYMBOL}?interval=1d&range=5d"
    
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
        
        if not data.get('chart', {}).get('result'):
            return None, "Yahoo returned no data for ^MOVE"
        
        result = data['chart']['result'][0]
        meta = result['meta']
        
        current = meta.get('regularMarketPrice') or meta.get('previousClose')
        if current is None:
            return None, "No price data in Yahoo response for ^MOVE"
        
        # Get previous close for 1-day change
        prev_close = meta.get('previousClose', current)
        change_1d = round(current - prev_close, 2) if prev_close else None
        
        # Determine signal based on thresholds
        thresholds = {'low': 80, 'normal': 100, 'elevated': 120, 'high': 150}
        if current < thresholds['low']:
            signal = 'low_vol'
        elif current < thresholds['normal']:
            signal = 'normal'
        elif current < thresholds['elevated']:
            signal = 'elevated'
        elif current < thresholds['high']:
            signal = 'high'
        else:
            signal = 'extreme'
        
        move_data = {
            'value': round(current, 2),
            'change_1d': change_1d,
            'signal': signal,
            'source': 'Yahoo Finance',
            'yahoo_symbol': YAHOO_MOVE_SYMBOL,
        }
        
        print(f"  ✓ MOVE index: {current:.2f} ({change_1d:+.2f} 1d)")
        return move_data, ""
        
    except Exception as e:
        return None, f"Error fetching MOVE from Yahoo: {e}"


def fetch_and_build_curve_data() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Main function to fetch all curve data components.
    Returns (curve_data_dict, error_reason) tuple.
    
    Sources:
    - PRIMARY: Treasury.gov daily yield curve (levels + computed spreads)
    - OPTIONAL: FRED enrichment (validation data when available)
    - MOVE: Yahoo Finance ^MOVE
    """
    errors = []
    
    # 1. Fetch Treasury.gov yields (PRIMARY - required)
    treasury_data, treasury_error = fetch_treasury_yields()
    if not treasury_data:
        errors.append(f"Treasury.gov: {treasury_error}")
    
    # 2. Attempt FRED enrichment (OPTIONAL - continues without it)
    fred_data = try_fred_enrichment()
    
    # 3. Fetch MOVE index (separate from Treasury data)
    move_data, move_error = fetch_move_index()
    if not move_data:
        errors.append(f"MOVE: {move_error}")
    
    # If Treasury (primary) failed, we can't produce valid curve data
    if not treasury_data:
        return None, "; ".join(errors)
    
    # Build the curve_data structure matching market_data.json schema
    curve_data = {
        '_comment': 'Yield curve spreads and volatility. PRIMARY source: Treasury.gov daily yield curve. MOVE: Yahoo Finance.',
        '_primary_source': 'Treasury.gov',
        '_source_url': TREASURY_SOURCE_URL,
        '_fred_status': 'available' if fred_data else 'unavailable (optional)',
        'last_updated': datetime.now().isoformat(),
        'as_of_date': treasury_data.get('date'),
        
        'spreads': {
            '2s10s': {
                'label': '2s10s Spread',
                'description': '10Y minus 2Y Treasury yield. Classic recession indicator. Negative = inverted curve.',
                'value_bps': treasury_data['spreads'].get('2s10s', {}).get('value_bps'),
                'signal': treasury_data['spreads'].get('2s10s', {}).get('signal'),
                'source': 'Treasury.gov (computed)',
                'calculation': '10Y - 2Y from Treasury daily curve',
            },
            '10s30s': {
                'label': '10s30s Spread (NOB proxy)',
                'description': '30Y minus 10Y Treasury yield. Reflects long-end term premium and duration demand.',
                'value_bps': treasury_data['spreads'].get('10s30s', {}).get('value_bps'),
                'signal': treasury_data['spreads'].get('10s30s', {}).get('signal'),
                'source': 'Treasury.gov (computed)',
                'calculation': '30Y - 10Y from Treasury daily curve',
            }
        },
        
        'levels': {
            '2y': {
                'value': treasury_data['levels'].get('2y', {}).get('value') if isinstance(treasury_data['levels'].get('2y'), dict) else treasury_data['levels'].get('2y'),
                'change_1d_bps': treasury_data['levels'].get('2y', {}).get('change_1d_bps') if isinstance(treasury_data['levels'].get('2y'), dict) else None,
                'source': 'Treasury.gov'
            },
            '10y': {
                'value': treasury_data['levels'].get('10y', {}).get('value') if isinstance(treasury_data['levels'].get('10y'), dict) else treasury_data['levels'].get('10y'),
                'change_1d_bps': treasury_data['levels'].get('10y', {}).get('change_1d_bps') if isinstance(treasury_data['levels'].get('10y'), dict) else None,
                'source': 'Treasury.gov'
            },
            '30y': {
                'value': treasury_data['levels'].get('30y', {}).get('value') if isinstance(treasury_data['levels'].get('30y'), dict) else treasury_data['levels'].get('30y'),
                'change_1d_bps': treasury_data['levels'].get('30y', {}).get('change_1d_bps') if isinstance(treasury_data['levels'].get('30y'), dict) else None,
                'source': 'Treasury.gov'
            }
        },
        
        'move_index': {
            '_comment': 'MOVE Index - bond market VIX. Source: Yahoo Finance ^MOVE.',
            'label': 'MOVE Index',
            'description': 'Treasury implied volatility index. High readings = bond market stress/uncertainty.',
            'value': move_data.get('value') if move_data else None,
            'change_1d': move_data.get('change_1d') if move_data else None,
            'signal': move_data.get('signal') if move_data else None,
            'yahoo_symbol': YAHOO_MOVE_SYMBOL,
            'source': 'Yahoo Finance',
            'thresholds': {'low': 80, 'normal': 100, 'elevated': 120, 'high': 150}
        }
    }
    
    # Add FRED enrichment data if available (for transparency/validation)
    if fred_data:
        curve_data['_fred_enrichment'] = {
            'status': 'available',
            'T10Y2Y': fred_data.get('T10Y2Y'),
        }
    
    return curve_data, ""


def validate_curve_data(data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate curve data has minimum required fields.
    Returns (is_valid, error_reason).
    """
    if not data:
        return False, "data is None"
    
    # Must have at least 2s10s spread from Treasury
    spreads = data.get('spreads', {})
    s2s10s = spreads.get('2s10s', {})
    if s2s10s.get('value_bps') is None:
        return False, "2s10s spread value is missing"
    
    # Must have at least 2Y and 10Y levels
    levels = data.get('levels', {})
    if levels.get('2y', {}).get('value') is None:
        return False, "2Y yield level is missing"
    if levels.get('10y', {}).get('value') is None:
        return False, "10Y yield level is missing"
    
    return True, ""


def mark_curve_data_stale(error_reason: str) -> bool:
    """
    Mark existing curve_data as stale without overwriting it.
    Preserves last-known-good values.
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
        
        # Remove stale flags if present
        curve_data.pop('_stale', None)
        curve_data.pop('_stale_since', None)
        curve_data.pop('_stale_reason', None)

        existing_curve = market_data.get('curve_data') or {}
        new_move = curve_data.get('move_index') or {}
        old_move = existing_curve.get('move_index') or {}
        if new_move.get('value') is None and old_move.get('value') is not None:
            # Preserve last-known-good MOVE when Yahoo is unreachable
            preserved = dict(old_move)
            preserved['_comment'] = new_move.get('_comment', preserved.get('_comment'))
            preserved['label'] = new_move.get('label', preserved.get('label'))
            preserved['description'] = new_move.get('description', preserved.get('description'))
            preserved['yahoo_symbol'] = new_move.get('yahoo_symbol', preserved.get('yahoo_symbol'))
            preserved['source'] = new_move.get('source', preserved.get('source', 'Yahoo Finance'))
            preserved['thresholds'] = new_move.get('thresholds', preserved.get('thresholds'))
            curve_data['move_index'] = preserved
            print("  ⚠ MOVE unavailable; preserved last-known-good MOVE value")

        market_data['curve_data'] = curve_data
        
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
    print("PRIMARY: Treasury.gov daily yield curve")
    print("OPTIONAL: FRED enrichment (no API key required)")
    print("MOVE: Yahoo Finance ^MOVE")
    print(f"Started: {datetime.now()}")
    print("=" * 60)
    
    data, error_reason = fetch_and_build_curve_data()
    
    if data:
        # Validate before accepting
        is_valid, validation_error = validate_curve_data(data)
        if not is_valid:
            mark_curve_data_stale(f"Validation failed: {validation_error}")
            print(f"\n✗ Validation failed: {validation_error}")
            return 1
        
        if not update_market_data(data):
            mark_curve_data_stale("Failed to write market_data.json")
            return 1
        
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"As of: {data.get('as_of_date')}")
        print(f"Source: {data.get('_primary_source')}")
        
        spreads = data.get('spreads', {})
        if spreads.get('2s10s', {}).get('value_bps') is not None:
            print(f"2s10s Spread: {spreads['2s10s']['value_bps']:+.1f} bps ({spreads['2s10s'].get('signal', 'unknown')})")
        if spreads.get('10s30s', {}).get('value_bps') is not None:
            print(f"10s30s Spread: {spreads['10s30s']['value_bps']:+.1f} bps ({spreads['10s30s'].get('signal', 'unknown')})")
        
        levels = data.get('levels', {})
        print(f"Levels: 2Y={levels.get('2y', {}).get('value')}%, 10Y={levels.get('10y', {}).get('value')}%, 30Y={levels.get('30y', {}).get('value')}%")
        
        move = data.get('move_index', {})
        if move.get('value') is not None:
            print(f"MOVE: {move['value']:.2f} ({move.get('signal', 'unknown')})")
        else:
            print("MOVE: unavailable")
        
        fred_status = data.get('_fred_status', 'unknown')
        print(f"FRED enrichment: {fred_status}")
        
    else:
        # Fetch/parse/validation failed - mark existing data as stale
        mark_curve_data_stale(error_reason or "Unknown error during fetch/parse")
        print(f"\n✗ Failed to fetch curve data: {error_reason}")
        print("  (existing data preserved, marked stale)")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
