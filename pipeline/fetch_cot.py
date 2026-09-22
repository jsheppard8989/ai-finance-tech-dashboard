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

from workspace_paths import SITE_DATA_DIR, STATE_DIR

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"

from market_data_io import load_market_data, save_market_data  # fail-closed I/O
COT_PRIOR_NETS_FILE = STATE_DIR / "cot_prior_nets.json"

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
    "cme_nq": [
        "NASDAQ-100 Consolidated",
        "NASDAQ-100 CONSOLIDATED",
        "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
        "NASDAQ MINI",
        "E-MINI NASDAQ-100",
        "E-MINI NASDAQ 100",
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
    for contract_id in ['10y_note', 'cme_btc', '2y_note', '30y_bond', 'cme_nq']:
        if contract_id in data:
            entry = data[contract_id]
            if entry.get('leveraged_funds_net') is not None:
                has_valid = True
                break
    
    if not has_valid:
        return False, "No contracts have leveraged_funds_net data"
    
    return True, ""


def load_prior_nets() -> Dict[str, Any]:
    """
    Load prior week's net positions from state file.
    Returns dict with report_date and nets by contract_id.
    """
    if not COT_PRIOR_NETS_FILE.exists():
        return {}
    try:
        with open(COT_PRIOR_NETS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠ Could not load prior nets: {e}")
        return {}


def save_prior_nets(
    report_date: str,
    nets: Dict[str, int],
    prior_report_date: Optional[str] = None,
    prior_nets: Optional[Dict[str, int]] = None,
) -> bool:
    """
    Persist current week's nets plus optional distinct prior-week snapshot.

    Schema keeps two weeks so same-week re-fetches can still show a real
    prior_week_net / change_1w instead of cloning current → fake Δ=0.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "report_date": report_date,
            "saved_at": datetime.now().isoformat(),
            "nets": nets,
            "prior_report_date": prior_report_date,
            "prior_nets": prior_nets or {},
        }
        with open(COT_PRIOR_NETS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        if prior_report_date:
            print(f"  ✓ Saved nets for {report_date} (prior week {prior_report_date})")
        else:
            print(f"  ✓ Saved nets for {report_date}")
        return True
    except Exception as e:
        print(f"  ⚠ Could not save prior nets: {e}")
        return False


def compute_change_1w(current_net: Optional[int], prior_net: Optional[int]) -> Optional[int]:
    """Compute week-over-week change if both values available."""
    if current_net is None or prior_net is None:
        return None
    return current_net - prior_net


def _resolve_comparison_prior(
    report_date: Optional[str], prior_data: Dict[str, Any]
) -> Tuple[Optional[str], Dict[str, int], bool]:
    """
    Decide which stored nets are the distinct prior week for delta display.

    Returns (compare_prior_date, compare_prior_nets, advancing_week).

    - New week (stored report_date != current): stored nets ARE the prior week.
    - Same-week re-fetch: use nested prior_report_date/prior_nets if distinct.
    - Never compare current nets to themselves (that produced fake change_1w=0).
    """
    stored_date = prior_data.get("report_date")
    stored_nets = prior_data.get("nets") or {}
    hist_prior_date = prior_data.get("prior_report_date")
    hist_prior_nets = prior_data.get("prior_nets") or {}

    if report_date and stored_date and stored_date != report_date:
        return stored_date, stored_nets, True

    if report_date and stored_date and stored_date == report_date:
        if hist_prior_date and hist_prior_date != report_date:
            return hist_prior_date, hist_prior_nets, False
        return None, {}, False

    # No usable prior snapshot yet
    return None, {}, bool(report_date and not stored_date)


def build_cot_result(parsed_data: Dict[str, Dict[str, Any]], report_date: Optional[str]) -> Dict[str, Any]:
    """
    Build the structured COT result for market_data.json.

    Computes change_1w only when a distinct prior-week snapshot exists.
    Same-week re-fetch keeps last-known prior nets (two-week state) instead of
    cloning current → fake Δ=0.
    """
    prior_data = load_prior_nets()
    stored_date = prior_data.get("report_date")
    stored_nets = prior_data.get("nets") or {}

    compare_prior_date, compare_prior_nets, advancing_week = _resolve_comparison_prior(
        report_date, prior_data
    )
    has_distinct_prior = bool(
        compare_prior_date and report_date and compare_prior_date != report_date
    )
    current_nets = {}

    def build_contract_entry(contract_id: str, label: str, contract_code: str) -> Dict[str, Any]:
        data = parsed_data.get(contract_id, {})

        lev_net = data.get('leveraged_funds_net')
        am_net = data.get('asset_manager_net')
        dealer_net = data.get('dealer_net')

        if lev_net is not None:
            current_nets[contract_id] = lev_net

        prior_net = compare_prior_nets.get(contract_id) if has_distinct_prior else None
        # Only emit a numeric delta when prior week is a distinct report_date.
        # Same-week self-compare must not yield change_1w=0.
        change_1w = (
            compute_change_1w(lev_net, prior_net) if has_distinct_prior else None
        )

        return {
            "label": label,
            "contract": contract_code,
            "asset_manager_net": am_net,
            "leveraged_funds_net": lev_net,
            "prior_week_net": prior_net,
            "dealer_net": dealer_net,
            "change_1w": change_1w,
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
        "prior_report_date": compare_prior_date if has_distinct_prior else None,
        "rates_positioning": {
            "10y_note": build_contract_entry("10y_note", "10-Year T-Note Futures", "TY"),
            "2y_note": build_contract_entry("2y_note", "2-Year T-Note Futures", "TU"),
            "30y_bond": build_contract_entry("30y_bond", "30-Year T-Bond Futures", "US"),
        },
        "btc_positioning": {
            "cme_btc": build_contract_entry("cme_btc", "CME Bitcoin Futures", "BTC"),
        },
        "equity_positioning": {
            "cme_nq": build_contract_entry("cme_nq", "CME E-mini Nasdaq-100", "NQ"),
        },
        "positioning_context": {
            "_comment": "Narrative summary of positioning trends",
            "summary": None,
            "key_shift": None,
            "crowded_trades": []
        }
    }

    if report_date and current_nets:
        if advancing_week:
            # Shift: former current becomes nested prior; write new current.
            save_prior_nets(
                report_date,
                current_nets,
                prior_report_date=stored_date,
                prior_nets=stored_nets,
            )
        else:
            # Same week: refresh current nets, preserve distinct prior snapshot.
            save_prior_nets(
                report_date,
                current_nets,
                prior_report_date=compare_prior_date if has_distinct_prior else None,
                prior_nets=compare_prior_nets if has_distinct_prior else {},
            )

    return result


def _rollup_data_status(market_data: Dict[str, Any]) -> str:
    """
    Compute top-level _data_status from individual data_fetch_status values.
    
    Returns:
        'live'    - All automated sections are live
        'partial' - Some sections are live, others stale or stub
        'stale'   - All automated sections are stale
        'stub'    - No sections have live data yet
    """
    status = market_data.get('data_fetch_status', {})
    # Key automated sections (treasury_calendar is manual/stub for now)
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


def mark_cot_stale(error_reason: str) -> bool:
    """
    Mark existing cftc_cot data as stale without overwriting it.
    Fail-closed: preserve last known good data; repair conflict markers if needed.
    """
    try:
        if not MARKET_DATA_FILE.exists():
            print(f"  ⚠ No existing market_data.json to mark stale")
            return False

        market_data, load_note = load_market_data(MARKET_DATA_FILE, repair=True)
        if not market_data:
            print(f"  ⚠ No usable market_data to mark stale ({load_note})")
            return False

        if 'cftc_cot' in market_data:
            market_data['cftc_cot']['_stale'] = True
            market_data['cftc_cot']['_stale_since'] = datetime.now().isoformat()
            market_data['cftc_cot']['_stale_reason'] = error_reason

        if 'data_fetch_status' in market_data:
            market_data['data_fetch_status']['cftc_cot'] = 'stale'

        market_data['_data_status'] = _rollup_data_status(market_data)

        ok_save, save_msg = save_market_data(market_data, MARKET_DATA_FILE)
        if not ok_save:
            print(f"  ✗ Failed to mark data stale: {save_msg}")
            return False

        print(f"  ⚠ Marked cftc_cot as stale: {error_reason}")
        return True

    except Exception as e:
        print(f"  ✗ Failed to mark data stale: {e}")
        return False


def update_market_data(cot_data: Dict[str, Any]) -> bool:
    """Update market_data.json with the new COT data."""
    try:
        market_data, load_note = load_market_data(MARKET_DATA_FILE, repair=True)
        if load_note != "ok":
            print(f"  ⚠ market_data load: {load_note}")
        if not isinstance(market_data, dict):
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
        
        # Roll up _data_status based on individual section statuses
        market_data['_data_status'] = _rollup_data_status(market_data)
        market_data['_updated'] = datetime.now().strftime('%Y-%m-%d')
        
        ok_save, save_msg = save_market_data(market_data, MARKET_DATA_FILE)
        if not ok_save:
            print(f"  ✗ Refused to write market_data.json: {save_msg}")
            return False
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
    prior_report_date = result.get('prior_report_date')
    print(f"  ✓ Parsed COT data for report date: {report_date}")
    if prior_report_date:
        print(f"    Prior week: {prior_report_date}")
    
    for section_key, section_data in [('rates_positioning', result.get('rates_positioning', {})),
                                       ('btc_positioning', result.get('btc_positioning', {})),
                                       ('equity_positioning', result.get('equity_positioning', {}))]:
        for contract_id, contract_data in section_data.items():
            net = contract_data.get('leveraged_funds_net')
            if net is not None:
                display = format_net_display(net)
                change = contract_data.get('change_1w')
                change_str = ""
                if change is not None:
                    change_display = format_net_display(change)
                    change_str = f" (Δ {change_display})"
                print(f"    {contract_data['label']}: {display}{change_str}")



FINFUT_HISTORY_ZIP_URL = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"

# Prefer these market-name needles when multiple contracts match a pattern
# (e.g. BITCOIN vs MICRO BITCOIN; NASDAQ-100 CONSOLIDATED vs NASDAQ MINI).
PREFERRED_MARKET_NEEDLES = {
    "10y_note": "UST 10Y NOTE",
    "2y_note": "UST 2Y NOTE",
    "30y_bond": "UST BOND - CHICAGO BOARD OF TRADE",
    "cme_btc": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
    "cme_nq": "NASDAQ-100 CONSOLIDATED",
}


def parse_finfut_nets_for_date(txt_data: str, as_of_date: str) -> Dict[str, int]:
    """
    Parse Lev_Money net positions for a single Report_Date_as_YYYY-MM-DD
    from CFTC FinFutYY / financial futures CSV text.
    """
    import csv
    import io

    if not txt_data or not as_of_date:
        return {}

    reader = csv.DictReader(io.StringIO(txt_data))
    # contract_id -> (preference_rank, net)  lower rank = better
    best: Dict[str, Tuple[int, int]] = {}

    for row in reader:
        # DictReader keys may retain quotes depending on dialect
        def cell(*names):
            for n in names:
                if n in row:
                    return (row[n] or "").strip().strip('"')
                for rk, rv in row.items():
                    if rk.strip().strip('"') == n:
                        return (rv or "").strip().strip('"')
            return ""

        date = cell("Report_Date_as_YYYY-MM-DD")
        if date != as_of_date:
            continue
        market = cell("Market_and_Exchange_Names").upper()
        if not market:
            continue

        matched = None
        for contract_id, patterns in CONTRACT_PATTERNS.items():
            for pattern in patterns:
                if pattern.upper() in market:
                    matched = contract_id
                    break
            if matched:
                break
        if not matched:
            continue

        try:
            lev_long = int(cell("Lev_Money_Positions_Long_All").replace(",", ""))
            lev_short = int(cell("Lev_Money_Positions_Short_All").replace(",", ""))
        except (ValueError, TypeError):
            continue
        net = lev_long - lev_short

        preferred = PREFERRED_MARKET_NEEDLES.get(matched, "").upper()
        rank = 0 if preferred and preferred in market else 1
        # Reject MICRO / ULTRA when a preferred classic contract exists later
        if matched == "30y_bond" and "ULTRA" in market:
            rank = 2
        if matched == "cme_btc" and "MICRO" in market:
            rank = 2
        if matched == "cme_nq" and "MICRO" in market:
            rank = 2
        if matched == "cme_nq" and "CONSOLIDATED" not in market and "NASDAQ MINI" in market:
            rank = 1

        prev = best.get(matched)
        if prev is None or rank < prev[0]:
            best[matched] = (rank, net)

    return {cid: net for cid, (_rank, net) in best.items()}


def fetch_finfut_history_txt(year: Optional[int] = None) -> Optional[str]:
    """Download CFTC FinFutYY historical zip for a calendar year and return TXT."""
    import io
    import zipfile

    if year is None:
        year = datetime.now().year
    url = FINFUT_HISTORY_ZIP_URL.format(year=year)
    headers = _make_request_headers()
    try:
        print(f"  Trying FinFut history {year}...")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as response:
            content = response.read()
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for fname in zf.namelist():
                if fname.endswith('.txt'):
                    text = zf.read(fname).decode('utf-8', errors='replace')
                    print(f"  ✓ Fetched FinFut history {year} ({len(text)} bytes)")
                    return text
        print(f"  ✗ FinFut history zip had no .txt")
    except Exception as e:
        print(f"  ✗ FinFut history {year} failed: {e}")
    return None


def backfill_prior_nets(as_of_date: str) -> bool:
    """
    Seed cot_prior_nets.json from CFTC FinFut historical for as_of_date.
    Used when prior state was overwritten by a same-week self-save.
    """
    try:
        year = int(as_of_date[:4])
    except (TypeError, ValueError):
        print(f"  ✗ Invalid as_of_date: {as_of_date}")
        return False

    txt = fetch_finfut_history_txt(year)
    if not txt:
        return False

    nets = parse_finfut_nets_for_date(txt, as_of_date)
    if not nets:
        print(f"  ✗ No FinFut nets found for {as_of_date}")
        return False

    ok = save_prior_nets(as_of_date, nets, prior_report_date=None, prior_nets={})
    if ok:
        for cid, net in sorted(nets.items()):
            print(f"    {cid}: {net}")
    return ok


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch CFTC COT positioning")
    parser.add_argument(
        "--backfill-prior",
        metavar="YYYY-MM-DD",
        help="Seed prior nets from FinFut history for this as-of date, then exit",
    )
    parser.add_argument(
        "--backfill-prior-then-fetch",
        metavar="YYYY-MM-DD",
        help="Seed prior nets from FinFut history, then fetch current week",
    )
    args, _unknown = parser.parse_known_args()

    print("=" * 60)
    print("Fetch CFTC Commitment of Traders (COT) Positioning")
    print(f"Source: {CFTC_FIN_LF_PAGE}")
    print(f"Started: {datetime.now()}")
    print("=" * 60)

    if args.backfill_prior:
        ok = backfill_prior_nets(args.backfill_prior)
        return 0 if ok else 1

    if args.backfill_prior_then_fetch:
        if not backfill_prior_nets(args.backfill_prior_then_fetch):
            return 1

    data, error_reason = fetch_and_parse()
    
    if data:
        if not update_market_data(data):
            mark_cot_stale("Failed to write market_data.json")
            return 1
        
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Report Date: {data.get('report_date', 'unknown')}")
        prior_date = data.get('prior_report_date')
        if prior_date:
            print(f"Prior Week:  {prior_date}")
        
        def print_contract(section_name: str, key: str, label: str):
            section = data.get(section_name, {})
            entry = section.get(key, {})
            net = entry.get('leveraged_funds_net')
            if net is not None:
                change = entry.get('change_1w')
                change_str = ""
                if change is not None:
                    change_str = f" (Δ {format_net_display(change)})"
                print(f"{label}: Leveraged Funds Net = {format_net_display(net)}{change_str}")
        
        print_contract('rates_positioning', '10y_note', '10Y T-Note (TY)')
        print_contract('btc_positioning', 'cme_btc', 'CME Bitcoin (BTC)')
        print_contract('equity_positioning', 'cme_nq', 'CME Nasdaq-100 (NQ)')
    else:
        mark_cot_stale(error_reason or "Unknown error during fetch/parse")
        print(f"\n✗ Failed to fetch COT data: {error_reason}")
        print("  (existing data preserved, marked stale)")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
