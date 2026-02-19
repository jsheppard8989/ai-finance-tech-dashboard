#!/usr/bin/env python3
"""
Fetch stock data from Yahoo Finance and generate candlestick charts.
"""

import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

# Config
CHARTS_DIR = Path.home() / ".openclaw/workspace/site/charts"
CHARTS_DIR.mkdir(exist_ok=True)

# Stock symbols to chart (primary tickers for main display)
STOCKS = {
    'GOOGL': 'Alphabet Inc.',
    'MSFT': 'Microsoft Corporation',
    'AAPL': 'Apple Inc.',
    'NVDA': 'NVIDIA Corporation',
    'META': 'Meta Platforms Inc.',
    'BTC-USD': 'Bitcoin USD',
    'QQQ': 'Invesco QQQ Trust'
}

def get_all_tickers_from_scores():
    """Get all tickers from ticker_scores.json to ensure we chart everything."""
    import json
    ticker_file = Path.home() / ".openclaw/workspace/site/data/ticker_scores.json"
    tickers = {}
    if ticker_file.exists():
        try:
            with open(ticker_file, 'r') as f:
                scores = json.load(f)
                for s in scores:
                    if 'ticker' in s:
                        ticker = s['ticker']
                        # Map BTC to BTC-USD for Yahoo Finance
                        symbol = 'BTC-USD' if ticker == 'BTC' else ticker
                        tickers[symbol] = s.get('name', ticker)
        except Exception as e:
            print(f"Warning: Could not load ticker_scores.json: {e}")
    return tickers

# Second order / hidden play tickers (supply chain beneficiaries)
SECOND_ORDER_TICKERS = {
    # NVDA supply chain
    'NEE': 'NextEra Energy', 'CEG': 'Constellation Energy', 'VST': 'Vistra Corp',
    'SMR': 'NuScale Power', 'OKLO': 'Oklo Inc', 'BWXT': 'BWX Technologies',
    'CWST': 'Casella Waste', 'XYL': 'Xylem Inc', 'AWK': 'American Water',
    'ANET': 'Arista Networks', 'AVGO': 'Broadcom Inc', 'MRVL': 'Marvell Tech',
    'CSCO': 'Cisco Systems', 'DLR': 'Digital Realty', 'EQIX': 'Equinix Inc',
    # GOOGL supply chain
    'FFIV': 'F5 Inc', 'NET': 'Cloudflare', 'DDOG': 'Datadog',
    'SNOW': 'Snowflake', 'PLTR': 'Palantir', 'CFLT': 'Confluent',
    # MSFT supply chain
    'CRM': 'Salesforce', 'NOW': 'ServiceNow', 'VEEV': 'Veeva Systems',
    'WDAY': 'Workday', 'MDB': 'MongoDB',
    # AAPL supply chain
    'SWKS': 'Skyworks', 'QRVO': 'Qorvo', 'QCOM': 'Qualcomm',
    'SQ': 'Block Inc', 'PYPL': 'PayPal', 'SOFI': 'SoFi Technologies',
    # Broad market / other
    'ASML': 'ASML Holding', 'AMAT': 'Applied Materials', 'LRCX': 'Lam Research',
    'KLAC': 'KLA Corp', 'INTC': 'Intel Corp', 'AMD': 'AMD'
}

