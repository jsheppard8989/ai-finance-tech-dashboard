#!/usr/bin/env python3
"""
Enhanced stock analysis with conviction scoring, hidden plays, and multi-factor ranking.
"""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import re

# Directories
INBOX_DIR = Path.home() / ".openclaw/workspace/pipeline/inbox"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
ANALYSIS_DIR = Path.home() / ".openclaw/workspace/pipeline/analysis"
RESEARCH_DIR = Path.home() / ".openclaw/workspace/pipeline/research"

ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

# Conviction keywords (higher = stronger signal)
CONVICTION_HIGH = [
    'deep dive', 'thesis', 'conviction', 'high conviction', 'strong buy',
    'accumulating', 'adding to', 'increasing position', 'doubling down',
    'core holding', 'top pick', 'best idea', 'high confidence'
]

# Disruption keywords - newsletters get boosted when these are mentioned
DISRUPTION_KEYWORDS = [
    'disruption', 'disruptive', 'paradigm shift', 'game changer', 'breakthrough',
    'transformation', 'revolutionary', 'industry changing', 'once in a generation',
    'tipping point', 'inflection point', 'sea change', 'watershed moment'
]

CONVICTION_MEDIUM = [
    'buy', 'long', 'bullish', 'attractive', 'undervalued', 'opportunity',
    'position', 'holding', 'like', 'favorable'
]

CONVICTION_LOW = [
    'mentioned', 'tracking', 'watching', 'monitoring', 'interesting',
    'considering', 'looking at'
]

CONTRARIAN_NEGATIVE = [
    'crowded', 'overowned', 'consensus', 'everyone owns', 'overvalued',
    'sell', 'short', 'avoid', 'red flag', 'warning', 'too expensive',
    'priced in', 'fully valued'
]

CONTRARIAN_POSITIVE = [
    'unloved', 'hated', 'underowned', 'overlooked', 'ignored',
    'contrarian', 'against consensus', 'nobody talks about', 'underappreciated'
]

# Source tiers
TIER_1_SOURCES = [
    'hedge', 'fund letter', 'monetary matters', 'a16z', 'network state',
    'jack mallers', 'carson block', 'muddy waters'
]

TIER_2_SOURCES = [
    'rundown', 'newsletter', 'podcast', 'research'
]

# Hidden plays mapping (when megacap mentioned, these benefit)
HIDDEN_PLAYS = {
    'NVDA': {
        'supply_chain': ['ASML', 'AMAT', 'LRCX', 'KLAC', 'ENTG', 'MKSI'],
        'power': ['NEE', 'CEG', 'VST', 'SMR', 'OKLO', 'BWXT'],
        'cooling': ['CWST', 'XYL', 'AWK'],
        'data_centers': ['DLR', 'EQIX', 'AMT', 'CCI'],
        'networking': ['ANET', 'AVGO', 'MRVL', 'CSCO']
    },
    'GOOGL': {
        'cloud_infrastructure': ['ANET', 'FFIV', 'NET', 'DDOG'],
        'ai_training': ['SNOW', 'PLTR', 'CFLT'],
        'search_disruption': ['PERI', 'APP', 'TBLA']
    },
    'MSFT': {
        'enterprise_ai': ['CRM', 'NOW', 'VEEV', 'WDAY'],
        'azure_ecosystem': ['SNOW', 'DDOG', 'MDB', 'CFLT'],
        'productivity': ['ASAN', 'MONDAY', 'SMAR']
    },
    'TSLA': {
        'ev_supply_chain': ['ALB', 'SQM', 'MP', 'PLL'],
        'charging': ['CHPT', 'EVGO', 'BLNK'],
        'autonomy': ['MBLY', 'LAZR', 'INVZ']
    },
    'AMZN': {
        'logistics': ['ZTO', 'XPO', 'SAIA', 'ODFL'],
        'cloud': ['SNOW', 'DDOG', 'NET'],
        'automation': ['SYM', 'KION', 'AUTO']
    },
    'AAPL': {
        'services_growth': ['SQ', 'PYPL', 'SOFI'],
        'supply_chain': ['SWKS', 'QRVO', 'AVGO', 'QCOM'],
        'vision_pro_ecosystem': ['U', 'MTTR', 'VUZI']
    }
}

