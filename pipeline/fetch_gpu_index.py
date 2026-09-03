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
            'low': low,
            'high': high,
            'midpoint': (low + high) / 2
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
    Compute trend direction for a price series.
    Returns trend info with direction, recent values, and change.
    """
    valid_points = []
    for h in history:
        if field not in h:
            continue
        price_data = h[field]
        if price_data['type'] in ('range', 'single'):
            if price_data['type'] == 'range':
                value = price_data['midpoint']
            else:
                value = price_data['value']
            valid_points.append({
                'period': h['period'],
                'value': value,
                'display': price_data['display']
            })
    
    if len(valid_points) < 2:
        return {'direction': 'insufficient_data', 'points': len(valid_points)}
    
    recent_3 = valid_points[-3:] if len(valid_points) >= 3 else valid_points[-2:]
    recent_6 = valid_points[-6:] if len(valid_points) >= 6 else valid_points
    
    latest = recent_3[-1]['value']
    prev = recent_3[0]['value']
    
    change_pct = ((latest - prev) / prev) * 100 if prev > 0 else 0
    
    if change_pct > 10:
        direction = 'rising_sharply'
    elif change_pct > 3:
        direction = 'rising'
    elif change_pct < -10:
        direction = 'falling_sharply'
    elif change_pct < -3:
        direction = 'falling'
    else:
        direction = 'stable'
    
    return {
        'direction': direction,
        'change_pct': round(change_pct, 1),
        'latest_value': latest,
        'latest_display': recent_3[-1]['display'],
        'latest_period': recent_3[-1]['period'],
        'comparison_period': recent_3[0]['period'],
        'comparison_value': prev,
        'comparison_display': recent_3[0]['display'],
        'data_points': len(valid_points)
    }


def fetch_and_parse() -> Optional[Dict[str, Any]]:
    """
    Main fetch and parse function.
    Returns structured data for the compute forward widget.
    """
    print("Fetching SemiAnalysis GPU Index...")
    
    html = fetch_gpu_index_page()
    if not html:
        return None
    
    current_table_rows = parse_table_rows(html, 0)
    history_table_rows = parse_table_rows(html, 1)
    
    if not current_table_rows or not history_table_rows:
        print("  ✗ Failed to parse tables from HTML")
        return None
    
    current_data = parse_current_market_table(current_table_rows)
    history_data = parse_history_table(history_table_rows)
    
    h100_current = current_data.get('H100', {})
    h100_trend = compute_trend(history_data, '1y_contract')
    
    latest_on_demand = None
    for h in reversed(history_data):
        if 'on_demand' in h and h['on_demand']['type'] != 'unavailable':
            latest_on_demand = h['on_demand']
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
    
    print(f"  ✓ Parsed H100 data for period: {result['h100']['period']}")
    print(f"    1Y Contract: {result['h100']['1y_contract']['display']}")
    print(f"    On-Demand: {result['h100']['on_demand']['display']}")
    print(f"    Trend: {result['h100']['trend']['direction']} ({result['h100']['trend'].get('change_pct', 'N/A')}%)")
    
    return result


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
    
    data = fetch_and_parse()
    
    if data:
        update_market_data(data)
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"H100 1Y Contract: {data['h100']['1y_contract']['display']}")
        print(f"As-of Period: {data['h100']['period']}")
        print(f"Trend: {data['h100']['trend']['direction']}")
        print(f"On-Demand Status: {data['h100']['on_demand']['display']}")
    else:
        print("\n✗ Failed to fetch GPU index data")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
