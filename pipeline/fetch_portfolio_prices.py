#!/usr/bin/env python3
"""
Fetch current prices for portfolio basket tickers and update portfolio.json.

Marks positions to market WITHOUT recomputing inception shares.
Tickers: HIMS, GDRX, TEM, GH, ABT (five-name sleeve only)
"""

import json
import urllib.request
from pathlib import Path
from datetime import datetime

from workspace_paths import SITE_DATA_DIR

PORTFOLIO_FILE = SITE_DATA_DIR / "portfolio.json"

PORTFOLIO_TICKERS = ["HIMS", "GDRX", "TEM", "GH", "ABT"]


def fetch_yahoo_price(ticker: str) -> float | None:
    """Fetch current price from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
        
        if not data.get('chart', {}).get('result'):
            return None
        
        result = data['chart']['result'][0]
        meta = result['meta']
        price = meta.get('regularMarketPrice') or meta.get('previousClose', 0)
        return round(float(price), 2) if price else None
    except Exception as e:
        print(f"    Error fetching {ticker}: {e}")
        return None


def update_portfolio():
    """Update portfolio prices and compute current values."""
    print("=" * 60)
    print("Fetching Portfolio Prices")
    print(f"Started: {datetime.now()}")
    print("=" * 60)
    
    if not PORTFOLIO_FILE.exists():
        print(f"  ✗ Portfolio file not found: {PORTFOLIO_FILE}")
        return False
    
    with open(PORTFOLIO_FILE, 'r') as f:
        portfolio = json.load(f)
    
    for basket in portfolio.get("baskets", []):
        print(f"\nUpdating basket: {basket.get('title', 'Unknown')}")
        
        basket_current_value = 0.0
        
        for name in basket.get("names", []):
            ticker = name.get("ticker")
            shares = name.get("shares", 0)
            inception_price = name.get("inception_price", 0)
            
            print(f"  Fetching {ticker}...", end=" ")
            price = fetch_yahoo_price(ticker)
            
            if price is not None:
                name["current_price"] = price
                current_value = round(shares * price, 2)
                name["current_value"] = current_value
                basket_current_value += current_value
                
                change_pct = ((price - inception_price) / inception_price * 100) if inception_price else 0
                name["change_pct"] = round(change_pct, 2)
                
                print(f"${price:.2f} ({change_pct:+.2f}%)")
            else:
                name["current_value"] = name.get("notional", 1000)
                basket_current_value += name.get("notional", 1000)
                print("Failed - using notional")
        
        basket["basket_current_value"] = round(basket_current_value, 2)
        basket_notional = basket.get("basket_notional_usd", 5000)
        basket["basket_change_pct"] = round(
            ((basket_current_value - basket_notional) / basket_notional * 100), 2
        )
        basket["basket_index_value"] = round(
            (basket_current_value / basket_notional) * basket.get("index_start", 100), 2
        )
        
        basket["last_updated"] = datetime.now().isoformat()
    
    portfolio["_metadata"]["last_updated"] = datetime.now().isoformat()
    
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(portfolio, f, indent=2)
    
    print(f"\n✓ Portfolio updated: {PORTFOLIO_FILE}")
    print(f"Finished: {datetime.now()}")
    return True


def main():
    update_portfolio()


if __name__ == "__main__":
    main()