def detect_conviction_score(contexts):
    """Analyze contexts for conviction level. Returns 0-100 score."""
    score = 0
    high_count = 0
    medium_count = 0
    low_count = 0
    negative_count = 0
    
    all_text = ' '.join([c.get('subject', '') + ' ' + c.get('preview', '') for c in contexts]).lower()
    
    for kw in CONVICTION_HIGH:
        if kw in all_text:
            high_count += 1
    for kw in CONVICTION_MEDIUM:
        if kw in all_text:
            medium_count += 1
    for kw in CONVICTION_LOW:
        if kw in all_text:
            low_count += 1
    for kw in CONTRARIAN_NEGATIVE:
        if kw in all_text:
            negative_count += 1
    
    # Calculate conviction (0-100)
    if negative_count > 0:
        return -50  # Negative signal
    
    score = min(100, high_count * 25 + medium_count * 10 + low_count * 3)
    return score

def detect_contrarian_signal(contexts):
    """Detect if mention is contrarian (positive) or consensus (negative)."""
    all_text = ' '.join([c.get('subject', '') + ' ' + c.get('preview', '') for c in contexts]).lower()
    
    positive_signals = sum(1 for kw in CONTRARIAN_POSITIVE if kw in all_text)
    negative_signals = sum(1 for kw in CONTRARIAN_NEGATIVE if kw in all_text)
    
    if positive_signals > 0 and negative_signals == 0:
        return 'contrarian_positive'
    elif negative_signals > 0:
        return 'crowded_warning'
    return 'neutral'

def calculate_source_diversity_score(sources, contexts):
    """Score based on source quality and diversity."""
    base_score = len(sources) * 15
    
    # Tier multiplier
    tier_multiplier = 1.0
    for source in sources:
        source_lower = source.lower()
        if any(tier in source_lower for tier in TIER_1_SOURCES):
            tier_multiplier = max(tier_multiplier, 2.0)
        elif any(tier in source_lower for tier in TIER_2_SOURCES):
            tier_multiplier = max(tier_multiplier, 1.5)
    
    # Diversity bonus (exponential)
    diversity_bonus = 1.0
    if len(sources) == 2:
        diversity_bonus = 1.5
    elif len(sources) >= 3:
        diversity_bonus = 2.0
    
    return base_score * tier_multiplier * diversity_bonus

def detect_timeframe(contexts):
    """Detect investment timeframe mentioned."""
    all_text = ' '.join([c.get('subject', '') + ' ' + c.get('preview', '') for c in contexts]).lower()
    
    if any(kw in all_text for kw in ['long term', 'long-term', 'hold for', 'years', 'decade']):
        return 'long_term'
    elif any(kw in all_text for kw in ['trade', 'swing', 'momentum', 'catalyst']):
        return 'short_term'
    return 'unspecified'

def find_hidden_plays(ticker):
    """Find supply chain / second-order beneficiaries when megacap is mentioned."""
    ticker = ticker.upper()
    plays = []
    
    if ticker in HIDDEN_PLAYS:
        for category, tickers in HIDDEN_PLAYS[ticker].items():
            plays.append({
                'category': category,
                'tickers': tickers,
                'reason': f"{ticker} demand drives {category} growth"
            })
    
    return plays

def calculate_recency_bonus(contexts):
    """Bonus for recent first mentions or increasing velocity."""
    if not contexts:
        return 0
    
    dates = []
    for ctx in contexts:
        date_str = ctx.get('date', '')
        if date_str:
            try:
                # Try to parse various date formats
                d = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                dates.append(d)
            except:
                pass
    
    if not dates:
        return 0
    
    dates.sort()
    newest = dates[-1]
    oldest = dates[0]
    
    # First mention within 30 days
    days_since_first = (datetime.now(newest.tzinfo) - oldest).days
    if days_since_first <= 30:
        return 15
    
    # Increasing velocity (more recent mentions)
    if len(dates) >= 3:
        recent_count = sum(1 for d in dates if (datetime.now(d.tzinfo) - d).days <= 7)
        if recent_count >= 2:
            return 10
    
    return 0

