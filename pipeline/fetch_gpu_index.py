#!/usr/bin/env python3
"""
Fetch GPU rental pricing data from SemiAnalysis GPU Index public API.

Source: https://gpu-index.semianalysis.com/api/public-data
Data type: Daily spot-contract composite index + periodic contract ranges

This fetcher extracts from the JSON API:
- H100 daily Spot-Contract Composite from `index` (PRIMARY metric, e.g., $3.29)
- H100 1-year contract range from `contract` (SECONDARY, e.g., $2.40-3.20)
- B200 daily composite from `index` (Watch line)
- On-demand sold-out periods from `contract.soldOutPeriods`
- Daily index date + latest contract period for as-of awareness

TREND CALCULATION:
For the daily index, trend compares latest day vs 7 days prior (week-over-week).
For contract ranges, trend compares latest period vs prior period (period-over-period).
Longer-term trend anchors ~30 days back for daily, ~6 periods back for contract.

All numeric values are rounded at the data boundary (2 decimal places for prices,
1 decimal place for percentages) to prevent floating point noise from reaching the page.
"""

import json
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from workspace_paths import SITE_DATA_DIR

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"
API_URL = "https://gpu-index.semianalysis.com/api/public-data"
SOURCE_URL = "https://gpu-index.semianalysis.com/"


