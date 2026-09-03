#!/usr/bin/env python3
"""
Fetch GPU rental pricing data from SemiAnalysis GPU Index.

Source: https://gpu-index.semianalysis.com/
Data type: Surveyed index (monthly survey of 100+ neoclouds and buyers, validated against transactions)

This fetcher extracts:
- H100 1-year contract rental price (the forward commitment signal)
- Historical trend of that series
- On-demand/spot state (including "Sold Out" as a first-class value)
- Period/as-of date for staleness awareness

The free public data LAGS by several months. This is intentional and must be displayed.

TREND CALCULATION:
The trend compares the latest period to the immediately previous period (period-over-period).
This is a deliberate choice: the SemiAnalysis history uses varying period lengths (half-years
and quarters in 2023-2024, monthly from mid-2025 onward), so a fixed "N-month" lookback would
be misleading. Period-over-period is always honest because the comparison period is stored
and displayed alongside the percentage. The UI must show "vs [comparison_period]" so readers
know exactly what's being compared.

All numeric values are rounded at the data boundary (2 decimal places for prices/midpoints,
1 decimal place for percentages) to prevent floating point noise from reaching the page.
"""

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from workspace_paths import SITE_DATA_DIR

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"
SOURCE_URL = "https://gpu-index.semianalysis.com/"


def fetch_gpu_index_page() -> Optional[str]:
    """Fetch the SemiAnalysis GPU index page HTML."""
    try:
        req = urllib.request.Request(
            SOURCE_URL,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"  ✗ Failed to fetch GPU index page: {e}")
        return None


def parse_table_rows(html: str, table_index: int) -> List[List[str]]:
    """
    Parse an HTML table by index and return rows as lists of cell text.
    Simple regex-based parser for server-rendered HTML tables.
    """
    table_pattern = r'<table[^>]*>(.*?)</table>'
    tables = re.findall(table_pattern, html, re.DOTALL | re.IGNORECASE)
    
    if table_index >= len(tables):
        return []
    
    table_html = tables[table_index]
    rows = []
    
    row_pattern = r'<tr[^>]*>(.*?)</tr>'
    cell_pattern = r'<t[hd][^>]*>(.*?)</t[hd]>'
    
    for row_match in re.finditer(row_pattern, table_html, re.DOTALL | re.IGNORECASE):
        row_html = row_match.group(1)
        cells = []
        for cell_match in re.finditer(cell_pattern, row_html, re.DOTALL | re.IGNORECASE):
            cell_text = cell_match.group(1)
            cell_text = re.sub(r'<[^>]+>', '', cell_text)
            cell_text = cell_text.strip()
            cell_text = cell_text.replace('\n', ' ').replace('\r', '')
            cell_text = re.sub(r'\s+', ' ', cell_text)
            cells.append(cell_text)
        if cells:
            rows.append(cells)
    
    return rows


def normalize_price_value(raw: str) -> Dict[str, Any]:
    """
    Normalize a price cell value into structured data.
    Handles: "$2.10-2.70", "$2.82", "Sold Out", "✕ Sold Out", "—", empty.
    Returns dict with 'display', 'type', and optionally 'low'/'high' for ranges.
    """
    if not raw or raw.strip() in ('', '—', '–', '-'):
        return {'display': '—', 'type': 'unavailable'}
    
    text = raw.strip()
    
    if 'sold out' in text.lower():
        return {'display': 'Sold Out', 'type': 'sold_out'}
    
    range_match = re.match(r'\$?([\d.]+)\s*[-–]\s*\$?([\d.]+)', text)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        return {
            'display': f'${low:.2f}-{high:.2f}',
            'type': 'range',
            'low': round(low, 2),
            'high': round(high, 2),
            'midpoint': round((low + high) / 2, 2)
        }
    
    single_match = re.match(r'\$?([\d.]+)', text)
    if single_match:
        value = float(single_match.group(1))
        return {
            'display': f'${value:.2f}',
            'type': 'single',
            'value': value
        }
    
    return {'display': text, 'type': 'unknown'}