def analyze_tickers():
    """Main analysis function with enhanced scoring."""
    # Load all sources
    all_content = []
    
    # Load emails - lower base weight unless disruption keywords present
    for json_file in INBOX_DIR.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                data['source_type'] = 'email'
                data['source_weight'] = 0.5  # Base weight for newsletters
                
                # Check for disruption keywords to boost signal
                content_str = str(data.get('subject', '')) + ' ' + str(data.get('content_preview', ''))
                content_lower = content_str.lower()
                disruption_matches = sum(1 for kw in DISRUPTION_KEYWORDS if kw in content_lower)
                
                if disruption_matches > 0:
                    # Boost email weight significantly when disruption is mentioned
                    data['source_weight'] = min(1.5, 0.5 + (disruption_matches * 0.25))
                    data['disruption_signal'] = True
                
                all_content.append(data)
        except Exception as e:
            print(f"Error loading {json_file}: {e}")
    
    # Load transcripts - higher base weight (podcasts drive focus)
    for txt_file in TRANSCRIPT_DIR.glob("*.txt"):
        try:
            with open(txt_file, 'r') as f:
                content = f.read()
                # Extract tickers from transcript (simple pattern)
                tickers = re.findall(r'\b([A-Z]{1,5})\b', content)
                all_content.append({
                    'source_type': 'transcript',
                    'source_weight': 2.0,  # Podcasts drive focus - 4x base weight of emails
                    'source': txt_file.stem,
                    'extracted_tickers': list(set(tickers)),
                    'content_preview': content[:500],
                    'date': datetime.fromtimestamp(txt_file.stat().st_mtime).isoformat()
                })
        except Exception as e:
            print(f"Error loading {txt_file}: {e}")
    
    # Aggregate ticker data
    ticker_data = defaultdict(lambda: {
        'mentions': 0.0,  # Now weighted (can be fractional)
        'weighted_mention_count': 0,  # Raw count of mentions
        'sources': set(),
        'contexts': [],
        'first_seen': None,
        'last_seen': None
    })
    
    for item in all_content:
        tickers = item.get('extracted_tickers', [])
        source = item.get('sender', item.get('source', 'Unknown'))
        subject = item.get('subject', item.get('source', ''))
        preview = item.get('content_preview', '')[:300]
        date = item.get('date', '')
        source_weight = item.get('source_weight', 1.0)  # Default weight
        source_type = item.get('source_type', 'unknown')
        
        for ticker in tickers:
            ticker = ticker.upper()
            # Filter out common words that look like tickers
            common_words = {'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'HAD', 'HOT', 'HIS', 'HOW', 'MAN', 'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO', 'BOY', 'DID', 'ITS', 'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'DAD', 'MOM', 'AI', 'US', 'COVID', 'OK', 'ETF', 'IPO', 'EPS', 'GDP', 'CEO', 'CFO', 'CTO', 'VIP', 'NBA', 'NFL', 'MLB', 'FBI', 'CIA', 'IRS', 'FDA', 'SEC', 'FTC', 'DOJ', 'YES', 'NO', 'GO', 'DO', 'IF', 'UP', 'SO', 'ME', 'MY', 'WE', 'HE', 'IT', 'BE', 'BY', 'ON', 'TO', 'OF', 'IN', 'IS', 'AT', 'AS', 'OR', 'AN', 'TV', 'PC', 'CD', 'US', 'UK', 'EU', 'UN', 'VS', 'HR', 'IT', 'RIP', 'LOL', 'OMG', 'WOW', 'BIG', 'TOP', 'BEST', 'NEW', 'GOOD', 'BAD', 'HIGH', 'LOW', 'FAST', 'SLOW', 'HARD', 'EASY', 'TRUE', 'FALSE', 'REAL', 'FAKE', 'OPEN', 'CLOSE', 'LONG', 'SHORT', 'BUY', 'SELL', 'HOLD', 'CALL', 'PUT', 'BULL', 'BEAR', 'MOON', 'REKT', 'HODL', 'FUD', 'FOMO', 'ATH', 'ATL'}
            if ticker in common_words:
                continue
            if len(ticker) < 2 or len(ticker) > 5:
                continue
            # Must be all letters (no numbers or special chars for now)
            if not ticker.isalpha():
                continue
                
            data = ticker_data[ticker]
            # Weighted mentions - podcasts count more than newsletters
            data['mentions'] += source_weight
            data['weighted_mention_count'] = data.get('weighted_mention_count', 0) + 1
            data['sources'].add(source)
            data['contexts'].append({
                'subject': subject,
                'preview': preview,
                'source': source,
                'date': date,
                'source_type': source_type,
                'source_weight': source_weight
            })
            
            if not data['first_seen']:
                data['first_seen'] = date
            data['last_seen'] = date
    
    # Calculate enhanced scores
    scored_tickers = []
    
    for ticker, data in ticker_data.items():
        # Base mentions score
        mention_score = data['mentions'] * 10
        
        # Conviction analysis
        conviction_score = detect_conviction_score(data['contexts'])
        
        # Source diversity
        source_score = calculate_source_diversity_score(data['sources'], data['contexts'])
        
        # Contrarian signal
        contrarian_signal = detect_contrarian_signal(data['contexts'])
        contrarian_bonus = 0
        if contrarian_signal == 'contrarian_positive':
            contrarian_bonus = 20
        elif contrarian_signal == 'crowded_warning':
            contrarian_bonus = -30
        
        # Timeframe
        timeframe = detect_timeframe(data['contexts'])
        timeframe_bonus = 5 if timeframe == 'long_term' else 0
        
        # Recency
        recency_bonus = calculate_recency_bonus(data['contexts'])
        
        # Hidden plays
        hidden_plays = find_hidden_plays(ticker)
        hidden_play_bonus = 15 if hidden_plays else 0
        
        # Total score
        total_score = (mention_score + 
                      conviction_score + 
                      source_score + 
                      contrarian_bonus + 
                      timeframe_bonus + 
                      recency_bonus +
                      hidden_play_bonus)
        
        # Count source types for reporting
        transcript_count = sum(1 for ctx in data['contexts'] if ctx.get('source_type') == 'transcript')
        email_count = sum(1 for ctx in data['contexts'] if ctx.get('source_type') == 'email')
        disruption_mentions = sum(1 for ctx in data['contexts'] if ctx.get('disruption_signal'))
        
        scored_tickers.append({
            'ticker': ticker,
            'score': total_score,
            'breakdown': {
                'mentions': mention_score,
                'conviction': conviction_score,
                'source_diversity': source_score,
                'contrarian': contrarian_bonus,
                'timeframe': timeframe_bonus,
                'recency': recency_bonus,
                'hidden_play_potential': hidden_play_bonus
            },
            'mentions': data['mentions'],
            'raw_mention_count': data['weighted_mention_count'],
            'unique_sources': len(data['sources']),
            'sources': list(data['sources']),
            'source_breakdown': {
                'transcripts': transcript_count,
                'emails': email_count,
                'disruption_signals': disruption_mentions
            },
            'conviction_level': 'high' if conviction_score > 50 else ('medium' if conviction_score > 20 else 'low'),
            'contrarian_signal': contrarian_signal,
            'timeframe': timeframe,
            'hidden_plays': hidden_plays,
            'contexts': data['contexts'][:3],
            'first_seen': data['first_seen'],
            'last_seen': data['last_seen']
        })
    
    # Sort by score
    scored_tickers.sort(key=lambda x: x['score'], reverse=True)
    
    return scored_tickers

