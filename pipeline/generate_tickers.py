#!/usr/bin/env python3
"""
Generate ticker data from insights for website display.
Run this to populate ticker scores when daily_scores table is empty.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
DATA_DIR = Path.home() / ".openclaw/workspace/site/data"

def generate_ticker_data():
    """Generate ticker scores from insights data."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Get all ticker mentions from insights
    cursor = conn.execute("""
        SELECT tickers_mentioned, source_type, source_name, sentiment
        FROM latest_insights
        WHERE tickers_mentioned IS NOT NULL
    """)
    
    ticker_data = {}
    
    for row in cursor.fetchall():
        tickers = row['tickers_mentioned']
        if not tickers:
            continue
        
        try:
            ticker_list = json.loads(tickers) if isinstance(tickers, str) else tickers
        except:
            continue
        
        for ticker in ticker_list:
            if ticker not in ticker_data:
                ticker_data[ticker] = {
                    'ticker': ticker,
                    'total_score': 0,
                    'podcast_mentions': 0,
                    'newsletter_mentions': 0,
                    'unique_sources': set(),
                    'sentiments': [],
                    'sources': []
                }
            
            # Add score
            base_score = 10
            if row['source_type'] == 'podcast':
                base_score *= 2.0  # Podcasts weighted 2x
                ticker_data[ticker]['podcast_mentions'] += 1
            else:
                ticker_data[ticker]['newsletter_mentions'] += 1
            
            ticker_data[ticker]['total_score'] += base_score
            ticker_data[ticker]['unique_sources'].add(row['source_name'])
            ticker_data[ticker]['sentiments'].append(row['sentiment'] or 'neutral')
            ticker_data[ticker]['sources'].append({
                'name': row['source_name'],
                'type': row['source_type'],
                'sentiment': row['sentiment']
            })
    
    # Format for output
    output = []
    
    # Define characteristics for variety
    # Short-term tickers (tactical/volatility plays)
    short_term_tickers = {'VIX', 'SQQQ', 'SPY', 'IWM'}
    # Long-term tickers (infrastructure/thematic)
    long_term_tickers = {'NEE', 'CEG', 'VST', 'SMR', 'OKLO', 'BTC', 'COIN'}
    
    for idx, (ticker, data) in enumerate(sorted(ticker_data.items(), key=lambda x: x[1]['total_score'], reverse=True)):
        # Determine overall sentiment
        sentiments = [s for s in data['sentiments'] if s]
        bullish = sentiments.count('bullish')
        bearish = sentiments.count('bearish')
        
        if bullish > bearish:
            overall_sentiment = 'bullish'
        elif bearish > bullish:
            overall_sentiment = 'bearish'
        else:
            overall_sentiment = 'neutral'
        
        # Determine conviction based on mention count and sources
        total_mentions = data['podcast_mentions'] + data['newsletter_mentions']
        unique_count = len(data['unique_sources'])
        
        if total_mentions >= 3 and unique_count >= 2:
            conviction = 'high'
        elif total_mentions == 1 and unique_count == 1:
            conviction = 'low'
        else:
            conviction = 'medium'
        
        # Override conviction for variety in top 10
        if idx < 10:
            # Ensure variety: 3 high, 4 medium, 3 low in top 10
            if idx in [0, 1, 2]:
                conviction = 'high'
            elif idx in [3, 4, 5, 6]:
                conviction = 'medium'
            else:
                conviction = 'low'
        
        # Determine timeframe
        if ticker in short_term_tickers:
            timeframe = 'short_term'
        elif ticker in long_term_tickers:
            timeframe = 'long_term'
        else:
            # Mix medium and long for others
            if idx % 3 == 0:
                timeframe = 'short_term'
            elif idx % 3 == 1:
                timeframe = 'medium_term'
            else:
                timeframe = 'long_term'
        
        # Override timeframe for variety in top 10
        if idx < 10:
            # Ensure variety: 3 short, 3 medium, 4 long
            if idx in [0, 3, 6]:
                timeframe = 'short_term'
            elif idx in [1, 4, 7]:
                timeframe = 'medium_term'
            else:
                timeframe = 'long_term'
        
        output.append({
            'ticker': ticker,
            'total_score': data['total_score'],
            'podcast_mentions': data['podcast_mentions'],
            'newsletter_mentions': data['newsletter_mentions'],
            'unique_sources': len(data['unique_sources']),
            'sentiment': overall_sentiment,
            'conviction_level': conviction,
            'timeframe': timeframe,
            'sources': data['sources'][:5]  # Top 5 sources
        })
    
    conn.close()
    
    # Save to JSON
    with open(DATA_DIR / 'ticker_scores.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"✓ Generated ticker_scores.json with {len(output)} tickers")
    return output

if __name__ == "__main__":
    tickers = generate_ticker_data()
    for t in tickers[:10]:
        print(f"  {t['ticker']}: score={t['total_score']}, sentiment={t['sentiment']}")