def parse_current_market_table(rows: List[List[str]]) -> Dict[str, Any]:
    """
    Parse the "Current Market Pricing" table.
    Returns dict keyed by SKU (e.g., 'H100') with period and pricing data.
    """
    if len(rows) < 2:
        return {}
    
    header = rows[0]
    
    col_map = {}
    for i, col in enumerate(header):
        col_lower = col.lower().strip()
        if 'sku' in col_lower:
            col_map['sku'] = i
        elif 'period' in col_lower:
            col_map['period'] = i
        elif 'composite' in col_lower or 'spot-contract' in col_lower:
            col_map['composite'] = i
        elif 'on-demand' in col_lower:
            col_map['on_demand'] = i
        elif '1y' in col_lower:
            col_map['1y'] = i
    
    results = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        
        sku = row[col_map.get('sku', 0)].strip().upper() if 'sku' in col_map else ''
        if not sku:
            continue
        
        entry = {'sku': sku}
        
        if 'period' in col_map and len(row) > col_map['period']:
            entry['period'] = row[col_map['period']].strip()
        
        if 'composite' in col_map and len(row) > col_map['composite']:
            entry['composite'] = normalize_price_value(row[col_map['composite']])
        
        if 'on_demand' in col_map and len(row) > col_map['on_demand']:
            entry['on_demand'] = normalize_price_value(row[col_map['on_demand']])
        
        if '1y' in col_map and len(row) > col_map['1y']:
            entry['1y_contract'] = normalize_price_value(row[col_map['1y']])
        
        results[sku] = entry
    
    return results


def parse_history_table(rows: List[List[str]]) -> List[Dict[str, Any]]:
    """
    Parse the "Detailed Pricing History" table.
    Returns list of dicts with period and pricing data, oldest first.
    """
    if len(rows) < 2:
        return []
    
    header = rows[0]
    
    col_map = {}
    for i, col in enumerate(header):
        col_lower = col.lower().strip()
        if 'period' in col_lower:
            col_map['period'] = i
        elif 'composite' in col_lower or 'spot-contract' in col_lower:
            col_map['composite'] = i
        elif 'on-demand' in col_lower:
            col_map['on_demand'] = i
        elif '1y' in col_lower:
            col_map['1y'] = i
    
    history = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        
        period = row[col_map.get('period', 0)].strip() if 'period' in col_map else ''
        if not period:
            continue
        
        entry = {'period': period}
        
        if 'composite' in col_map and len(row) > col_map['composite']:
            entry['composite'] = normalize_price_value(row[col_map['composite']])
        
        if 'on_demand' in col_map and len(row) > col_map['on_demand']:
            entry['on_demand'] = normalize_price_value(row[col_map['on_demand']])
        
        if '1y' in col_map and len(row) > col_map['1y']:
            entry['1y_contract'] = normalize_price_value(row[col_map['1y']])
        
        history.append(entry)
    
    return history


def compute_trend(history: List[Dict[str, Any]], field: str = '1y_contract') -> Dict[str, Any]:
    """
    Compute trend for a price series using dual-horizon comparison.
    
    Returns TWO comparisons:
    1. Short-term: Latest period vs immediately previous period (period-over-period)
    2. Long-term: Latest period vs anchor ~6 rows back (or earliest valid if <7 points)
    
    ANCHOR SELECTION RULE (deterministic, documented):
    - If history has ≥7 valid data points: use index -7 (6 row intervals back from latest)
    - Otherwise: use index 0 (earliest available point)
    
    IMPORTANT: The history contains non-monthly rows (1H 2023, 2H 2023, Q1 2024, etc.)
    so row count does NOT equal calendar months. The `row_intervals` field explicitly
    counts the number of valid data rows between anchor and latest, not elapsed time.
    
    ZERO/INVALID ANCHOR HANDLING:
    If an anchor value is zero or negative, the percentage cannot be computed validly.
    In this case, the long_term comparison is omitted entirely (fail-closed).
    
    All numeric values are rounded to prevent floating point noise from reaching the page.
    """
    valid_points = []
    for h in history:
        if field not in h:
            continue
        price_data = h[field]
        if price_data['type'] in ('range', 'single'):
            if price_data['type'] == 'range':
                value = round(price_data['midpoint'], 2)
            else:
                value = round(price_data['value'], 2)
            valid_points.append({
                'period': h['period'],
                'value': value,
                'display': price_data['display']
            })
    
    if len(valid_points) < 2:
        return {'insufficient_data': True, 'data_points': len(valid_points)}
    
    latest = valid_points[-1]
    previous = valid_points[-2]
    
    # Short-term: period-over-period comparison
    # Guard against zero/negative previous value (fail-closed: no percentage)
    if previous['value'] <= 0:
        return {'insufficient_data': True, 'data_points': len(valid_points), 
                'reason': 'previous period value is zero or negative'}
    
    short_pct = ((latest['value'] - previous['value']) / previous['value']) * 100
    short_pct = round(short_pct, 1)
    
    result = {
        'data_points': len(valid_points),
        'latest_value': latest['value'],
        'latest_display': latest['display'],
        'latest_period': latest['period'],
        'short_term': {
            'change_pct': short_pct,
            'comparison_period': previous['period'],
            'comparison_value': previous['value'],
            'comparison_display': previous['display']
        }
    }
    
    # Long-term: anchor selection per documented rule
    # Prefer index -7 (6 row intervals back) if ≥7 points; otherwise earliest (index 0)
    if len(valid_points) >= 7:
        anchor_index = -7
    else:
        anchor_index = 0
    
    anchor = valid_points[anchor_index]
    
    # Only include long_term if:
    # 1. Anchor differs from short_term comparison (i.e., at least 3 points)
    # 2. Anchor value is positive (fail-closed: no invalid percentages)
    if anchor['period'] != previous['period'] and anchor['value'] > 0:
        long_pct = ((latest['value'] - anchor['value']) / anchor['value']) * 100
        long_pct = round(long_pct, 1)
        
        # row_intervals: number of rows between anchor and latest (not calendar time)
        # For index -7 with 18 points: latest is index 17, anchor is index 11, intervals = 6
        # This is explicitly row-based because history has varying period lengths
        # (1H 2023, Q1 2024, monthly from mid-2025, etc.)
        if anchor_index < 0:
            row_intervals = abs(anchor_index) - 1  # -7 means 6 intervals to latest
        else:
            row_intervals = len(valid_points) - 1 - anchor_index
        
        result['long_term'] = {
            'change_pct': long_pct,
            'anchor_period': anchor['period'],
            'anchor_value': anchor['value'],
            'anchor_display': anchor['display'],
            'row_intervals': row_intervals
        }
    
    # Legacy compatibility: keep 'change_pct' at top level but deprecate it
    # The UI should migrate to using short_term/long_term objects
    result['change_pct'] = short_pct
    result['comparison_period'] = previous['period']
    result['comparison_value'] = previous['value']
    result['comparison_display'] = previous['display']
    
    return result