def categorize_picks(scored_tickers):
    """Categorize picks into different types."""
    categories = {
        'consensus_buys': [],
        'hidden_gems': [],
        'contrarian_plays': [],
        'early_signals': [],
        'thematic': []
    }
    
    for ticker in scored_tickers[:20]:  # Top 20
        # Consensus buys: High score, multiple sources, high conviction
        if (ticker['score'] > 100 and 
            ticker['unique_sources'] >= 2 and 
            ticker['conviction_level'] == 'high'):
            categories['consensus_buys'].append(ticker)
        
        # Hidden gems: Has hidden plays, not a mega-cap
        elif ticker['hidden_plays'] and ticker['ticker'] not in ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA']:
            categories['hidden_gems'].append(ticker)
        
        # Contrarian plays: Explicit contrarian signal
        elif ticker['contrarian_signal'] == 'contrarian_positive':
            categories['contrarian_plays'].append(ticker)
        
        # Early signals: High recency bonus, few total mentions
        elif ticker['breakdown']['recency'] > 0 and ticker['mentions'] <= 3:
            categories['early_signals'].append(ticker)
        
        # Thematic: Remaining high scorers
        elif ticker['score'] > 50:
            categories['thematic'].append(ticker)
    
    return categories

def generate_enhanced_report():
    """Generate the final enhanced report."""
    print("=" * 60)
    print("Enhanced Stock Analysis Pipeline")
    print("=" * 60)
    
    scored = analyze_tickers()
    
    if not scored:
        print("\n⚠️  No tickers found")
        return None
    
    categories = categorize_picks(scored)
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'total_tickers_analyzed': len(scored),
        'top_5_overall': scored[:5],
        'categories': categories,
        'all_scored': scored[:30]
    }
    
    # Save JSON
    with open(ANALYSIS_DIR / 'top_picks_enhanced.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    # Generate markdown report
    with open(ANALYSIS_DIR / 'top_picks_enhanced.md', 'w') as f:
        f.write("# Enhanced Stock Analysis\n\n")
        f.write(f"Generated: {report['generated_at']}\n\n")
        f.write("## Source Weighting\n\n")
        f.write("- **🎙️ Podcasts/Transcripts:** 2.0x weight (drive primary focus)\n")
        f.write("- **📧 Newsletters:** 0.5x base weight\n")
        f.write("- **⚡ Disruption Boost:** Newsletters mentioning disruption keywords get up to 1.5x\n\n")
        f.write("---\n\n")
        
        # Overall top 5
        f.write("## 🏆 Top 5 Overall\n\n")
        for i, pick in enumerate(report['top_5_overall'], 1):
            f.write(f"### {i}. {pick['ticker']} (Score: {pick['score']})\n\n")
            src_breakdown = pick.get('source_breakdown', {})
            f.write(f"- **Weighted Mentions:** {pick['mentions']:.1f} | **Raw Count:** {pick.get('raw_mention_count', 0)}\n")
            f.write(f"- **Sources:** {pick['unique_sources']} (🎙️ Podcasts: {src_breakdown.get('transcripts', 0)}, 📧 Newsletters: {src_breakdown.get('emails', 0)})")
            if src_breakdown.get('disruption_signals', 0) > 0:
                f.write(f" | ⚡ Disruption: {src_breakdown['disruption_signals']}")
            f.write("\n")
            f.write(f"- **Conviction:** {pick['conviction_level']} | **Timeframe:** {pick['timeframe']}\n")
            f.write(f"- **Signal:** {pick['contrarian_signal']}\n\n")
            
            if pick['hidden_plays']:
                f.write("**Hidden Play Connections:**\n")
                for play in pick['hidden_plays'][:2]:
                    f.write(f"- {play['category']}: {', '.join(play['tickers'][:3])}\n")
                f.write("\n")
            
            if pick['contexts']:
                ctx = pick['contexts'][0]
                f.write(f"**Latest:** {ctx['subject'][:80]}...\n\n")
        
        # Categories
        for cat_name, picks in categories.items():
            if picks:
                f.write(f"\n## {'📊' if cat_name == 'consensus_buys' else '💎' if cat_name == 'hidden_gems' else '🎯' if cat_name == 'contrarian_plays' else '🌱' if cat_name == 'early_signals' else '🎨'} {cat_name.replace('_', ' ').title()}\n\n")
                for pick in picks[:5]:
                    f.write(f"- **{pick['ticker']}** (Score: {pick['score']}) — {pick['unique_sources']} sources, {pick['conviction_level']} conviction\n")
    
    # Display results
    print(f"\n✓ Analyzed {len(scored)} tickers")
    print(f"✓ Generated categories: {', '.join(k for k, v in categories.items() if v)}")
    
    print("\n" + "=" * 60)
    print("TOP 5 OVERALL")
    print("=" * 60)
    
    for i, pick in enumerate(scored[:5], 1):
        src = pick.get('source_breakdown', {})
        print(f"\n{i}. {pick['ticker']} | Score: {pick['score']}")
        print(f"   Weighted: {pick['mentions']:.1f} | 🎙️ {src.get('transcripts', 0)} 📧 {src.get('emails', 0)} | Conviction: {pick['conviction_level']}")
        if src.get('disruption_signals', 0) > 0:
            print(f"   ⚡ Disruption signals: {src['disruption_signals']}")
        print(f"   Signal: {pick['contrarian_signal']}")
        if pick['hidden_plays']:
            plays = [p['category'] for p in pick['hidden_plays']]
            print(f"   Hidden plays: {', '.join(plays)}")
    
    print("\n" + "=" * 60)
    
    return report

if __name__ == "__main__":
    generate_enhanced_report()
