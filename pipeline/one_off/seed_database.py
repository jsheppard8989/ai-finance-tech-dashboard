#!/usr/bin/env python3
"""
Populate database with sample archive data for testing.
Run once to seed the database with realistic content.
"""

import sys
from pathlib import Path
from datetime import datetime, date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db

def seed_database():
    """Add sample data to database."""
    db = get_db()
    
    print("Seeding database with sample archive data...")
    
    with db._get_connection() as conn:
        
        # === DEFINITIONS ===
        print("\n📖 Adding definitions...")
        
        definitions = [
            # Active on main page
            {
                'term': 'Dyson Swarm',
                'definition': 'A hypothetical megastructure consisting of a vast array of solar collectors (satellites) orbiting a star to capture its energy output. Unlike a solid Dyson Sphere, a swarm allows for gradual construction and doesn\'t require implausible engineering.',
                'investment_implications': 'As space-based solar power becomes economically viable, companies developing launch capabilities and orbital infrastructure could benefit.',
                'vote_count': 15,
                'display_on_main': 1,
                'display_order': 1
            },
            {
                'term': 'Jevon\'s Paradox',
                'definition': 'An economic phenomenon where increased efficiency in using a resource leads to increased consumption of that resource rather than decreased consumption.',
                'investment_implications': 'As AI makes computation cheaper, total compute demand may explode—benefiting chip makers, data centers, and power providers despite efficiency gains.',
                'vote_count': 12,
                'display_on_main': 1,
                'display_order': 2
            },
            {
                'term': 'Yen Carry Trade',
                'definition': 'A strategy where investors borrow in Japanese yen (low interest rates ~0.25%) and invest in higher-yielding assets (US Treasuries, tech stocks, emerging markets).',
                'investment_implications': 'When the Bank of Japan hikes rates or yen strengthens, unwinds trigger forced selling. Watch JPY/USD >150 as risk signal.',
                'vote_count': 18,
                'display_on_main': 1,
                'display_order': 3
            },
            # Archived definitions
            {
                'term': 'SPAC',
                'definition': 'Special Purpose Acquisition Company. A shell corporation listed on a stock exchange with the purpose of acquiring a private company, thereby making it public without going through the traditional IPO process.',
                'investment_implications': 'SPAC boom of 2020-2021 largely over. Most trading at or below NAV. Limited new issuance.',
                'vote_count': 8,
                'display_on_main': 0,
                'display_order': 0,
                'archived_date': (date.today() - timedelta(days=90)).isoformat(),
                'archived_reason': 'Market cycle shifted - SPAC boom is over'
            },
            {
                'term': 'Meme Stock',
                'definition': 'A stock that gains popularity among retail investors through social media and online forums, often resulting in rapid price increases disconnected from fundamental value.',
                'investment_implications': 'Phenomenon peaked in 2021. Remains relevant for risk management but less systemic impact than during peak retail trading era.',
                'vote_count': 6,
                'display_on_main': 0,
                'display_order': 0,
                'archived_date': (date.today() - timedelta(days=120)).isoformat(),
                'archived_reason': 'Term now mainstream - no longer needs definition'
            }
        ]
        
        for d in definitions:
            conn.execute("""
                INSERT OR IGNORE INTO definitions 
                (term, definition, investment_implications, vote_count, 
                 display_on_main, display_order, added_date, archived_date, archived_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (d['term'], d['definition'], d.get('investment_implications'), 
                  d['vote_count'], d['display_on_main'], d['display_order'],
                  (date.today() - timedelta(days=30)).isoformat(),
                  d.get('archived_date'), d.get('archived_reason')))
        
        print(f"  Added {len(definitions)} definitions")
        
        # === OVERTON WINDOW TERMS ===
        print("\n🪟 Adding Overton Window terms...")
        
        overton_terms = [
            # Active on main page
            {
                'term': 'Neuralink Moment',
                'description': 'The inflection point when brain-computer interfaces shift from experimental to consumer-ready, triggering societal restructuring around cognitive enhancement.',
                'first_detected_date': (date.today() - timedelta(days=14)).isoformat(),
                'last_mentioned_date': (date.today() - timedelta(days=3)).isoformat(),
                'mention_count': 3,
                'source_podcasts': '["Network State Podcast", "Monetary Matters"]',
                'status': 'active',
                'display_on_main': 1,
                'investment_implications': 'BCI hardware, neurotech chips, cognitive enhancement platforms. Early stage - watch for FDA approvals.'
            },
            {
                'term': 'Sovereign Individual Thesis',
                'description': 'The expectation that high-net-worth individuals will increasingly decouple from traditional jurisdictions, seeking digital-first citizenship and asset structures.',
                'first_detected_date': (date.today() - timedelta(days=21)).isoformat(),
                'last_mentioned_date': (date.today() - timedelta(days=5)).isoformat(),
                'mention_count': 2,
                'source_podcasts': '["Monetary Matters"]',
                'status': 'active',
                'display_on_main': 1,
                'investment_implications': 'Digital banking, crypto custody, tax-advantaged jurisdictions, nomad infrastructure.'
            },
            {
                'term': 'Compute Arbitrage',
                'description': 'Exploiting price differentials in AI compute across regions and providers—buying low in unregulated markets, deploying high in enterprise stacks.',
                'first_detected_date': (date.today() - timedelta(days=30)).isoformat(),
                'last_mentioned_date': (date.today() - timedelta(days=10)).isoformat(),
                'mention_count': 4,
                'source_podcasts': '["a16z Live", "Network State Podcast"]',
                'status': 'active',
                'display_on_main': 1,
                'investment_implications': 'GPU cloud providers, distributed compute networks, energy arbitrage plays.'
            },
            # Archived terms
            {
                'term': 'Metaverse Land Rush',
                'description': 'The speculative buying of virtual real estate in metaverse platforms, anticipating future value appreciation as adoption grows.',
                'first_detected_date': (date.today() - timedelta(days=365)).isoformat(),
                'last_mentioned_date': (date.today() - timedelta(days=180)).isoformat(),
                'mention_count': 12,
                'source_podcasts': '["a16z Live", "All-In Podcast"]',
                'status': 'archived',
                'display_on_main': 0,
                'archived_date': (date.today() - timedelta(days=150)).isoformat(),
                'archived_reason': 'Hype cycle ended - no longer emerging',
                'investment_implications': 'Virtual real estate largely collapsed. Concept failed to achieve mainstream traction.'
            },
            {
                'term': 'DeFi Summer',
                'description': 'The 2020-2021 period of explosive growth in decentralized finance protocols, yield farming, and liquidity mining.',
                'first_detected_date': (date.today() - timedelta(days=500)).isoformat(),
                'last_mentioned_date': (date.today() - timedelta(days=200)).isoformat(),
                'mention_count': 25,
                'source_podcasts': '["Bankless", "The Defiant"]',
                'status': 'graduated',
                'display_on_main': 0,
                'archived_date': (date.today() - timedelta(days=180)).isoformat(),
                'archived_reason': 'Term now mainstream in crypto discourse',
                'investment_implications': 'DeFi protocols maturing. Yield farming yields compressed. Infrastructure plays remain relevant.'
            }
        ]
        
        for t in overton_terms:
            conn.execute("""
                INSERT OR IGNORE INTO overton_terms 
                (term, description, first_detected_date, last_mentioned_date, mention_count,
                 source_podcasts, status, display_on_main, archived_date, archived_reason,
                 investment_implications)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (t['term'], t['description'], t['first_detected_date'], t['last_mentioned_date'],
                  t['mention_count'], t['source_podcasts'], t['status'], t['display_on_main'],
                  t.get('archived_date'), t.get('archived_reason'), t.get('investment_implications')))
        
        print(f"  Added {len(overton_terms)} Overton terms")
        
        # === LATEST INSIGHTS ===
        print("\n📰 Adding insights...")
        
        insights = [
            # Active on main page (most recent)
            {
                'title': 'SpaceX/xAI $1.25T Super-Entity',
                'source_type': 'podcast',
                'source_name': 'The Rundown AI',
                'source_date': (date.today() - timedelta(days=2)).isoformat(),
                'summary': 'Elon Musk consolidating Starlink satellite network with xAI Grok infrastructure creates first vertically integrated AI-to-orbit stack.',
                'key_takeaway': 'Vertical integration of AI compute with orbital infrastructure creates durable competitive moats.',
                'tickers_mentioned': '["GOOGL", "NVDA", "AVGO"]',
                'sentiment': 'bullish',
                'display_on_main': 1,
                'display_order': 1
            },
            {
                'title': 'Gold Climax Top Signal',
                'source_type': 'podcast',
                'source_name': 'Monetary Matters',
                'source_date': (date.today() - timedelta(days=5)).isoformat(),
                'summary': 'Milton Berg institutional model flipped net-short across major indices while retail remains 100% long. Historical pattern suggests 8% drawdown.',
                'key_takeaway': 'Risk-off: Reduce momentum exposure. Watch VIX >25.',
                'tickers_mentioned': '["VIX", "SQQQ", "TLT"]',
                'sentiment': 'bearish',
                'display_on_main': 1,
                'display_order': 2
            },
            {
                'title': 'Bitcoin as Hard Asset',
                'source_type': 'podcast',
                'source_name': 'Jack Mallers Show',
                'source_date': (date.today() - timedelta(days=12)).isoformat(),
                'summary': 'New liquidity regime narrative gaining traction - BTC decoupling from tech-correlation as treasury reserve thesis resurfaces.',
                'key_takeaway': 'BTC positioning vs DXY weakness, yen carry unwind scenarios.',
                'tickers_mentioned': '["BTC", "COIN", "MSTR"]',
                'sentiment': 'bullish',
                'display_on_main': 1,
                'display_order': 3
            },
            {
                'title': 'Healthcare AI Moats',
                'source_type': 'podcast',
                'source_name': 'a16z Live',
                'source_date': (date.today() - timedelta(days=21)).isoformat(),
                'summary': 'Tennr and Camber building operational infrastructure rather than clinical AI. First-mover advantage in regulatory capture.',
                'key_takeaway': 'Watch for IPO pipeline in healthtech operations.',
                'tickers_mentioned': '["VEEV", "TDOC", "DOCS"]',
                'sentiment': 'bullish',
                'display_on_main': 1,
                'display_order': 4
            },
            {
                'title': 'Machine-Native Money',
                'source_type': 'podcast',
                'source_name': 'Network State Podcast',
                'source_date': (date.today() - timedelta(days=30)).isoformat(),
                'summary': 'USDC co-founder Sean Neville on deterministic crypto meeting probabilistic AI - identity systems for autonomous agents require new financial rails.',
                'key_takeaway': 'Long-term: Stablecoin infrastructure (COIN, fintech rails).',
                'tickers_mentioned': '["COIN", "PYPL", "SQ"]',
                'sentiment': 'bullish',
                'display_on_main': 1,
                'display_order': 5
            },
            # Archived insights
            {
                'title': 'Fed Pivot Signal',
                'source_type': 'newsletter',
                'source_name': 'Monetary Matters',
                'source_date': (date.today() - timedelta(days=45)).isoformat(),
                'summary': 'Fed funds futures pricing in rate cuts by Q3 2025. Historical analysis of prior pivot signals.',
                'key_takeaway': 'Treasury duration attractive at current yields.',
                'tickers_mentioned': '["TLT", "IEF"]',
                'sentiment': 'bullish',
                'display_on_main': 0,
                'display_order': 0,
                'archived_date': (date.today() - timedelta(days=30)).isoformat(),
                'archived_reason': 'Superseded by newer episodes'
            },
            {
                'title': 'Nuclear Renaissance',
                'source_type': 'newsletter',
                'source_name': 'The Energy Letter',
                'source_date': (date.today() - timedelta(days=60)).isoformat(),
                'summary': 'SMR approvals accelerating. Regulatory pathway clearing for next-gen reactors.',
                'key_takeaway': 'Nuclear power infrastructure plays positioned for multi-year buildout.',
                'tickers_mentioned': '["SMR", "OKLO", "NEE", "CEG"]',
                'sentiment': 'bullish',
                'display_on_main': 0,
                'display_order': 0,
                'archived_date': (date.today() - timedelta(days=40)).isoformat(),
                'archived_reason': 'Theme still relevant but content aged out'
            }
        ]
        
        for i in insights:
            conn.execute("""
                INSERT OR IGNORE INTO latest_insights 
                (title, source_type, source_name, source_date, summary, key_takeaway,
                 tickers_mentioned, sentiment, display_on_main, display_order,
                 added_date, archived_date, archived_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (i['title'], i['source_type'], i['source_name'], i['source_date'],
                  i['summary'], i['key_takeaway'], i['tickers_mentioned'], i['sentiment'],
                  i['display_on_main'], i['display_order'], i['source_date'],
                  i.get('archived_date'), i.get('archived_reason')))
        
        print(f"  Added {len(insights)} insights")
    
    print("\n✅ Database seeded successfully!")
    print("\nStats:")
    stats = db.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

if __name__ == "__main__":
    seed_database()