#!/usr/bin/env python3
"""
Fetch stock data from Yahoo Finance and generate candlestick charts.
Only charts the top 10 tickers by weighted score + QQQ/BTC for title bar.
"""

import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import sqlite3
import json

# Config
CHARTS_DIR = Path.home() / ".openclaw/workspace/site/charts"
CHARTS_DIR.mkdir(exist_ok=True)

DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"

# Always-chart tickers for title bar display
TITLE_BAR_TICKERS = {
    'QQQ': 'Invesco QQQ Trust',
    'BTC-USD': 'Bitcoin USD'
}


def get_top_tickers_from_db(limit=10):
    """Get top tickers by weighted score from database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        cursor = conn.execute("""
            SELECT ticker, SUM(weighted_score) as total_score, COUNT(*) as mentions
            FROM ticker_mentions
            WHERE ticker NOT IN ('S&P', 'Nasdaq', 'Russell', 'Semiconductors')  -- Skip index names
            GROUP BY ticker
            ORDER BY total_score DESC
            LIMIT ?
        """, (limit,))
        
        tickers = {}
        for row in cursor.fetchall():
            ticker = row['ticker']
            # Map BTC to BTC-USD for Yahoo Finance
            symbol = 'BTC-USD' if ticker == 'BTC' else ticker
            tickers[symbol] = {
                'name': ticker,  # Use ticker as name, can be enhanced later
                'score': row['total_score'],
                'mentions': row['mentions']
            }
        
        conn.close()
        return tickers
    except Exception as e:
        print(f"Warning: Could not load tickers from database: {e}")
        return {}


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
    print("Stock Chart Generator - Top 10 Tickers + Title Bar")
    print("=" * 60)
    
    charts_created = []
    all_price_data = []
    
    # Get top 10 tickers from database
    top_tickers = get_top_tickers_from_db(limit=10)
    
    # Add title bar tickers
    all_tickers = dict(top_tickers)  # Copy top tickers
    for symbol, name in TITLE_BAR_TICKERS.items():
        if symbol not in all_tickers:
            all_tickers[symbol] = {'name': name, 'score': 0, 'mentions': 0}
    
    print(f"\n📊 Charting {len(top_tickers)} top tickers + {len(TITLE_BAR_TICKERS)} title bar tickers")
    print("Top tickers:", list(top_tickers.keys()))
    print("-" * 40)
    
    # Generate/update charts for all tickers
    for symbol, info in all_tickers.items():
        name = info['name'] if isinstance(info, dict) else info
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
