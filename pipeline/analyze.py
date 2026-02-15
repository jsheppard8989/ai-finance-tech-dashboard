#!/usr/bin/env python3
"""
Stock analysis and scoring from newsletter data.
Reads ingested emails and produces top 5 stock picks.
"""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Directories
INBOX_DIR = Path.home() / ".openclaw/workspace/pipeline/inbox"
ANALYSIS_DIR = Path.home() / ".openclaw/workspace/pipeline/analysis"

# Ensure analysis dir exists
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

def load_all_emails():
    """Load all processed email JSON files."""
    emails = []
    for json_file in INBOX_DIR.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                emails.append(data)
        except Exception as e:
            print(f"Error loading {json_file}: {e}")
    return emails

def score_tickers(emails):
    """Score tickers based on mention frequency and context."""
    ticker_data = defaultdict(lambda: {
        "mentions": 0,
        "sources": set(),
        "contexts": [],
        "first_seen": None,
        "last_seen": None
    })
    
    for email in emails:
        tickers = email.get("extracted_tickers", [])
        sender = email.get("sender", "Unknown")
        subject = email.get("subject", "")
        content_preview = email.get("content_preview", "")[:200]
        date_str = email.get("date", "")
        
        for ticker in tickers:
            ticker = ticker.upper()
            data = ticker_data[ticker]
            
            data["mentions"] += 1
            data["sources"].add(sender)
            
            # Store context (subject + preview)
            context = {
                "subject": subject[:80],
                "preview": content_preview,
                "source": sender[:50],
                "date": date_str
            }
            data["contexts"].append(context)
            
            # Track dates
            if not data["first_seen"]:
                data["first_seen"] = date_str
            data["last_seen"] = date_str
    
    return ticker_data

def calculate_scores(ticker_data):
    """Calculate final scores for each ticker."""
    scored = []
    
    for ticker, data in ticker_data.items():
        # Base score from mention count
        mention_score = data["mentions"] * 10
        
        # Diversity bonus (mentioned by multiple sources)
        source_bonus = len(data["sources"]) * 15
        
        # Recency bonus (more recent = higher)
        # (Simplified - could be more sophisticated with date parsing)
        
        total_score = mention_score + source_bonus
        
        scored.append({
            "ticker": ticker,
            "score": total_score,
            "mentions": data["mentions"],
            "unique_sources": len(data["sources"]),
            "sources": list(data["sources"]),
            "contexts": data["contexts"][:3],  # Top 3 contexts
            "first_seen": data["first_seen"],
            "last_seen": data["last_seen"]
        })
    
    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored

def generate_report(top_picks, all_emails):
    """Generate analysis report."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_emails_processed": len(all_emails),
        "unique_tickers_found": len(top_picks),
        "top_5_picks": top_picks[:5],
        "all_scored": top_picks[:20]  # Top 20 for reference
    }
    
    return report

def save_report(report):
    """Save report to analysis directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # JSON version
    json_path = ANALYSIS_DIR / f"top_picks_{timestamp}.json"
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Also save as latest
    latest_path = ANALYSIS_DIR / "top_picks.json"
    with open(latest_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Markdown version for readability
    md_path = ANALYSIS_DIR / "top_picks.md"
    with open(md_path, 'w') as f:
        f.write("# Top Stock Picks Analysis\n\n")
        f.write(f"Generated: {report['generated_at']}\n\n")
        f.write(f"Emails processed: {report['total_emails_processed']}\n\n")
        
        f.write("## Top 5 Picks\n\n")
        for i, pick in enumerate(report['top_5_picks'], 1):
            f.write(f"### {i}. {pick['ticker']} (Score: {pick['score']})\n\n")
            f.write(f"- **Mentions:** {pick['mentions']}\n")
            f.write(f"- **Unique Sources:** {pick['unique_sources']}\n")
            f.write(f"- **Sources:** {', '.join(pick['sources'])}\n\n")
            
            if pick['contexts']:
                f.write("**Recent Mentions:**\n\n")
                for ctx in pick['contexts'][:2]:
                    f.write(f"- *{ctx['subject']}* ({ctx['source']})\n")
                    f.write(f"  > {ctx['preview'][:120]}...\n\n")
            f.write("\n")
        
        f.write("---\n\n")
        f.write(f"## All Tickers Scored ({len(report['all_scored'])} total)\n\n")
        for pick in report['all_scored']:
            f.write(f"- **{pick['ticker']}**: Score {pick['score']} ({pick['mentions']} mentions, {pick['unique_sources']} sources)\n")
    
    return json_path, md_path

if __name__ == "__main__":
    print("=" * 50)
    print("Stock Analysis Pipeline")
    print("=" * 50)
    
    # Load all emails
    print("\nLoading processed emails...")
    all_emails = load_all_emails()
    
    if not all_emails:
        print("\n⚠️  No emails found in inbox/")
        print("   Run: python3 ingest.py")
        print("   Or forward newsletters to jsheppard8989@gmail.com")
        exit(1)
    
    print(f"✓ Loaded {len(all_emails)} emails")
    
    # Score tickers
    print("\nScoring tickers...")
    ticker_data = score_tickers(all_emails)
    print(f"✓ Found {len(ticker_data)} unique tickers")
    
    # Calculate final scores
    scored = calculate_scores(ticker_data)
    
    # Generate report
    report = generate_report(scored, all_emails)
    
    # Save results
    json_path, md_path = save_report(report)
    
    # Display results
    print("\n" + "=" * 50)
    print("TOP 5 STOCK PICKS")
    print("=" * 50)
    
    for i, pick in enumerate(report['top_5_picks'], 1):
        print(f"\n{i}. {pick['ticker']}")
        print(f"   Score: {pick['score']} | Mentions: {pick['mentions']} | Sources: {pick['unique_sources']}")
        if pick['contexts']:
            ctx = pick['contexts'][0]
            print(f"   Latest: {ctx['subject'][:60]}...")
    
    print("\n" + "=" * 50)
    print(f"\n✓ Report saved:")
    print(f"   JSON: {json_path}")
    print(f"   Markdown: {md_path}")
    print(f"   Latest: {ANALYSIS_DIR / 'top_picks.json'}")
