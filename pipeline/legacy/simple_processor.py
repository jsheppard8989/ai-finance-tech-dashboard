#!/usr/bin/env python3
"""
Quick keyword-based transcript processor.
Fallback when AI APIs are unavailable - extracts tickers and basic sentiment.
"""

import re
import json
from pathlib import Path
from datetime import datetime, date

TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"

# Ticker patterns
TICKER_PATTERN = r'\b([A-Z]{3,5})\b'

# Common words to exclude
EXCLUDE_WORDS = {'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'HAD', 'HOT', 'HIS', 'HOW', 'MAN', 'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO', 'BOY', 'DID', 'ITS', 'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'DAD', 'MOM', 'AI', 'US', 'COVID', 'OK', 'ETF', 'IPO', 'EPS', 'GDP', 'CEO', 'CFO', 'CTO', 'VIP', 'NBA', 'NFL', 'MLB', 'FBI', 'CIA', 'IRS', 'FDA', 'SEC', 'FTC', 'DOJ', 'YES', 'NO', 'GO', 'DO', 'IF', 'UP', 'SO', 'ME', 'MY', 'WE', 'HE', 'IT', 'BE', 'BY', 'ON', 'TO', 'OF', 'IN', 'IS', 'AT', 'AS', 'OR', 'AN', 'TV', 'PC', 'CD', 'US', 'UK', 'EU', 'UN', 'VS', 'HR', 'IT', 'RIP', 'LOL', 'OMG', 'WOW', 'BIG', 'TOP', 'BEST', 'NEW', 'GOOD', 'BAD', 'HIGH', 'LOW', 'FAST', 'SLOW', 'HARD', 'EASY', 'TRUE', 'FALSE', 'REAL', 'FAKE', 'OPEN', 'CLOSE', 'LONG', 'SHORT', 'BUY', 'SELL', 'HOLD', 'CALL', 'PUT', 'BULL', 'BEAR', 'MOON', 'REKT', 'HODL', 'FUD', 'FOMO', 'ATH', 'ATL', 'GPT', 'CEO', 'AGI', 'LLM'}

# Investment keywords
BULLISH_KEYWORDS = ['buy', 'long', 'bullish', 'accumulate', 'increase', 'growth', 'opportunity', 'undervalued', 'cheap', 'strong', 'moon', 'rocket']
BEARISH_KEYWORDS = ['sell', 'short', 'bearish', 'decrease', 'overvalued', 'expensive', 'weak', 'crash', 'drop', 'fall']

def extract_tickers_from_text(text):
    """Extract potential tickers from text."""
    tickers = re.findall(TICKER_PATTERN, text)
    valid_tickers = []
    for t in tickers:
        if t not in EXCLUDE_WORDS and len(t) >= 2 and len(t) <= 5:
            valid_tickers.append(t)
    return list(set(valid_tickers))

def detect_sentiment(text, ticker):
    """Basic sentiment detection around ticker mentions."""
    text_lower = text.lower()
    
    # Find sentences containing the ticker
    sentences = re.split(r'[.!?]+', text)
    ticker_sentences = [s for s in sentences if ticker.lower() in s.lower()]
    
    if not ticker_sentences:
        return 'neutral', 50
    
    context = ' '.join(ticker_sentences).lower()
    
    bullish_count = sum(1 for kw in BULLISH_KEYWORDS if kw in context)
    bearish_count = sum(1 for kw in BEARISH_KEYWORDS if kw in context)
    
    if bullish_count > bearish_count:
        return 'bullish', min(50 + bullish_count * 10, 90)
    elif bearish_count > bullish_count:
        return 'bearish', max(50 - bearish_count * 10, 20)
    else:
        return 'neutral', 50

def process_transcript_simple(filepath):
    """Process a transcript with simple keyword extraction."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Skip if too short
    if len(content) < 1000:
        return None
    
    # Extract tickers
    tickers = extract_tickers_from_text(content)
    
    # Get first 500 chars for preview
    preview = content[:500].replace('\n', ' ')
    
    # Detect podcast from content
    podcast_name = "Unknown"
    if 'monetary matters' in content.lower() or 'jack farley' in content.lower():
        podcast_name = "Monetary Matters with Jack Farley"
    elif 'jack mallers' in content.lower() or 'mallers show' in content.lower():
        podcast_name = "The Jack Mallers Show"
    elif 'peter diamandis' in content.lower() or 'moonshots' in content.lower():
        podcast_name = "Moonshots with Peter Diamandis"
    elif 'a16z' in content.lower():
        podcast_name = "a16z Live"
    
    # Build ticker mentions
    ticker_mentions = []
    for ticker in tickers[:15]:  # Limit to top 15
        sentiment, conviction = detect_sentiment(content, ticker)
        ticker_mentions.append({
            'ticker': ticker,
            'sentiment': sentiment,
            'conviction_score': conviction,
            'context': f"Mentioned in {podcast_name} discussion"
        })
    
    return {
        'podcast': podcast_name,
        'filename': filepath.name,
        'tickers_found': len(tickers),
        'ticker_mentions': ticker_mentions,
        'preview': preview[:200],
        'processed_at': datetime.now().isoformat()
    }

def main():
    """Process all transcripts with simple extraction."""
    print("="*60)
    print("Simple Keyword-Based Transcript Processing")
    print("(Fallback mode - no AI API required)")
    print("="*60)
    
    results = []
    processed_count = 0
    
    for transcript_file in TRANSCRIPT_DIR.glob("*.txt"):
        print(f"\nProcessing {transcript_file.name}...")
        
        result = process_transcript_simple(transcript_file)
        
        if result:
            results.append(result)
            processed_count += 1
            print(f"  ✓ Found {result['tickers_found']} tickers")
            print(f"  ✓ Top mentions: {', '.join([t['ticker'] for t in result['ticker_mentions'][:5]])}")
        else:
            print(f"  ⏭ Skipped (too short)")
    
    # Save results
    output_file = Path.home() / ".openclaw/workspace/pipeline/simple_analysis.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n" + "="*60)
    print(f"Processed {processed_count} transcripts")
    print(f"Results saved to: {output_file}")
    print("\nTicker Summary:")
    
    all_tickers = {}
    for r in results:
        for tm in r['ticker_mentions']:
            t = tm['ticker']
            if t not in all_tickers:
                all_tickers[t] = {'count': 0, 'sentiment': tm['sentiment']}
            all_tickers[t]['count'] += 1
    
    # Sort by count
    sorted_tickers = sorted(all_tickers.items(), key=lambda x: x[1]['count'], reverse=True)
    for ticker, data in sorted_tickers[:20]:
        print(f"  {ticker}: {data['count']} mentions ({data['sentiment']})")

if __name__ == "__main__":
    main()
