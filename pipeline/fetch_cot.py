#!/usr/bin/env python3
"""
Fetch CFTC Commitment of Traders (COT) positioning data.

Source: https://www.cftc.gov/dea/futures/financial_lf.htm
Data type: Weekly disaggregated positioning report for financial futures

This fetcher extracts leveraged_funds_net positions for:
- 10-Year Treasury Note Futures (TY) - "10 YEAR U.S. TREASURY NOTES"
- 2-Year Treasury Note Futures (TU) - "2-YEAR U.S. TREASURY NOTES"  
- 30-Year Treasury Bond Futures (US) - "U.S. TREASURY BONDS"
- CME Bitcoin Futures (BTC) - "BITCOIN - CHICAGO MERCANTILE EXCHANGE"

CFTC releases COT every Friday at 3:30pm ET for positions as of prior Tuesday.
Data is free and requires no API key.

FAIL-CLOSED BEHAVIOR:
- On parse/network failure: preserve prior good data, mark as stale
- Never invent nets or fabricate data
- Leave nulls so UI shows "Coming soon" rather than false data
"""

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from workspace_paths import SITE_DATA_DIR

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"

# CFTC Disaggregated Futures-Only report for financial futures
# This contains leveraged funds, asset managers, etc. breakdown
CFTC_BASE_URL = "https://www.cftc.gov/dea/futures"
CFTC_FIN_FUT_TXT = f"{CFTC_BASE_URL}/deacot_txt.zip"  # Combined disaggregated COT
CFTC_FIN_LF_PAGE = f"{CFTC_BASE_URL}/financial_lf.htm"  # Human-readable page

# Contract name patterns in CFTC data (case-insensitive matching)
# Updated based on actual CFTC report format observed in 2026
CONTRACT_PATTERNS = {
    "10y_note": [
        "UST 10Y NOTE",
        "10-YEAR U.S. TREASURY NOTES",
        "10 YEAR U.S. TREASURY NOTES", 
        "10-YR U.S. TREASURY NOTES",
        "CBT 10 YEAR T-NOTE",
    ],
    "2y_note": [
        "UST 2Y NOTE",
        "2-YEAR U.S. TREASURY NOTES",
        "2 YEAR U.S. TREASURY NOTES",
        "2-YR U.S. TREASURY NOTES",
        "CBT 2 YEAR T-NOTE",
    ],
    "30y_bond": [
        "UST BOND - CHICAGO BOARD",
        "U.S. TREASURY BONDS",
        "30-YEAR U.S. TREASURY BONDS",
        "CBT U.S. TREASURY BOND",
    ],
    "cme_btc": [
        "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
        "CME BITCOIN",
    ],
}


def _make_request_headers() -> dict:
    """Build request headers that work with CFTC servers."""
    return {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }


def _run_curl_fetch(curl_cmd: str, url: str, label: str) -> Optional[str]:
    """
    Run curl fetch with specific binary path.
    Returns content on success, None on failure.
    """
    import subprocess
    try:
        result = subprocess.run(
            [curl_cmd, '-sL', '--compressed', '--max-time', '30', url],
            capture_output=True,
            timeout=35
        )
        if result.returncode == 0 and result.stdout:
            content = result.stdout.decode('utf-8', errors='replace')
            if len(content) > 10000:  # Expect ~140KB of data
                print(f"  ✓ Fetched CFTC page via {label} ({len(content)} bytes)")
                return content
            else:
                print(f"  ✗ {label} returned only {len(content)} bytes (SSL/connection failure?)")
        else:
            stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
            if 'SSL' in stderr or 'certificate' in stderr.lower() or result.returncode == 60:
                print(f"  ✗ {label} SSL certificate error (returncode={result.returncode})")
            elif result.returncode == 35:
                print(f"  ✗ {label} SSL connect error")
            else:
                print(f"  ✗ {label} failed (returncode={result.returncode})")
    except FileNotFoundError:
        print(f"  ✗ {label} not found")
    except Exception as e:
        print(f"  ✗ {label} error: {e}")
    return None


