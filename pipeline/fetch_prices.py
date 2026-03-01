#!/usr/bin/env python3
"""
Fetch current prices and 2-week % change for all tickers.
"""

import json
import urllib.request
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
PRICE_FILE = Path.home() / ".openclaw/workspace/site/price_data.json"

def get_tickers_from_data():
    """Get all tickers that need prices from ticker_scores.json and database."""
    tickers = set()
    
    # Load from ticker_scores.json (primary source)
    ticker_scores_file = Path.home() / ".openclaw/workspace/site/data/ticker_scores.json"
    if ticker_scores_file.exists():
        try:
            with open(ticker_scores_file, 'r') as f:
                scores = json.load(f)
                for s in scores:
                    if 'ticker' in s:
                        tickers.add(s['ticker'])
            print(f"  Loaded {len(tickers)} tickers from ticker_scores.json")
        except Exception as e:
            print(f"  Warning: Could not load ticker_scores.json: {e}")
    
    # Also get from database for any missing tickers
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute('SELECT tickers_mentioned FROM latest_insights WHERE tickers_mentioned IS NOT NULL')
        for row in cursor.fetchall():
            if row[0]:
                try:
                    t_list = json.loads(row[0])
                    tickers.update(t_list)
                except:
                    pass
        conn.close()
    except Exception as e:
        print(f"  Warning: Could not load from database: {e}")
    
    return sorted(tickers)

# Map display names / invalid symbols to Yahoo Finance symbols. None = skip fetch.
YAHOO_SYMBOL_MAP = {
    'AppLovin': 'APP',
    'CROWD': 'CRWD',   # CrowdStrike
    'Russell': 'IWM',  # Russell 2000 ETF
    'S&P': 'SPY',
    'S&P 500': 'SPY',
    'Semiconductors': 'SMH',
    'Nasdaq': 'QQQ',
    'WORK': None,      # WeWork delisted
    'FTIE': None,      # Unclear / LSE-only
    'SQ': None,        # Block Inc - Yahoo 404
}
SKIP_TICKERS = {'N/A', 'n/a', ''}

def fetch_price_data(ticker):
    """Fetch price and 2-week (14 day) change from Yahoo Finance."""
    try:
        if ticker in SKIP_TICKERS or not (ticker and str(ticker).strip()):
            return None
        symbol = YAHOO_SYMBOL_MAP.get(ticker, ticker)
        if symbol is None:
            return None
        if symbol == 'BTC':
            symbol = 'BTC-USD'
        elif symbol == 'VIX':
            symbol = '^VIX'
        # Get 14 days of data (2 weeks)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=20d"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
        
        if not data.get('chart', {}).get('result'):
            return None
        
        result = data['chart']['result'][0]
        meta = result['meta']
        
        # Get current price (regular market price or last close)
        current_price = meta.get('regularMarketPrice') or meta.get('previousClose', 0)
        
        # Get prices array
        prices = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
        timestamps = result.get('timestamp', [])
        
        # Calculate 2-week (14 day) change
        if len(prices) >= 14:
            # Get price from 14 days ago (index -14 from end)
            price_14_days_ago = prices[-14]
            if price_14_days_ago and current_price:
                change_pct = ((current_price - price_14_days_ago) / price_14_days_ago) * 100
            else:
                change_pct = 0
        elif len(prices) >= 2:
            # Fallback: use earliest available price in the range
            price_earliest = prices[0]
            if price_earliest and current_price:
                change_pct = ((current_price - price_earliest) / price_earliest) * 100
            else:
                change_pct = 0
        else:
            # Fallback to previous close
            prev_close = meta.get('previousClose', current_price)
            if prev_close and current_price:
                change_pct = ((current_price - prev_close) / prev_close) * 100
            else:
                change_pct = 0
        
        return {
            'price': round(current_price, 2),
            'change_pct': round(change_pct, 2),
            'name': meta.get('shortName', meta.get('longName', ticker)),
            'updated': datetime.now().isoformat(),
            'price_14d_ago': round(prices[-14], 2) if len(prices) >= 14 else None
        }
        
    except Exception as e:
        print(f"    Error fetching {ticker}: {str(e)[:60]}")
        return None

def main():
    print("="*60)
    print("Fetching Prices with 2-Week (14 Day) % Change")
    print(f"Started: {datetime.now()}")
    print("="*60)
    
    raw = get_tickers_from_data()
    tickers = [t for t in raw if t not in SKIP_TICKERS and (t and str(t).strip())]
    # Ensure QQQ and BTC are included (for title bar)
    for required in ['QQQ', 'BTC']:
        if required not in tickers:
            tickers.append(required)
    print(f"\nFound {len(tickers)} tickers")
    
    # Load existing prices
    existing = {}
    if PRICE_FILE.exists():
        with open(PRICE_FILE, 'r') as f:
            existing = json.load(f)
    
    # Fetch new prices
    new_prices = {}
    for ticker in tickers:
        print(f"  Fetching {ticker}...", end=' ')
        data = fetch_price_data(ticker)
        if data:
            new_prices[ticker] = data
            print(f"${data['price']:.2f} ({data['change_pct']:+.2f}%)")
        else:
            # Keep existing if available
            if ticker in existing and not ticker.startswith('_'):
                new_prices[ticker] = existing[ticker]
                print(f"Using cached: ${existing[ticker]['price']:.2f}")
            else:
                print("Failed")
    
    # Add metadata
    new_prices['_metadata'] = {
        'last_updated': datetime.now().isoformat(),
        'count': len([k for k in new_prices.keys() if not k.startswith('_')])
    }
    
    # Save
    with open(PRICE_FILE, 'w') as f:
        json.dump(new_prices, f, indent=2)
    
    print(f"\n✓ Saved {len(new_prices)-1} prices to {PRICE_FILE}")
    print(f"Finished: {datetime.now()}")

if __name__ == "__main__":
    main()
