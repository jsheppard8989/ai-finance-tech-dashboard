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
    """Get all tickers that need prices."""
    # Load current data.js to get all tickers
    data_js = Path.home() / ".openclaw/workspace/site/data/data.js"
    tickers = set()
    
    if data_js.exists():
        with open(data_js, 'r') as f:
            content = f.read()
            # Quick parse to get ticker symbols
            if 'tickerScores' in content:
                start = content.find('tickerScores:')
                if start > 0:
                    bracket_start = content.find('[', start)
                    bracket_end = content.find(']', bracket_start)
                    try:
                        scores = json.loads(content[bracket_start:bracket_end+1])
                        for s in scores:
                            if 'ticker' in s:
                                tickers.add(s['ticker'])
                    except:
                        pass
    
    # Also get from database
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute('SELECT tickers_mentioned FROM latest_insights')
        for row in cursor.fetchall():
            if row[0]:
                try:
                    t_list = json.loads(row[0])
                    tickers.update(t_list)
                except:
                    pass
        conn.close()
    except:
        pass
    
    return sorted(tickers)

def fetch_price_data(ticker):
    """Fetch price and 2-week change from Yahoo Finance."""
    try:
        # Map ticker symbols for Yahoo Finance
        symbol = ticker
        if ticker == 'BTC':
            symbol = 'BTC-USD'
        elif ticker == 'VIX':
            symbol = '^VIX'
        
        # Get current price
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=15d"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
        
        if not data.get('chart', {}).get('result'):
            return None
        
        result = data['chart']['result'][0]
        meta = result['meta']
        
        # Get current price
        current_price = meta.get('regularMarketPrice', 0)
        
        # Get 2-week (10 trading days) change
        timestamps = result.get('timestamp', [])
        prices = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
        
        if len(prices) >= 10:
            price_10_days_ago = prices[-10]  # 10 days back
            if price_10_days_ago and current_price:
                change_pct = ((current_price - price_10_days_ago) / price_10_days_ago) * 100
            else:
                change_pct = 0
        else:
            # Fallback to regularMarketPreviousClose
            prev_close = meta.get('previousClose', current_price)
            if prev_close and current_price:
                change_pct = ((current_price - prev_close) / prev_close) * 100
            else:
                change_pct = 0
        
        return {
            'price': round(current_price, 2),
            'change_pct': round(change_pct, 2),
            'name': meta.get('shortName', meta.get('longName', ticker)),
            'updated': datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"    Error fetching {ticker}: {str(e)[:60]}")
        return None

def main():
    print("="*60)
    print("Fetching Prices with 2-Week % Change")
    print(f"Started: {datetime.now()}")
    print("="*60)
    
    tickers = get_tickers_from_data()
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