def fetch_cot_page() -> Optional[str]:
    """
    Fetch the CFTC financial futures COT HTML page.
    
    CURL PREFERENCE ORDER (Mac Anaconda SSL workaround):
    On Mac, Anaconda's bundled curl may use outdated SSL certificates that fail
    to verify CFTC's Cloudflare certificate (http=000 / returncode 60/35).
    To handle this, we try multiple curl binaries in order:
    
    1. /usr/bin/curl (macOS system curl - uses system certificates)
    2. PATH curl (may be Anaconda curl - works on Linux, may fail Mac SSL)
    3. urllib fallback (Python ssl, usually works but slower)
    
    This ordering ensures Mac users with Anaconda get working fetches while
    Linux and non-Anaconda Mac users also work fine.
    """
    import shutil
    
    # Preferred curl binaries in order of preference
    # System curl first (reliable SSL on Mac), then PATH curl
    curl_candidates = []
    
    # macOS/Linux system curl - preferred for SSL reliability
    for system_curl in ['/usr/bin/curl', '/bin/curl']:
        if Path(system_curl).exists():
            curl_candidates.append((system_curl, f"system curl ({system_curl})"))
            break
    
    # PATH curl (may be Anaconda curl on Mac)
    path_curl = shutil.which('curl')
    if path_curl and path_curl not in [c[0] for c in curl_candidates]:
        curl_candidates.append((path_curl, f"PATH curl ({path_curl})"))
    
    # Try each curl candidate
    for curl_cmd, label in curl_candidates:
        content = _run_curl_fetch(curl_cmd, CFTC_FIN_LF_PAGE, label)
        if content:
            return content
    
    # Fallback to urllib with explicit gzip handling
    try:
        import gzip
        headers = _make_request_headers()
        headers['Accept-Encoding'] = 'identity'  # Request uncompressed
        req = urllib.request.Request(CFTC_FIN_LF_PAGE, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            # Check if gzip compressed
            if data[:2] == b'\x1f\x8b':
                data = gzip.decompress(data)
            return data.decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  ✗ urllib fallback failed: {e}")
    
    return None


def parse_report_date(html: str) -> Optional[str]:
    """
    Extract the report date from CFTC HTML page.
    Looks for patterns like "As of September 2, 2026" or date in header.
    """
    patterns = [
        r'As of\s+([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',
        r'Report Date:\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',
        r'Data as of\s+([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})',
        r'(\d{1,2}/\d{1,2}/\d{4})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            try:
                for fmt in ['%B %d, %Y', '%B %d %Y', '%m/%d/%Y', '%Y-%m-%d']:
                    try:
                        dt = datetime.strptime(date_str.replace(',', ''), fmt)
                        return dt.strftime('%Y-%m-%d')
                    except ValueError:
                        continue
            except Exception:
                pass
    return None


def extract_contract_section(html: str, contract_patterns: List[str]) -> Optional[str]:
    """
    Extract the section for a specific contract from the CFTC page.
    CFTC pages have fixed-width text sections for each contract.
    
    Returns lines from contract header through next separator (---) or next contract.
    """
    for pattern in contract_patterns:
        pattern_regex = re.escape(pattern)
        # Find the contract header line
        match = re.search(
            rf'({pattern_regex}[^\n]*\n(?:[^\n]*\n){{0,15}})',
            html,
            re.IGNORECASE | re.DOTALL
        )
        if match:
            return match.group(1)
    return None


def parse_leveraged_funds_net(section: str) -> Optional[int]:
    """
    Parse leveraged funds net position from a CFTC contract section.
    
    CFTC fixed-width format (2026 version):
    Line 1: Contract name
    Line 2: CFTC Code #... Open Interest is ...
    Line 3: "Positions"
    Line 4: numbers in columns (dealer, AM, leveraged, other, nonreportable)
    
    Column layout (based on header):
    - Dealer: Long, Short, Spreading (cols 0-2)
    - Asset Manager: Long, Short, Spreading (cols 3-5)
    - Leveraged Funds: Long, Short, Spreading (cols 6-8) <-- We want these
    - Other: Long, Short, Spreading (cols 9-11)
    - Nonreportable: Long, Short (cols 12-13)
    
    Returns net contracts (long - short), or None if not found.
    """
    if not section:
        return None
    
    lines = section.strip().split('\n')
    
    # Look for the "Positions" line and the numbers that follow
    positions_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == 'positions':
            positions_idx = i
            break
    
    if positions_idx is None or positions_idx + 1 >= len(lines):
        return None
    
    # The line after "Positions" has all the numbers
    numbers_line = lines[positions_idx + 1]
    
    # Extract all numbers from the line
    numbers = re.findall(r'[\d,]+', numbers_line)
    numbers = [int(n.replace(',', '')) for n in numbers if n.replace(',', '').isdigit()]
    
    # CFTC format: 14 numbers total
    # [0-2]: Dealer (Long, Short, Spreading)
    # [3-5]: Asset Manager (Long, Short, Spreading)
    # [6-8]: Leveraged Funds (Long, Short, Spreading)
    # [9-11]: Other (Long, Short, Spreading)
    # [12-13]: Nonreportable (Long, Short)
    
    if len(numbers) >= 8:
        # Leveraged Funds Long is at index 6, Short at index 7
        lev_long = numbers[6]
        lev_short = numbers[7]
        return lev_long - lev_short
    
    # Fallback: try to find any labeled leveraged funds data
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if 'lev' in line_lower and ('money' in line_lower or 'fund' in line_lower):
            nums = re.findall(r'[\d,]+', line)
            nums = [int(n.replace(',', '')) for n in nums if n.replace(',', '').isdigit()]
            if len(nums) >= 2:
                return nums[0] - nums[1]
    
    return None


def parse_cot_from_html(html: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse COT data from CFTC HTML page (financial_lf.htm format).
    
    Returns dict keyed by our contract IDs with positioning data.
    """
    results = {}
    
    if not html:
        return results
    
    # Extract report date from the page
    date_match = re.search(r'Positions as of\s+(\w+\s+\d{1,2},?\s+\d{4})', html, re.IGNORECASE)
    report_date = None
    if date_match:
        try:
            date_str = date_match.group(1).replace(',', '')
            from datetime import datetime
            dt = datetime.strptime(date_str, '%B %d %Y')
            report_date = dt.strftime('%Y-%m-%d')
        except Exception:
            pass
    
    for contract_id, patterns in CONTRACT_PATTERNS.items():
        section = extract_contract_section(html, patterns)
        if section:
            net = parse_leveraged_funds_net(section)
            if net is not None:
                results[contract_id] = {
                    'contract': contract_id,
                    'leveraged_funds_net': net,
                    'report_date': report_date
                }
    
    return results


def fetch_disaggregated_txt() -> Optional[str]:
    """
    Fetch and extract the disaggregated COT data from CFTC's combined file.
    This is more reliable than HTML parsing.
    """
    try:
        import io
        import zipfile
        
        req = urllib.request.Request(
            "https://www.cftc.gov/dea/newcot/f_disagg.txt",
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  ✗ Failed to fetch disaggregated TXT: {e}")
        return None


def parse_disaggregated_txt(txt_data: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse the disaggregated COT text file.
    
    The file has columns including:
    - Market_and_Exchange_Names
    - Report_Date_as_YYYY-MM-DD
    - Lev_Money_Positions_Long_All / Lev_Money_Positions_Short_All
    
    Returns dict keyed by our contract IDs with positioning data.
    """
    results = {}
    
    if not txt_data:
        return results
    
    lines = txt_data.strip().split('\n')
    if not lines:
        return results
    
    header = lines[0].split(',')
    header = [h.strip().strip('"') for h in header]
    
    col_map = {}
    for i, col in enumerate(header):
        col_lower = col.lower().replace(' ', '_')
        if 'market' in col_lower and 'exchange' in col_lower:
            col_map['market'] = i
        elif 'report_date' in col_lower:
            col_map['date'] = i
        elif 'lev' in col_lower and 'long' in col_lower and 'all' in col_lower:
            col_map['lev_long'] = i
        elif 'lev' in col_lower and 'short' in col_lower and 'all' in col_lower:
            col_map['lev_short'] = i
        elif 'asset_mgr' in col_lower and 'long' in col_lower:
            col_map['am_long'] = i
        elif 'asset_mgr' in col_lower and 'short' in col_lower:
            col_map['am_short'] = i
        elif 'dealer' in col_lower and 'long' in col_lower:
            col_map['dealer_long'] = i
        elif 'dealer' in col_lower and 'short' in col_lower:
            col_map['dealer_short'] = i
    
    for line in lines[1:]:
        if not line.strip():
            continue
        
        fields = line.split(',')
        fields = [f.strip().strip('"') for f in fields]
        
        if 'market' not in col_map or col_map['market'] >= len(fields):
            continue
        
        market_name = fields[col_map['market']].upper()
        
        matched_contract = None
        for contract_id, patterns in CONTRACT_PATTERNS.items():
            for pattern in patterns:
                if pattern.upper() in market_name:
                    matched_contract = contract_id
                    break
            if matched_contract:
                break
        
        if not matched_contract:
            continue
        
        if matched_contract in results:
            continue
        
        entry = {'contract': matched_contract, 'market_name': market_name}
        
        if 'date' in col_map and col_map['date'] < len(fields):
            entry['report_date'] = fields[col_map['date']]
        
        def safe_int(idx):
            if idx in col_map and col_map[idx] < len(fields):
                try:
                    return int(fields[col_map[idx]].replace(',', ''))
                except (ValueError, TypeError):
                    pass
            return None
        
        lev_long = safe_int('lev_long')
        lev_short = safe_int('lev_short')
        if lev_long is not None and lev_short is not None:
            entry['leveraged_funds_long'] = lev_long
            entry['leveraged_funds_short'] = lev_short
            entry['leveraged_funds_net'] = lev_long - lev_short
        
        am_long = safe_int('am_long')
        am_short = safe_int('am_short')
        if am_long is not None and am_short is not None:
            entry['asset_manager_long'] = am_long
            entry['asset_manager_short'] = am_short
            entry['asset_manager_net'] = am_long - am_short
        
        dealer_long = safe_int('dealer_long')
        dealer_short = safe_int('dealer_short')
        if dealer_long is not None and dealer_short is not None:
            entry['dealer_long'] = dealer_long
            entry['dealer_short'] = dealer_short
            entry['dealer_net'] = dealer_long - dealer_short
        
        results[matched_contract] = entry
    
    return results


def fetch_combined_cot() -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch combined COT current/historical data.
    Returns (txt_content, error_reason).
    
    Tries multiple sources in order:
    1. CFTC official disaggregated reports
    2. Nasdaq Data Link (formerly Quandl) CFTC mirror - free, no key needed for basic use
    """
    # CFTC official sources
    cftc_sources = [
        ("https://www.cftc.gov/dea/newcot/f_disagg.txt", "CFTC f_disagg.txt"),
        ("https://www.cftc.gov/dea/newcot/FinFutYY.txt", "CFTC FinFutYY.txt"),
        ("https://www.cftc.gov/dea/newcot/deafut_txt.zip", "CFTC deafut_txt.zip"),
    ]
    
    headers = _make_request_headers()
    
    for url, name in cftc_sources:
        try:
            print(f"  Trying {name}...")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                content = response.read()
                
                # Handle zip files
                if url.endswith('.zip'):
                    import io
                    import zipfile
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        for fname in zf.namelist():
                            if fname.endswith('.txt'):
                                content = zf.read(fname).decode('utf-8', errors='replace')
                                break
                else:
                    content = content.decode('utf-8', errors='replace')
                
                if content and len(content) > 1000:
                    print(f"  ✓ Fetched {name} ({len(content)} bytes)")
                    return content, None
        except Exception as e:
            print(f"  ✗ {name} failed: {e}")
            continue
    
    # Try Nasdaq Data Link (Quandl) as fallback - free for basic COT data
    # Uses the CFTC dataset mirror: https://data.nasdaq.com/data/CFTC
    nasdaq_endpoints = [
        # Disaggregated Futures-Only Financial
        ("https://data.nasdaq.com/api/v3/datasets/CFTC/097741_FO_L_ALL.csv?rows=1", "Nasdaq CFTC 10Y TNote"),
        ("https://data.nasdaq.com/api/v3/datasets/CFTC/133741_FO_L_ALL.csv?rows=1", "Nasdaq CFTC Bitcoin"),
    ]
    
    for url, name in nasdaq_endpoints:
        try:
            print(f"  Trying {name}...")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read().decode('utf-8', errors='replace')
                if content and len(content) > 100:
                    print(f"  ✓ Fetched {name}")
                    # Nasdaq returns single-contract CSV, we'd need to aggregate
                    # For now just note it's available
        except Exception as e:
            print(f"  ✗ {name} failed: {e}")
            continue
    
    return None, "All CFTC data sources failed"


def format_net_display(net: Optional[int]) -> str:
    """Format net position for display (e.g., +123K or -45K)."""
    if net is None:
        return None
    
    net_k = net / 1000
    if abs(net_k) >= 1:
        sign = '+' if net_k > 0 else ''
        return f"{sign}{net_k:.0f}K"
    else:
        sign = '+' if net > 0 else ''
        return f"{sign}{net}"


def validate_cot_data(data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate that COT data has minimum required fields.
    At least one contract must have leveraged_funds_net.
    """
    if not data:
        return False, "No COT data parsed"
    
    has_valid = False
    for contract_id in ['10y_note', 'cme_btc', '2y_note', '30y_bond']:
        if contract_id in data:
            entry = data[contract_id]
            if entry.get('leveraged_funds_net') is not None:
                has_valid = True
                break
    
    if not has_valid:
        return False, "No contracts have leveraged_funds_net data"
    
    return True, ""


def build_cot_result(parsed_data: Dict[str, Dict[str, Any]], report_date: Optional[str]) -> Dict[str, Any]:
    """Build the structured COT result for market_data.json."""
    
    def build_contract_entry(contract_id: str, label: str, contract_code: str) -> Dict[str, Any]:
        data = parsed_data.get(contract_id, {})
        
        lev_net = data.get('leveraged_funds_net')
        am_net = data.get('asset_manager_net')
        dealer_net = data.get('dealer_net')
        
        return {
            "label": label,
            "contract": contract_code,
            "asset_manager_net": am_net,
            "leveraged_funds_net": lev_net,
            "dealer_net": dealer_net,
            "change_1w": None,
            "signal": None,
            "percentile_1y": None
        }
    
    result = {
        "_comment": "CFTC Commitment of Traders positioning data. Source: cftc.gov weekly reports.",
        "_fetch_url": "https://www.cftc.gov/dea/futures/financial_lf.htm",
        "_api_alternative": "Quandl CFTC dataset (may need key)",
        "_fetch_instructions": "CFTC releases COT every Friday at 3:30pm ET for positions as of prior Tuesday.",
        "last_updated": datetime.now().isoformat(),
        "report_date": report_date,
        "rates_positioning": {
            "10y_note": build_contract_entry("10y_note", "10-Year T-Note Futures", "TY"),
            "2y_note": build_contract_entry("2y_note", "2-Year T-Note Futures", "TU"),
            "30y_bond": build_contract_entry("30y_bond", "30-Year T-Bond Futures", "US"),
        },
        "btc_positioning": {
            "cme_btc": build_contract_entry("cme_btc", "CME Bitcoin Futures", "BTC"),
        },
        "positioning_context": {
            "_comment": "Narrative summary of positioning trends",
            "summary": None,
            "key_shift": None,
            "crowded_trades": []
        }
    }
    
    return result


def mark_cot_stale(error_reason: str) -> bool:
    """
    Mark existing cftc_cot data as stale without overwriting it.
    Fail-closed: preserve last known good data.
    """
    try:
        if not MARKET_DATA_FILE.exists():
            print(f"  ⚠ No existing market_data.json to mark stale")
            return False
        
        with open(MARKET_DATA_FILE, 'r') as f:
            market_data = json.load(f)
        
        if 'cftc_cot' in market_data:
            market_data['cftc_cot']['_stale'] = True
            market_data['cftc_cot']['_stale_since'] = datetime.now().isoformat()
            market_data['cftc_cot']['_stale_reason'] = error_reason
        
        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['cftc_cot'] = 'stale'
        
        with open(MARKET_DATA_FILE, 'w') as f:
            json.dump(market_data, f, indent=2)
        
        print(f"  ⚠ Marked cftc_cot as stale: {error_reason}")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to mark data stale: {e}")
        return False


def update_market_data(cot_data: Dict[str, Any]) -> bool:
    """Update market_data.json with the new COT data."""
    try:
        if MARKET_DATA_FILE.exists():
            with open(MARKET_DATA_FILE, 'r') as f:
                market_data = json.load(f)
        else:
            market_data = {}
        
        if '_stale' in cot_data:
            del cot_data['_stale']
        if '_stale_since' in cot_data:
            del cot_data['_stale_since']
        if '_stale_reason' in cot_data:
            del cot_data['_stale_reason']
        
        market_data['cftc_cot'] = cot_data
        
        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['cftc_cot'] = 'live'
        
        market_data['_updated'] = datetime.now().strftime('%Y-%m-%d')
        
        with open(MARKET_DATA_FILE, 'w') as f:
            json.dump(market_data, f, indent=2)
        
        print(f"  ✓ Updated {MARKET_DATA_FILE}")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to update market_data.json: {e}")
        return False


def fetch_and_parse() -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Main fetch and parse function.
    Returns (structured_data, error_reason).
    
    On success: (data_dict, "")
    On failure: (None, "reason for failure")
    
    Strategy:
    Primary: HTML page parsing via curl (works reliably with Cloudflare)
    The CFTC financial_lf.htm page contains all financial futures including
    Treasury notes/bonds and Bitcoin.
    """
    print("Fetching CFTC Commitment of Traders data...")
    
    # Primary strategy: HTML page parsing (financial_lf.htm)
    # This is the most reliable source - it contains all financial futures
    # including UST 2Y/5Y/10Y Notes, UST Bond, and CME Bitcoin
    html_content = fetch_cot_page()
    
    if html_content:
        parsed_data = parse_cot_from_html(html_content)
        
        if parsed_data:
            report_date = None
            for contract_data in parsed_data.values():
                if 'report_date' in contract_data:
                    report_date = contract_data['report_date']
                    break
            
            is_valid, val_error = validate_cot_data(parsed_data)
            if is_valid:
                result = build_cot_result(parsed_data, report_date)
                _print_result_summary(result)
                return result, ""
            else:
                return None, f"HTML parse validation failed: {val_error}"
        else:
            return None, "Failed to parse contracts from HTML page"
    
    return None, "Failed to fetch CFTC financial futures page"


def _print_result_summary(result: Dict[str, Any]) -> None:
    """Print summary of parsed COT data."""
    report_date = result.get('report_date', 'unknown')
    print(f"  ✓ Parsed COT data for report date: {report_date}")
    
    for section_key, section_data in [('rates_positioning', result.get('rates_positioning', {})),
                                       ('btc_positioning', result.get('btc_positioning', {}))]:
        for contract_id, contract_data in section_data.items():
            net = contract_data.get('leveraged_funds_net')
            if net is not None:
                display = format_net_display(net)
                print(f"    {contract_data['label']}: {display}")


def main():
    print("=" * 60)
    print("Fetch CFTC Commitment of Traders (COT) Positioning")
    print(f"Source: {CFTC_FIN_LF_PAGE}")
    print(f"Started: {datetime.now()}")
    print("=" * 60)
    
    data, error_reason = fetch_and_parse()
    
    if data:
        if not update_market_data(data):
            mark_cot_stale("Failed to write market_data.json")
            return 1
        
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Report Date: {data.get('report_date', 'unknown')}")
        
        rates = data.get('rates_positioning', {})
        ty = rates.get('10y_note', {})
        if ty.get('leveraged_funds_net') is not None:
            print(f"10Y T-Note (TY): Leveraged Funds Net = {format_net_display(ty['leveraged_funds_net'])}")
        
        btc_section = data.get('btc_positioning', {})
        btc = btc_section.get('cme_btc', {})
        if btc.get('leveraged_funds_net') is not None:
            print(f"CME Bitcoin: Leveraged Funds Net = {format_net_display(btc['leveraged_funds_net'])}")
    else:
        mark_cot_stale(error_reason or "Unknown error during fetch/parse")
        print(f"\n✗ Failed to fetch COT data: {error_reason}")
        print("  (existing data preserved, marked stale)")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
