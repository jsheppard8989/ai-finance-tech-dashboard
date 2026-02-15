#!/usr/bin/env python3
"""
Fetch current prices for all tickers in the database.
Runs daily to update price_data.json
"""

import json
import urllib.request
import sqlite3
from pathlib import Path
from datetime import datetime

# Paths
DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
PRICE_FILE = Path.home() / ".openclaw/workspace/site/price_data.json"

def get_all_tickers():
    """Get all unique tickers from database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("""
        SELECT DISTINCT ticker FROM ticker_mentions
        UNION
        SELECT DISTINCT ticker FROM daily_scores
    """)
    tickers = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tickers

def fetch_yahoo_prices(tickers):
    """Fetch prices from Yahoo Finance."""
    prices = {}
    
    # Yahoo Finance API endpoint (unofficial)
    base_url = "https://query1.finance.yahoo.com/v8/finance/chart/"
    
    for ticker in tickers:
        try:
            # Handle special cases
            symbol = ticker
            if ticker == 'BTC':
                symbol = 'BTC-USD'
            elif ticker == 'VIX':
                symbol = '^VIX'
            
            url = f"{base_url}{symbol}?interval=1d&range=1d"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read())
                
            if data.get('chart', {}).get('result'):
                result = data['chart']['result'][0]
                meta = result['meta']
                
                price = meta.get('regularMarketPrice', 0)
                prev_close = meta.get('previousClose', price)
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
                
                prices[ticker] = {
                    'price': round(price, 2),
                    'change_pct': round(change_pct, 2),
                    'name': meta.get('shortName', meta.get('longName', ticker)),
                    'updated': datetime.now().isoformat()
                }
                print(f"  ✓ {ticker}: ${price:.2f} ({change_pct:+.2f}%)")
            else:
                print(f"  ⚠ {ticker}: No data")
                
        except Exception as e:
            print(f"  ✗ {ticker}: {str(e)[:50]}")
    
    return prices

def update_price_file(prices):
    """Update the price_data.json file."""
    # Load existing to preserve any manual entries
    existing = {}
    if PRICE_FILE.exists():
        with open(PRICE_FILE, 'r') as f:
            existing = json.load(f)
    
    # Merge new prices
    existing.update(prices)
    
    # Add metadata
    existing['_metadata'] = {
        'last_updated': datetime.now().isoformat(),
        'count': len([k for k in existing.keys() if not k.startswith('_')])
    }
    
    with open(PRICE_FILE, 'w') as f:
        json.dump(existing, f, indent=2)
    
    print(f"\n✓ Updated {PRICE_FILE} with {len(prices)} prices")

def main():
    """Main entry point."""
    print("="*60)
    print("Fetching Ticker Prices")
    print(f"Started: {datetime.now()}")
    print("="*60)
    
    # Get tickers from database
    tickers = get_all_tickers()
    print(f"\nFound {len(tickers)} tickers in database")
    
    # Add common market tickers if not present
    for market_ticker in ['QQQ', 'BTC-USD', 'SPY']:
        if market_ticker not in tickers:
            tickers.append(market_ticker)
    
    print(f"Fetching prices for {len(tickers)} tickers...\n")
    
    # Fetch prices
    prices = fetch_yahoo_prices(tickers)
    
    # Update file
    update_price_file(prices)
    
    print(f"\nFinished: {datetime.now()}")

if __name__ == "__main__":
    main()