def fetch_data(symbol, period='14d'):
    """Fetch historical data from Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        # Get data for the period
        df = ticker.history(period=period, interval='1d')
        
        if df.empty:
            print(f"  ✗ No data received for {symbol}")
            return None
        
        print(f"  ✓ Fetched {len(df)} days of data for {symbol}")
        return df
    except Exception as e:
        print(f"  ✗ Error fetching {symbol}: {e}")
        return None

def create_candlestick_chart(df, symbol, name):
    """Create a candlestick chart from the data."""
    try:
        fig, ax = plt.subplots(figsize=(12, 6), facecolor='#1a1a2e')
        ax.set_facecolor('#1a1a2e')
        
        # Calculate width for candles
        width = 0.6
        width2 = 0.1
        
        # Create candlesticks
        for i, (date, row) in enumerate(df.iterrows()):
            open_price = row['Open']
            close_price = row['Close']
            high_price = row['High']
            low_price = row['Low']
            
            # Determine color
            if close_price >= open_price:
                color = '#4caf50'  # Green for up
                lower = open_price
                height = close_price - open_price
            else:
                color = '#f44336'  # Red for down
                lower = close_price
                height = open_price - close_price
            
            # Draw the candle body
            ax.bar(i, height, width, bottom=lower, color=color, edgecolor=color, linewidth=1)
            
            # Draw the wick
            ax.plot([i, i], [low_price, high_price], color=color, linewidth=1)
        
        # Formatting
        ax.set_title(f'{name} ({symbol}) - 2 Week Chart', 
                     fontsize=16, color='#00d4ff', fontweight='bold', pad=20)
        ax.set_xlabel('Date', fontsize=12, color='#8892b0')
        ax.set_ylabel('Price ($)', fontsize=12, color='#8892b0')
        
        # Set x-axis labels
        date_labels = [d.strftime('%m/%d') for d in df.index]
        ax.set_xticks(range(0, len(df), max(1, len(df)//7)))
        ax.set_xticklabels([date_labels[i] for i in range(0, len(df), max(1, len(df)//7))], 
                          rotation=45, ha='right', color='#8892b0')
        
        # Style the axes
        ax.tick_params(colors='#8892b0', which='both')
        ax.spines['bottom'].set_color('#333')
        ax.spines['top'].set_color('#333')
        ax.spines['left'].set_color('#333')
        ax.spines['right'].set_color('#333')
        
        # Add grid
        ax.grid(True, alpha=0.2, color='#333', linestyle='--')
        
        # Add price stats
        latest_close = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2] if len(df) > 1 else latest_close
        change = latest_close - prev_close
        change_pct = (change / prev_close) * 100 if prev_close != 0 else 0
        
        color = '#4caf50' if change >= 0 else '#f44336'
        sign = '+' if change >= 0 else ''
        
        stats_text = f'Latest: ${latest_close:.2f} ({sign}{change:.2f}, {sign}{change_pct:.2f}%)'
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, 
                fontsize=12, color=color, fontweight='bold',
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='#1a1a2e', alpha=0.8))
        
        plt.tight_layout()
        
        # Save chart
        chart_path = CHARTS_DIR / f'{symbol.replace("-", "_")}_chart.png'
        plt.savefig(chart_path, dpi=150, facecolor='#1a1a2e', 
                   edgecolor='none', bbox_inches='tight')
        plt.close()
        
        print(f"  ✓ Chart saved: {chart_path}")
        return chart_path
        
    except Exception as e:
        print(f"  ✗ Error creating chart for {symbol}: {e}")
        return None

def save_price_data(all_data):
    """Save price data to JSON for webpage consumption."""
    import json
    price_data = {}
    
    for item in all_data:
        symbol = item['symbol']
        price_data[symbol] = {
            'price': round(item['latest_price'], 2),
            'change_pct': round(item['change_pct'], 2),
            'name': item['name'],
            'updated_at': datetime.now().isoformat()
        }
    
    # Save to site directory for webpage access
    price_file = CHARTS_DIR.parent / 'price_data.json'
    with open(price_file, 'w') as f:
        json.dump(price_data, f, indent=2)
    
    print(f"\n✓ Price data saved to: {price_file}")
    return price_file

def main():
    print("=" * 60)
    print("Stock Chart Generator - 2 Week (14 Day) Charts")
    print("=" * 60)
    
    charts_created = []
    all_price_data = []
    
    # Get all tickers from ticker_scores.json
    all_tickers = get_all_tickers_from_scores()
    
    # Ensure QQQ and BTC-USD are included (for title bar display)
    if 'QQQ' not in all_tickers:
        all_tickers['QQQ'] = 'Invesco QQQ Trust'
    if 'BTC-USD' not in all_tickers and 'BTC' in all_tickers:
        all_tickers['BTC-USD'] = all_tickers['BTC']  # Map BTC to BTC-USD for Yahoo Finance
    
    print(f"\n📊 Found {len(all_tickers)} tickers to chart")
    print("-" * 40)
    
    # Generate/update charts for all tickers
    for symbol, name in all_tickers.items():
        print(f"\n📊 Processing {symbol}...")
        
        # Fetch data (14 days = 2 weeks)
        df = fetch_data(symbol, period='14d')
        if df is None:
            print(f"  ✗ Failed to fetch data for {symbol}")
            continue
        
        # Create/update chart
        chart_path = create_candlestick_chart(df, symbol, name)
        if chart_path:
            latest_price = float(df['Close'].iloc[-1])
            # Calculate 2-week change (14 days ago to today)
            if len(df) >= 14:
                price_14d_ago = float(df['Close'].iloc[-14])  # 14th day from end
            else:
                price_14d_ago = float(df['Close'].iloc[0])  # Earliest available
            
            change_pct = ((latest_price - price_14d_ago) / price_14d_ago) * 100 if price_14d_ago != 0 else 0
            
            chart_data = {
                'symbol': symbol,
                'name': name,
                'path': str(chart_path),
                'latest_price': latest_price,
                'change_pct': change_pct,
                'price_14d_ago': price_14d_ago
            }
            charts_created.append(chart_data)
            all_price_data.append(chart_data)
            print(f"  ✓ ${latest_price:.2f} ({change_pct:+.2f}% over 14 days)")
    
    # Save price data for webpage
    save_price_data(all_price_data)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Charts created/updated: {len(charts_created)}")
    print(f"Charts saved to: {CHARTS_DIR}")
    return charts_created

if __name__ == "__main__":
    main()