def fetch_public_data() -> Optional[Dict[str, Any]]:
    """Fetch JSON from the SemiAnalysis public-data API."""
    try:
        req = urllib.request.Request(
            API_URL,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"  ✗ Failed to fetch public-data API: {e}")
        return None


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse API date string like 'Sun, 20 Sep 2026 00:00:00 GMT'."""
    try:
        return datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S GMT')
    except (ValueError, TypeError):
        return None


def format_date_short(dt: datetime) -> str:
    """Format datetime as 'Sep 20, 2026'."""
    return dt.strftime('%b %d, %Y')


def normalize_price_value(raw: Any) -> Dict[str, Any]:
    """
    Normalize a price value into structured data.
    Handles: [low, high] ranges, single floats, None.
    """
    if raw is None:
        return {'display': '—', 'type': 'unavailable'}
    
    if isinstance(raw, list) and len(raw) == 2:
        low, high = round(raw[0], 2), round(raw[1], 2)
        return {
            'display': f'${low:.2f}-{high:.2f}',
            'type': 'range',
            'low': low,
            'high': high,
            'midpoint': round((low + high) / 2, 2)
        }
    
    if isinstance(raw, (int, float)):
        value = round(float(raw), 2)
        return {
            'display': f'${value:.2f}',
            'type': 'single',
            'value': value
        }
    
    return {'display': str(raw), 'type': 'unknown'}


def compute_daily_trend(index_data: List[Dict], sku: str = 'h100') -> Dict[str, Any]:
    """
    Compute trend for daily index data.
    
    Returns dual-horizon comparison:
    1. Short-term: latest vs 7 days prior (week-over-week)
    2. Long-term: latest vs ~30 days prior
    """
    valid_points = []
    for entry in index_data:
        value = entry.get(sku)
        date = parse_date(entry.get('date', ''))
        if value is not None and date is not None:
            valid_points.append({
                'date': date,
                'value': round(value, 2)
            })
    
    valid_points.sort(key=lambda x: x['date'])
    
    if len(valid_points) < 2:
        return {'insufficient_data': True, 'data_points': len(valid_points)}
    
    latest = valid_points[-1]
    
    def find_closest_to_days_ago(target_days: int):
        target_date = latest['date'] - timedelta(days=target_days)
        closest = None
        closest_diff = float('inf')
        for point in valid_points[:-1]:
            diff = abs((point['date'] - target_date).days)
            if diff < closest_diff:
                closest = point
                closest_diff = diff
        return closest, closest_diff
    
    week_ago, week_diff = find_closest_to_days_ago(7)
    
    if week_ago is None or week_ago['value'] <= 0:
        return {'insufficient_data': True, 'data_points': len(valid_points),
                'reason': 'no valid week-ago comparison point'}
    
    short_pct = round(((latest['value'] - week_ago['value']) / week_ago['value']) * 100, 1)
    
    result = {
        'data_points': len(valid_points),
        'latest_value': latest['value'],
        'latest_date': format_date_short(latest['date']),
        'short_term': {
            'change_pct': short_pct,
            'comparison_date': format_date_short(week_ago['date']),
            'comparison_value': week_ago['value'],
            'days_back': (latest['date'] - week_ago['date']).days
        }
    }
    
    month_ago, month_diff = find_closest_to_days_ago(30)
    if month_ago and month_ago != week_ago and month_ago['value'] > 0:
        long_pct = round(((latest['value'] - month_ago['value']) / month_ago['value']) * 100, 1)
        result['long_term'] = {
            'change_pct': long_pct,
            'anchor_date': format_date_short(month_ago['date']),
            'anchor_value': month_ago['value'],
            'days_back': (latest['date'] - month_ago['date']).days
        }
    
    result['change_pct'] = short_pct
    result['comparison_date'] = result['short_term']['comparison_date']
    
    return result


def compute_contract_trend(contract_data: List[Dict]) -> Dict[str, Any]:
    """
    Compute trend for contract range data (1-year commitment prices).
    Uses midpoint of ranges for comparison.
    """
    valid_points = []
    for entry in contract_data:
        one_y = entry.get('1y')
        period = entry.get('period', '')
        if one_y and isinstance(one_y, list) and len(one_y) == 2:
            low, high = one_y
            midpoint = round((low + high) / 2, 2)
            valid_points.append({
                'period': period,
                'value': midpoint,
                'low': round(low, 2),
                'high': round(high, 2),
                'display': f'${low:.2f}-{high:.2f}'
            })
    
    if len(valid_points) < 2:
        return {'insufficient_data': True, 'data_points': len(valid_points)}
    
    latest = valid_points[-1]
    previous = valid_points[-2]
    
    if previous['value'] <= 0:
        return {'insufficient_data': True, 'data_points': len(valid_points),
                'reason': 'previous period value is zero or negative'}
    
    short_pct = round(((latest['value'] - previous['value']) / previous['value']) * 100, 1)
    
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
    
    if len(valid_points) >= 7:
        anchor_index = -7
    else:
        anchor_index = 0
    
    anchor = valid_points[anchor_index]
    
    if anchor['period'] != previous['period'] and anchor['value'] > 0:
        long_pct = round(((latest['value'] - anchor['value']) / anchor['value']) * 100, 1)
        if anchor_index < 0:
            row_intervals = abs(anchor_index) - 1
        else:
            row_intervals = len(valid_points) - 1 - anchor_index
        
        result['long_term'] = {
            'change_pct': long_pct,
            'anchor_period': anchor['period'],
            'anchor_value': anchor['value'],
            'anchor_display': anchor['display'],
            'row_intervals': row_intervals
        }
    
    result['change_pct'] = short_pct
    result['comparison_period'] = previous['period']
    result['comparison_value'] = previous['value']
    result['comparison_display'] = previous['display']
    
    return result


def extract_h100_contract(api_data: Dict) -> Optional[Dict]:
    """Extract H100 contract data from API response."""
    contracts = api_data.get('contract', [])
    for contract in contracts:
        if contract.get('sku', '').upper() == 'H100':
            return contract
    return None


def validate_parsed_result(result: Dict[str, Any]) -> tuple:
    """
    Validate that a parsed result has all required fields with valid data.
    Returns (is_valid, error_reason).
    """
    if not result:
        return False, "result is None"
    
    h100 = result.get('h100', {})
    
    daily_date = h100.get('daily_date', '')
    if not daily_date:
        return False, "H100 daily_date is missing"
    
    composite = h100.get('composite_index', {})
    if composite.get('type') not in ('single',):
        return False, f"H100 composite_index type is '{composite.get('type')}', expected single"
    
    daily_trend = h100.get('daily_trend', {})
    if daily_trend.get('insufficient_data'):
        return False, f"H100 daily_trend has insufficient data: {daily_trend.get('reason', 'unknown')}"
    
    return True, ""


def fetch_and_parse() -> tuple:
    """
    Main fetch and parse function.
    Returns (structured_data, error_reason) tuple.
    """
    print("Fetching SemiAnalysis GPU Index public API...")
    print(f"  URL: {API_URL}")
    
    api_data = fetch_public_data()
    if not api_data:
        return None, "Network error: failed to fetch API"
    
    if api_data.get('status') != 'ok':
        return None, f"API error: status={api_data.get('status', 'unknown')}"
    
    index_data = api_data.get('index', [])
    if not index_data:
        return None, "Parse error: no index data in API response"
    
    h100_contract = extract_h100_contract(api_data)
    if not h100_contract:
        return None, "Parse error: H100 contract data not found"
    
    contract_data = h100_contract.get('data', [])
    sold_out_periods = h100_contract.get('soldOutPeriods', {}).get('onDemand', [])
    
    latest_index = index_data[-1] if index_data else {}
    latest_h100_daily = latest_index.get('h100')
    latest_b200_daily = latest_index.get('b200')
    latest_date = parse_date(latest_index.get('date', ''))
    
    if latest_h100_daily is None or latest_date is None:
        return None, "Parse error: latest H100 daily value not found"
    
    daily_trend = compute_daily_trend(index_data, 'h100')
    contract_trend = compute_contract_trend(contract_data)
    
    latest_contract = contract_data[-1] if contract_data else {}
    latest_contract_period = latest_contract.get('period', 'unknown')
    latest_1y = latest_contract.get('1y')
    latest_on_demand = latest_contract.get('onDemand')
    
    on_demand_status = {'display': '—', 'type': 'unavailable'}
    if latest_contract_period in sold_out_periods:
        on_demand_status = {'display': 'Sold Out', 'type': 'sold_out', 'period': latest_contract_period}
    elif latest_on_demand:
        on_demand_status = normalize_price_value(latest_on_demand)
        on_demand_status['period'] = latest_contract_period
    
    history_summary_recent = []
    for entry in contract_data[-5:]:
        period = entry.get('period', '')
        one_y = entry.get('1y')
        od = entry.get('onDemand')
        
        one_y_display = normalize_price_value(one_y).get('display', '—')
        if period in sold_out_periods:
            od_display = 'Sold Out'
        else:
            od_display = normalize_price_value(od).get('display', '—')
        
        history_summary_recent.append({
            'period': period,
            '1y_contract': one_y_display,
            'on_demand': od_display
        })
    
    result = {
        '_comment': 'GPU rental pricing from SemiAnalysis public API. Daily spot-contract composite + periodic contract ranges.',
        '_source_url': SOURCE_URL,
        '_api_url': API_URL,
        '_data_type': 'api_index',
        'last_fetched': datetime.now().isoformat(),
        
        'h100': {
            'daily_date': format_date_short(latest_date),
            'daily_date_iso': latest_date.strftime('%Y-%m-%d'),
            'composite_index': normalize_price_value(latest_h100_daily),
            'contract_period': latest_contract_period,
            '1y_contract': normalize_price_value(latest_1y),
            'on_demand': on_demand_status,
            'sold_out_periods': sold_out_periods,
            'daily_trend': daily_trend,
            'contract_trend': contract_trend,
            'trend': contract_trend,
            'period': latest_contract_period
        },
        
        'b200': {
            'daily_date': format_date_short(latest_date),
            'composite_index': normalize_price_value(latest_b200_daily)
        },
        
        'history_summary': {
            'oldest_period': contract_data[0]['period'] if contract_data else None,
            'newest_period': latest_contract_period,
            'newest_daily': format_date_short(latest_date),
            'total_daily_points': len(index_data),
            'total_contract_periods': len(contract_data),
            'recent_5': history_summary_recent
        }
    }
    
    is_valid, error_reason = validate_parsed_result(result)
    if not is_valid:
        return None, f"Validation error: {error_reason}"
    
    print(f"  ✓ Fetched H100 data:")
    print(f"    Daily Composite: {result['h100']['composite_index']['display']} (as of {result['h100']['daily_date']})")
    print(f"    1Y Contract: {result['h100']['1y_contract']['display']} ({result['h100']['contract_period']})")
    print(f"    On-Demand: {result['h100']['on_demand']['display']}")
    
    dt = result['h100']['daily_trend']
    if dt.get('short_term'):
        short = dt['short_term']
        trend_str = f"{short['change_pct']:+.1f}% vs {short['comparison_date']}"
        if dt.get('long_term'):
            lt = dt['long_term']
            trend_str += f" · {lt['change_pct']:+.1f}% vs {lt['anchor_date']}"
        print(f"    Daily Trend: {trend_str}")
    
    return result, ""


def _rollup_data_status(market_data: Dict[str, Any]) -> str:
    """
    Compute top-level _data_status from individual data_fetch_status values.
    """
    status = market_data.get('data_fetch_status', {})
    auto_sections = ['curve_data', 'cftc_cot', 'compute_forward']
    
    live_count = 0
    stale_count = 0
    stub_count = 0
    
    for section in auto_sections:
        val = status.get(section, 'stub')
        if val == 'live':
            live_count += 1
        elif val == 'stale':
            stale_count += 1
        else:
            stub_count += 1
    
    total = len(auto_sections)
    
    if live_count == total:
        return 'live'
    elif live_count > 0:
        return 'partial'
    elif stale_count > 0:
        return 'stale'
    else:
        return 'stub'


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
        
        market_data['_data_status'] = _rollup_data_status(market_data)
        
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
        
        if '_stale' in gpu_data:
            del gpu_data['_stale']
        if '_stale_since' in gpu_data:
            del gpu_data['_stale_since']
        if '_stale_reason' in gpu_data:
            del gpu_data['_stale_reason']
        
        market_data['compute_forward'] = gpu_data
        
        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['compute_forward'] = 'live'
        
        market_data['_data_status'] = _rollup_data_status(market_data)
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
    print("Fetch SemiAnalysis GPU Rental Pricing Index (API)")
    print(f"Source: {API_URL}")
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
        print(f"H100 Daily Composite: {data['h100']['composite_index']['display']}")
        print(f"As-of Daily: {data['h100']['daily_date']}")
        print(f"H100 1Y Contract: {data['h100']['1y_contract']['display']}")
        print(f"As-of Contract: {data['h100']['contract_period']}")
        dt = data['h100']['daily_trend']
        if dt.get('short_term'):
            short = dt['short_term']
            trend_str = f"{short['change_pct']:+.1f}% vs {short['comparison_date']}"
            if dt.get('long_term'):
                lt = dt['long_term']
                trend_str += f" · {lt['change_pct']:+.1f}% vs {lt['anchor_date']}"
            print(f"Daily Trend: {trend_str}")
        print(f"On-Demand Status: {data['h100']['on_demand']['display']}")
        if data['h100'].get('sold_out_periods'):
            print(f"Sold-Out Periods: {', '.join(data['h100']['sold_out_periods'])}")
    else:
        mark_data_stale(error_reason or "Unknown error during fetch/parse")
        print(f"\n✗ Failed to fetch GPU index data: {error_reason}")
        print("  (existing data preserved, marked stale)")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
