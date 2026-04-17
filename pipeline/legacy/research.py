#!/usr/bin/env python3
"""
Advanced theme extraction and research pipeline.
Extracts concepts, maps supply chains, finds hidden plays.
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Directories
INBOX_DIR = Path.home() / ".openclaw/workspace/pipeline/inbox"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
RESEARCH_DIR = Path.home() / ".openclaw/workspace/pipeline/research"

RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

# Theme patterns to watch for
THEME_PATTERNS = {
    "ai_disruption": [
        r'\bai\b.*\b(disrupt|replace|kill|destroy|eliminate)\b',
        r'\b(disrupt|replace).{0,30}\bwith ai\b',
        r'\bai is (killing|hurting|crushing)\b',
    ],
    "supply_bottleneck": [
        r'\b(shortage|bottleneck|constraint|limited supply)\b',
        r'\bcan\'t (get|find|source|buy)\b',
        r'\bdemand exceeds supply\b',
        r'\bbackorder|backlog\b',
    ],
    "demand_surge": [
        r'\b(soaring|skyrocketing|surging|exploding) demand\b',
        r'\borders? (up|surged|doubled|tripled)\b',
        r'\bsold out\b',
        r'\bcan\'t keep up\b',
    ],
    "regulatory_risk": [
        r'\b(regulation|regulatory|sec|ftc|doj|antitrust)\b',
        r'\b(law|bill|legislation).{0,20}\b(propose|pass|enact)\b',
    ],
    "margin_pressure": [
        r'\b(margin|profit).{0,20}\b(compress|squeeze|pressure|decline)\b',
        r'\bpricing power\b',
        r'\bcost (increase|rising)\b',
    ]
}

# Industry supply chain mapping
SUPPLY_CHAIN = {
    "ai_chips": {
        "upstream": ["lithography", "silicon_wafers", "photoresist", "eda_software"],
        "downstream": ["memory", "servers", "data_centers", "power", "cooling", "networking"],
        "key_players": ["NVDA", "AMD", "INTC", "TSM", "ASML"]
    },
    "memory": {
        "upstream": ["ai_chips", "raw_materials", "manufacturing_equipment"],
        "downstream": ["servers", "data_centers", "ai_applications", "edge_computing"],
        "key_players": ["MU", "WDC", "STX", "SKHY", "Samsung"]
    },
    "data_centers": {
        "upstream": ["ai_chips", "memory", "power", "cooling", "land", "fiber"],
        "downstream": ["cloud_providers", "ai_services", "enterprise"],
        "key_players": ["GOOGL", "MSFT", "AMZN", "META", "DLR", "EQIX"]
    },
    "power": {
        "upstream": ["natural_gas", "nuclear", "solar", "wind", "grid_infrastructure"],
        "downstream": ["data_centers", "manufacturing", "charging"],
        "key_players": ["NEE", "D", "SO", "AEP", "CEG", "SMR"]
    },
    "trucking": {
        "upstream": ["fuel", "insurance", "drivers", "trucks", "software"],
        "downstream": ["retail", "manufacturing", "ecommerce", "freight_brokers"],
        "key_players": ["JBHT", "ODFL", "LSTR", "KNX", "SAIA", "UPS", "FDX"]
    },
    "software": {
        "upstream": ["developers", "cloud", "open_source"],
        "downstream": ["enterprise", "consumers", "industries"],
        "key_players": ["MSFT", "ORCL", "CRM", "NOW", "ADBE", "INTU"]
    }
}

# Companies by industry exposure
INDUSTRY_EXPOSURE = {
    "ai_power_demand": ["NEE", "D", "SO", "AEP", "CEG", "SMR", "OKLO", "BWXT", "CCJ", "URA"],
    "ai_cooling": ["VST", "CWST", "XYL", "AWK", "WTRG"],
    "ai_networking": ["ANET", "AVGO", "MRVL", "CSCO", "FFIV"],
    "lithography": ["ASML", "AMAT", "LRCX", "KLAC"],
    "data_center_reits": ["DLR", "EQIX", "AMT", "CCI", "QTS"],
    "freight_tech": ["PCAR", "CMI", "ETRN", "WERN", "HTLD"],
    "insurance_trucking": ["TRV", "CB", "PGR", "ALL"],
    "fuel": ["CVX", "XOM", "COP", "MPC", "VLO"],
}

def load_all_content():
    """Load all emails and transcripts."""
    all_content = []
    
    # Load emails
    for json_file in INBOX_DIR.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                all_content.append({
                    "source": data.get("sender", "Unknown"),
                    "subject": data.get("subject", ""),
                    "content": data.get("content", ""),
                    "date": data.get("date", ""),
                    "type": "email"
                })
        except Exception as e:
            print(f"Error loading {json_file}: {e}")
    
    # Load transcripts
    for txt_file in TRANSCRIPT_DIR.glob("*.txt"):
        try:
            with open(txt_file, 'r') as f:
                content = f.read()
                all_content.append({
                    "source": txt_file.stem,
                    "subject": f"Podcast: {txt_file.stem}",
                    "content": content,
                    "date": str(datetime.now()),
                    "type": "podcast"
                })
        except Exception as e:
            print(f"Error loading {txt_file}: {e}")
    
    return all_content

def extract_themes(content_item):
    """Extract themes from a content item."""
    full_text = f"{content_item['subject']} {content_item['content']}".lower()
    
    themes_found = []
    for theme_name, patterns in THEME_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, full_text, re.IGNORECASE):
                themes_found.append(theme_name)
                break
    
    return themes_found

def extract_explicit_tickers(text):
    """Extract explicit $TICKER mentions."""
    pattern = r'\$([A-Z]{1,5})\b'
    return list(set(re.findall(pattern, text)))

def extract_company_mentions(text):
    """Extract company name mentions."""
    # Map of company names to tickers
    company_map = {
        "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT",
        "google": "GOOGL", "alphabet": "GOOGL", "meta": "META",
        "facebook": "META", "amazon": "AMZN", "tesla": "TSLA",
        "netflix": "NFLX", "salesforce": "CRM", "oracle": "ORCL",
        "snowflake": "SNOW", "palantir": "PLTR", "mongodb": "MDB",
        "datadog": "DDOG", "cloudflare": "NET", "twilio": "TWLO",
        "workday": "WDAY", "servicenow": "NOW", "vmware": "VMW",
        "crowdstrike": "CRWD", "zscaler": "ZS", "okta": "OKTA",
        "sentinelone": "S", "cisco": "CSCO", "juniper": "JNPR",
        "arista": "ANET", "broadcom": "AVGO", "marvell": "MRVL",
        "micron": "MU", "western digital": "WDC", "seagate": "STX",
        "intel": "INTC", "amd": "AMD", "tsmc": "TSM",
        "asml": "ASML", "applied materials": "AMAT", "lam research": "LRCX",
        "kla": "KLAC", "texas instruments": "TXN", "qualcomm": "QCOM",
        "analog devices": "ADI", "nxp": "NXPI", "on semi": "ON",
        "microchip": "MCHP", "xilinx": "XLNX"
    }
    
    tickers = []
    text_lower = text.lower()
    
    for company, ticker in company_map.items():
        if company in text_lower:
            tickers.append(ticker)
    
    return list(set(tickers))

def analyze_industry_mentions(content_items):
    """Track which industries are being mentioned in disruption contexts."""
    industry_mentions = defaultdict(lambda: {
        "mentions": 0,
        "disruption_signals": [],
        "sources": set(),
        "contexts": []
    })
    
    for item in content_items:
        text = f"{item['subject']} {item['content']}".lower()
        themes = extract_themes(item)
        
        for industry, data in SUPPLY_CHAIN.items():
            # Check if industry mentioned
            if industry.replace("_", " ") in text or industry in text:
                industry_mentions[industry]["mentions"] += 1
                industry_mentions[industry]["sources"].add(item['source'][:50])
                
                # Check for disruption signals
                if "ai_disruption" in themes or "disrupt" in text:
                    industry_mentions[industry]["disruption_signals"].append({
                        "source": item['subject'][:80],
                        "context": item['content'][:200]
                    })
                
                industry_mentions[industry]["contexts"].append({
                    "subject": item['subject'][:80],
                    "source": item['source'][:50]
                })
    
    return industry_mentions

def find_hidden_plays(industry_mentions, content_items):
    """Find companies in related industries that might be affected."""
    hidden_plays = []
    
    for industry, data in industry_mentions.items():
        if data["disruption_signals"]:
            # This industry is being disrupted
            # Look at downstream/supply chain effects
            
            if industry in SUPPLY_CHAIN:
                chain = SUPPLY_CHAIN[industry]
                
                # Check upstream (what feeds this industry)
                for upstream in chain.get("upstream", []):
                    if upstream in INDUSTRY_EXPOSURE:
                        for ticker in INDUSTRY_EXPOSURE[upstream]:
                            hidden_plays.append({
                                "ticker": ticker,
                                "theme": f"Upstream of disrupted {industry}",
                                "logic": f"{upstream} supplies {industry} which is being disrupted by AI",
                                "affected_industry": industry
                            })
                
                # Check downstream (who uses this industry)
                for downstream in chain.get("downstream", []):
                    if downstream in INDUSTRY_EXPOSURE:
                        for ticker in INDUSTRY_EXPOSURE[downstream]:
                            hidden_plays.append({
                                "ticker": ticker,
                                "theme": f"Downstream of disrupted {industry}",
                                "logic": f"{downstream} depends on {industry} which is being disrupted",
                                "affected_industry": industry
                            })
    
    return hidden_plays

def find_supply_bottlenecks(content_items):
    """Identify potential supply chain bottlenecks from AI demand."""
    bottlenecks = []
    
    for item in content_items:
        text = f"{item['subject']} {item['content']}".lower()
        themes = extract_themes(item)
        
        if "supply_bottleneck" in themes or "demand_surge" in themes:
            # Look for mentions of specific bottlenecks
            bottleneck_keywords = {
                "power": "ai_power_demand",
                "electricity": "ai_power_demand",
                "energy": "ai_power_demand",
                "cooling": "ai_cooling",
                "water": "ai_cooling",
                "network": "ai_networking",
                "bandwidth": "ai_networking",
                "lithography": "lithography",
                "wafers": "lithography",
                "memory": "memory"
            }
            
            for keyword, category in bottleneck_keywords.items():
                if keyword in text:
                    if category in INDUSTRY_EXPOSURE:
                        for ticker in INDUSTRY_EXPOSURE[category]:
                            bottlenecks.append({
                                "ticker": ticker,
                                "category": category,
                                "bottleneck": keyword,
                                "source": item['subject'][:80],
                                "context": item['content'][:150]
                            })
    
    return bottlenecks

def generate_research_report(content_items, industry_mentions, hidden_plays, bottlenecks):
    """Generate comprehensive research report."""
    
    # Count explicit ticker mentions
    all_tickers = defaultdict(lambda: {"mentions": 0, "sources": set(), "contexts": []})
    
    for item in content_items:
        text = f"{item['subject']} {item['content']}"
        tickers = extract_explicit_tickers(text) + extract_company_mentions(text)
        
        for ticker in tickers:
            all_tickers[ticker]["mentions"] += 1
            all_tickers[ticker]["sources"].add(item['source'][:50])
            all_tickers[ticker]["contexts"].append({
                "subject": item['subject'][:80],
                "source": item['source'][:50]
            })
    
    # Sort by mentions
    top_tickers = sorted(
        [(t, d) for t, d in all_tickers.items()],
        key=lambda x: x[1]["mentions"],
        reverse=True
    )[:20]
    
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_sources_analyzed": len(content_items),
        "themes_detected": {
            theme: sum(1 for item in content_items if theme in extract_themes(item))
            for theme in THEME_PATTERNS.keys()
        },
        "industry_analysis": {
            industry: {
                "mentions": data["mentions"],
                "sources": list(data["sources"]),
                "disruption_count": len(data["disruption_signals"]),
                "contexts": data["contexts"][:3]
            }
            for industry, data in sorted(
                industry_mentions.items(),
                key=lambda x: x[1]["mentions"],
                reverse=True
            )[:10]
        },
        "explicit_ticker_mentions": [
            {
                "ticker": ticker,
                "mentions": data["mentions"],
                "sources": list(data["sources"]),
                "contexts": data["contexts"][:2]
            }
            for ticker, data in top_tickers
        ],
        "hidden_plays": hidden_plays[:15],
        "supply_bottlenecks": bottlenecks[:15]
    }
    
    return report

def save_research_report(report):
    """Save report to research directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # JSON version
    json_path = RESEARCH_DIR / f"research_{timestamp}.json"
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Also save as latest
    latest_json = RESEARCH_DIR / "latest_research.json"
    with open(latest_json, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Markdown version
    md_path = RESEARCH_DIR / "latest_research.md"
    with open(md_path, 'w') as f:
        f.write("# Investment Research Report\n\n")
        f.write(f"Generated: {report['generated_at']}\n\n")
        f.write(f"Sources analyzed: {report['total_sources_analyzed']}\n\n")
        
        f.write("## Detected Themes\n\n")
        for theme, count in report['themes_detected'].items():
            if count > 0:
                f.write(f"- **{theme}**: {count} mentions\n")
        f.write("\n")
        
        f.write("## Industry Analysis\n\n")
        for industry, data in report['industry_analysis'].items():
            f.write(f"### {industry.replace('_', ' ').title()}\n")
            f.write(f"- Mentions: {data['mentions']}\n")
            f.write(f"- Disruption signals: {data['disruption_count']}\n")
            if data['contexts']:
                f.write(f"- Latest: {data['contexts'][0]['subject']}\n")
            f.write("\n")
        
        f.write("## Explicit Ticker Mentions\n\n")
        for item in report['explicit_ticker_mentions'][:10]:
            f.write(f"### {item['ticker']} ({item['mentions']} mentions)\n")
            f.write(f"- Sources: {', '.join(item['sources'][:3])}\n")
            if item['contexts']:
                f.write(f"- Context: {item['contexts'][0]['subject']}\n")
            f.write("\n")
        
        f.write("## Hidden Plays (Supply Chain & Second-Order Effects)\n\n")
        for play in report['hidden_plays'][:10]:
            f.write(f"### {play['ticker']}\n")
            f.write(f"- Theme: {play['theme']}\n")
            f.write(f"- Logic: {play['logic']}\n")
            f.write(f"- Affected Industry: {play['affected_industry']}\n\n")
        
        f.write("## Supply Chain Bottlenecks\n\n")
        for item in report['supply_bottlenecks'][:10]:
            f.write(f"### {item['ticker']}\n")
            f.write(f"- Category: {item['category']}\n")
            f.write(f"- Bottleneck: {item['bottleneck']}\n")
            f.write(f"- Source: {item['source']}\n\n")
    
    return json_path, md_path

if __name__ == "__main__":
    print("=" * 60)
    print("Advanced Research Analysis Pipeline")
    print("=" * 60)
    
    # Load all content
    print("\nLoading content...")
    content_items = load_all_content()
    
    if not content_items:
        print("No content found. Run ingest.py first or add transcripts.")
        exit(1)
    
    print(f"✓ Loaded {len(content_items)} content items")
    
    # Analyze
    print("\nAnalyzing industries and themes...")
    industry_mentions = analyze_industry_mentions(content_items)
    
    print("Finding hidden plays...")
    hidden_plays = find_hidden_plays(industry_mentions, content_items)
    
    print("Identifying supply bottlenecks...")
    bottlenecks = find_supply_bottlenecks(content_items)
    
    # Generate report
    print("Generating research report...")
    report = generate_research_report(content_items, industry_mentions, hidden_plays, bottlenecks)
    
    # Save
    json_path, md_path = save_research_report(report)
    
    # Display
    print("\n" + "=" * 60)
    print("RESEARCH SUMMARY")
    print("=" * 60)
    
    print(f"\nThemes detected:")
    for theme, count in report['themes_detected'].items():
        if count > 0:
            print(f"  - {theme}: {count}")
    
    print(f"\nTop industries mentioned:")
    for industry, data in list(report['industry_analysis'].items())[:5]:
        print(f"  - {industry}: {data['mentions']} mentions")
    
    print(f"\nHidden plays identified: {len(hidden_plays)}")
    for play in hidden_plays[:5]:
        print(f"  - {play['ticker']}: {play['logic'][:60]}...")
    
    print(f"\nSupply bottlenecks: {len(bottlenecks)}")
    
    print("\n" + "=" * 60)
    print(f"✓ Reports saved:")
    print(f"   JSON: {json_path}")
    print(f"   Markdown: {md_path}")
    print(f"   Latest: {RESEARCH_DIR}/latest_research.json")