def validate_parsed_result(result: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate that a parsed result has all required fields with valid data.
    Returns (is_valid, error_reason).
    
    Required for a valid result:
    - h100.period must not be 'unknown' or empty
    - h100.1y_contract must have a valid type (range or single), not unavailable
    - h100.trend must have short_term data (not insufficient_data)
    
    This prevents partial/malformed parses from overwriting previously good data.
    """
    if not result:
        return False, "result is None"
    
    h100 = result.get('h100', {})
    
    # Check period
    period = h100.get('period', '')
    if not period or period == 'unknown':
        return False, "H100 period is missing or unknown"
    
    # Check 1y_contract has valid pricing data
    contract = h100.get('1y_contract', {})
    contract_type = contract.get('type', '')
    if contract_type not in ('range', 'single'):
        return False, f"H100 1y_contract type is '{contract_type}', expected range or single"
    
    # Check trend has valid short_term data
    trend = h100.get('trend', {})
    if trend.get('insufficient_data'):
        return False, f"H100 trend has insufficient data: {trend.get('reason', 'unknown reason')}"
    if not trend.get('short_term'):
        return False, "H100 trend missing short_term comparison"
    
    return True, ""


def fetch_and_parse() -> tuple[Optional[Dict[str, Any]], str]:
    """
    Main fetch and parse function.
    Returns (structured_data, error_reason) tuple.
    
    On success: (data_dict, "")
    On failure: (None, "reason for failure")
    
    The error_reason is used to mark existing data as stale with context.
    """
    print("Fetching SemiAnalysis GPU Index...")
    
    html = fetch_gpu_index_page()
    if not html:
        return None, "Network error: failed to fetch page"
    
    current_table_rows = parse_table_rows(html, 0)
    history_table_rows = parse_table_rows(html, 1)
    
    if not current_table_rows:
        return None, "Parse error: current market pricing table not found"
    if not history_table_rows:
        return None, "Parse error: pricing history table not found"
    
    current_data = parse_current_market_table(current_table_rows)
    history_data = parse_history_table(history_table_rows)
    
    if not current_data:
        return None, "Parse error: could not extract current market data from table"
    if not history_data:
        return None, "Parse error: could not extract history data from table"
    
    h100_current = current_data.get('H100', {})
    if not h100_current:
        return None, "Parse error: H100 row not found in current market table"
    
    h100_trend = compute_trend(history_data, '1y_contract')
    
    latest_on_demand = None
    for h in reversed(history_data):
        if 'on_demand' in h and h['on_demand']['type'] != 'unavailable':
            latest_on_demand = h['on_demand'].copy()
            latest_on_demand['period'] = h['period']
            break
    
    result = {
        '_comment': 'GPU rental pricing index from SemiAnalysis. This is SURVEYED data from monthly surveys of 100+ neoclouds/buyers, validated against transactions. NOT a live market price.',
        '_source_url': SOURCE_URL,
        '_data_type': 'surveyed_index',
        '_staleness_note': 'Free public data lags several months behind current date. Display the as-of period prominently.',
        'last_fetched': datetime.now().isoformat(),
        
        'h100': {
            'period': h100_current.get('period', 'unknown'),
            'composite_index': h100_current.get('composite', {'display': '—', 'type': 'unavailable'}),
            '1y_contract': h100_current.get('1y_contract', {'display': '—', 'type': 'unavailable'}),
            'on_demand': latest_on_demand or {'display': '—', 'type': 'unavailable'},
            'trend': h100_trend
        },
        
        'b200': {
            'period': current_data.get('B200', {}).get('period', 'unknown'),
            'composite_index': current_data.get('B200', {}).get('composite', {'display': '—', 'type': 'unavailable'})
        },
        
        'history_summary': {
            'oldest_period': history_data[0]['period'] if history_data else None,
            'newest_period': history_data[-1]['period'] if history_data else None,
            'total_periods': len(history_data),
            'recent_5': [
                {
                    'period': h['period'],
                    '1y_contract': h.get('1y_contract', {}).get('display', '—'),
                    'on_demand': h.get('on_demand', {}).get('display', '—')
                }
                for h in history_data[-5:]
            ] if history_data else []
        }
    }
    
    # Validate the result before accepting it
    is_valid, error_reason = validate_parsed_result(result)
    if not is_valid:
        return None, f"Validation error: {error_reason}"
    
    print(f"  ✓ Parsed H100 data for period: {result['h100']['period']}")
    print(f"    1Y Contract: {result['h100']['1y_contract']['display']}")
    print(f"    On-Demand: {result['h100']['on_demand']['display']}")
    trend = result['h100']['trend']
    if trend.get('short_term'):
        short = trend['short_term']
        long_str = ""
        if trend.get('long_term'):
            lt = trend['long_term']
            long_str = f", {lt['change_pct']:+.1f}% since {lt['anchor_period']}"
        print(f"    Trend: {short['change_pct']:+.1f}% vs {short['comparison_period']}{long_str}")
    else:
        print(f"    Trend: insufficient data ({trend.get('data_points', 0)} points)")
    
    return result, ""


def mark_data_stale(error_reason: str) -> bool:
    """
    Mark existing compute_forward data as stale without overwriting it.
    Called on fetch failure so the widget shows the last known good data
    with a staleness indicator rather than fabricated or missing values.
    """
    try:
        if not MARKET_DATA_FILE.exists():
            print(f"  ⚠ No existing market_data.json to mark stale")
            return False
        
        with open(MARKET_DATA_FILE, 'r') as f:
            market_data = json.load(f)
        
        if 'compute_forward' in market_data:
            market_data['compute_forward']['_stale'] = True
            market_data['compute_forward']['_stale_since'] = datetime.now().isoformat()
            market_data['compute_forward']['_stale_reason'] = error_reason
        
        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['compute_forward'] = 'stale'
        
        with open(MARKET_DATA_FILE, 'w') as f:
            json.dump(market_data, f, indent=2)
        
        print(f"  ⚠ Marked compute_forward as stale: {error_reason}")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to mark data stale: {e}")
        return False


def update_market_data(gpu_data: Dict[str, Any]) -> bool:
    """Update market_data.json with the new GPU index data."""
    try:
        if MARKET_DATA_FILE.exists():
            with open(MARKET_DATA_FILE, 'r') as f:
                market_data = json.load(f)
        else:
            market_data = {}
        
        market_data['compute_forward'] = gpu_data
        
        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['compute_forward'] = 'live'
        
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
    print("Fetch SemiAnalysis GPU Rental Pricing Index")
    print(f"Source: {SOURCE_URL}")
    print(f"Started: {datetime.now()}")
    print("=" * 60)
    
    data, error_reason = fetch_and_parse()
    
    if data:
        if not update_market_data(data):
            mark_data_stale("Failed to write market_data.json")
            return 1
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"H100 1Y Contract: {data['h100']['1y_contract']['display']}")
        print(f"As-of Period: {data['h100']['period']}")
        trend = data['h100']['trend']
        if trend.get('short_term'):
            short = trend['short_term']
            trend_str = f"{short['change_pct']:+.1f}% vs {short['comparison_period']}"
            if trend.get('long_term'):
                lt = trend['long_term']
                trend_str += f" · {lt['change_pct']:+.1f}% since {lt['anchor_period']}"
            print(f"Trend: {trend_str}")
        else:
            print(f"Trend: insufficient data")
        print(f"On-Demand Status: {data['h100']['on_demand']['display']}")
    else:
        # Fetch/parse/validation failed - mark existing data as stale but don't overwrite it
        # This is fail-closed behavior: the widget shows last known good data
        # with staleness indicator rather than fabricated or missing values
        mark_data_stale(error_reason or "Unknown error during fetch/parse")
        print(f"\n✗ Failed to fetch GPU index data: {error_reason}")
        print("  (existing data preserved, marked stale)")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
