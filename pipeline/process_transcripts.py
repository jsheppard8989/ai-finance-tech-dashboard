#!/usr/bin/env python3
"""
Process the 6 unprocessed podcast transcripts and add to database.
"""
import sys
import json
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db, PodcastEpisode, TickerMention

def add_jack_mallers_episode(db):
    """Add The Jack Mallers Show - Episode 104"""
    episode = PodcastEpisode(
        podcast_name="The Jack Mallers Show",
        episode_title="Episode 104: From Software to Hard Asset - Bitcoin and the New Liquidity Regime",
        episode_date=date(2025, 2, 9),  # Mentioned as Monday episode, referencing Feb 4th CNN article
        transcript_path="transcripts/https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-1-10%2F417811310-44100-2-5be9b2c9f29f2.txt",
        summary="Jack Mallers delivers a macro thesis on Bitcoin's decoupling from tech stocks. He argues Bitcoin has been trading like software/tech stocks due to shared investor bases, but the current liquidity rotation from software to hard assets (energy, critical minerals, infrastructure) is shaking out weak hands. Key catalysts include: 1) AI capex making software companies capital-intensive rather than cash-generative, 2) US policy pivoting to rebuild domestic industry, 3) China dumping treasuries for gold. Mallers sees this as healthy capitulation that will ultimately benefit Bitcoin as it matures into trading like a hard asset rather than tech.",
        key_takeaways=[
            "Bitcoin's correlation to tech stocks (~0.8) vs gold (~0.09) shows it's been misclassified by the market",
            "Software stocks are getting crushed as AI capex transforms them from cash machines to capital-intensive businesses",
            "US liquidity is rotating from financial engineering (buybacks, high multiples) to real economy (infrastructure, defense, critical minerals)",
            "Larry Fink's Davos comments acknowledged wealth creation went to narrow slice of society - elite overproduction creates political instability",
            "China urging banks to curb US treasury exposure while loading up on gold signals monetary regime change",
            "Fed's Warsh discussing yield curve control means money printing to cap yields - highly bullish for hard assets",
            "Bitcoin at $70k with only 50% supply in profit suggests we're in latter half of pain, not beginning of bear market",
            "Tech tourists getting flushed out is healthy - Bitcoin will eventually trade as hard money, not tech stock"
        ],
        key_tickers=["BTC", "MSTR", "COIN", "HOOD"],
        investment_thesis="Bitcoin is experiencing a healthy correction that shakes out tech-stock tourists while the underlying hard asset narrative strengthens. The liquidity regime is shifting from paper assets to real assets, and Bitcoin stands to benefit as the only truly scarce digital asset. With potential Fed yield curve control coming and China diversifying from USD, Bitcoin's monetary premium should expand.",
        relevance_score=95
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"  Added Jack Mallers episode (ID: {episode_id})")
    
    # Add ticker mentions
    tickers_data = [
        ("BTC", "Bitcoin is the primary hard asset beneficiary of liquidity rotation from software to real assets", "bullish", 95),
        ("MSTR", "MicroStrategy as Bitcoin proxy - will benefit as BTC matures to hard asset status", "bullish", 80),
        ("COIN", "Coinbase benefits from Bitcoin volatility and increased institutional adoption", "bullish", 70),
        ("HOOD", "Robinhood expanding Bitcoin offerings - mentioned in context of accessible BTC exposure", "bullish", 60),
        ("NVDA", "AI capex beneficiary but trading at stretched multiples - liquidity leaving tech", "bearish", -30),
        ("META", "Shifted from cash machine to capital intensive - multiple compression coming", "neutral", -20),
        ("GOOGL", "AI spending hurting cash flows - mentioned as having historic profits but stock down", "neutral", -20),
        ("AMZN", "Doubling capex - no longer asset light business model", "neutral", -20),
    ]
    
    for ticker, context, sentiment, conviction in tickers_data:
        mention = TickerMention(
            ticker=ticker,
            source_type="podcast",
            source_name="The Jack Mallers Show",
            episode_title=episode.episode_title,
            context=context[:300],
            conviction_score=conviction,
            sentiment=sentiment,
            timeframe="long_term",
            is_contrarian=ticker in ["BTC", "MSTR"],
            is_disruption_focused=True
        )
        db.add_ticker_mention(mention)
    
    print(f"  Added {len(tickers_data)} ticker mentions")
    return episode_id

def add_milton_berg_episode(db):
    """Add Monetary Matters with Milton Berg"""
    episode = PodcastEpisode(
        podcast_name="Monetary Matters",
        episode_title="Technical Analysis Deep Dive with Milton Berg - February 2026 Market Signals",
        episode_date=date(2026, 2, 6),  # References Friday Feb 6th as current day
        transcript_path="transcripts/EWWMN2965097612.txt",
        summary="Legendary technician Milton Berg analyzes current market conditions using proprietary indicators. Despite the market holding up well, Berg sees warning signals including a rare VXN pattern (35% gain in 3 days) and an unprecedented one-day island reversal in the Russell 2000. He went short on December 11th based on VXN sell signals and remains cautious. However, Thursday Feb 5th's action matched patterns seen at local bottoms (1997, 2015, 2024), creating tension between short-term bounce potential and medium-term bearish signals.",
        key_takeaways=[
            "April 2025 buy signals projected 6-8% more upside from January highs - not yet satisfied",
            "December 11th VXN sell signal has kept Berg short - historically leads to significant declines",
            "Thursday Feb 5th matched local bottom patterns: VXN +35% in 3 days, weakest 5-day Nasdaq performance in 180 days",
            "Russell 2000 one-day island reversal at peak is unprecedented - extremely bearish signal",
            "Market hasn't had 7% correction since April lows - historically unusual this deep into rally",
            "Berg flipped from 100%+ short to covering shorts and going long on Feb 9th based on panic indicators",
            "Small caps leading then crashing is classic late-cycle behavior (the 'dogs' lead at tops)",
            "False signals occur in bull markets - context of April thrust matters for signal interpretation"
        ],
        key_tickers=["SPY", "QQQ", "IWM", "VIX"],
        investment_thesis="Technical indicators suggest we're at an inflection point. While medium-term sell signals remain valid, short-term panic indicators suggest a bounce is likely. The unique Russell 2000 island reversal and VXN spike suggest this correction could be sharp but potentially short-lived if historical patterns hold.",
        relevance_score=90
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"  Added Milton Berg episode (ID: {episode_id})")
    
    # Add ticker mentions
    tickers_data = [
        ("SPY", "S&P 500 projection suggests 6% more upside before 10% correction - not yet achieved", "neutral", 40),
        ("QQQ", "Nasdaq showing panic indicators - potential local bottom forming", "neutral", 20),
        ("IWM", "Russell 2000 island reversal is unprecedented bearish signal", "bearish", -60),
        ("VIX", "VXN spike patterns suggest either local bottom or major top forming", "neutral", 0),
        ("GLD", "Gold shorted at highs - remains bearish on precious metals", "bearish", -50),
        ("SLV", "Silver shorted at highs along with gold", "bearish", -50),
    ]
    
    for ticker, context, sentiment, conviction in tickers_data:
        mention = TickerMention(
            ticker=ticker,
            source_type="podcast",
            source_name="Monetary Matters",
            episode_title=episode.episode_title,
            context=context[:300],
            conviction_score=conviction,
            sentiment=sentiment,
            timeframe="short_term",
            is_contrarian=False,
            is_disruption_focused=False
        )
        db.add_ticker_mention(mention)
    
    print(f"  Added {len(tickers_data)} ticker mentions")
    return episode_id

def add_carson_block_episode(db):
    """Add Muddy Waters with Carson Block"""
    episode = PodcastEpisode(
        podcast_name="Muddy Waters",
        episode_title="Carson Block on Short Selling, AI Pretenders, and Mining Opportunities",
        episode_date=date(2025, 11, 15),  # References Irisone conference in November 2025
        transcript_path="transcripts/default.txt",
        summary="Carson Block discusses short selling in AI hype cycles and opportunities in mining. He warns against shorting AI pretenders too early despite recognizing overvaluation - momentum can persist longer than expected. Key insights: 1) AI bubble will pop when supply of speculative companies overwhelms demand, 2) Hyperscalers (MSFT, GOOGL, META) have cash flows to survive AI capex unlike dotcoms, 3) Vietnam and India benefit from US-China Cold War, 4) Snowline Gold is most compelling greenfield gold deposit for acquisition by majors.",
        key_takeaways=[
            "Shorting AI pretenders now is dangerous despite overvaluation - momentum too strong",
            "AI bubble pops when supply of speculative companies overwhelms demand - expect 2026 IPO flood",
            "Hyperscalers can survive AI investments due to massive cash flows - unlike dotcoms",
            "Snowline Gold is most compelling greenfield gold deposit globally - likely acquisition target",
            "Vietnam benefits from FDI flows redirecting from China - now improving decision-making",
            "India offers similar Cold War benefits with large consumer growth story",
            "Chinese ADRs remain fraudulent - SEC can't investigate due to lack of cooperation",
            "Hong Kong market is 'cesspit' with frequent pump and dump schemes",
            "Mining offers venture capital returns with more data - under-allocated sector"
        ],
        key_tickers=["SNWGF", "CVNA", "APP", "OKLO", "GME", "TSLA"],
        investment_thesis="Focus on real assets like gold miners that benefit from both metal prices and M&A activity as majors deplete reserves. Avoid shorting overvalued AI names until momentum breaks. Vietnam and India offer geographic diversification for long-term capital.",
        relevance_score=85
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"  Added Carson Block episode (ID: {episode_id})")
    
    # Add ticker mentions
    tickers_data = [
        ("SNWGF", "Snowline Gold - most compelling greenfield gold deposit for major acquisition", "bullish", 85),
        ("CVNA", "Carvana - activist short target by Gotham City, rebounded due to strong momentum", "bearish", -40),
        ("APP", "Applovin - purported ad tech AI cheating, no moat if platforms enforce TOS", "bearish", -50),
        ("OKLO", "Oklo - small modular reactor design, many years from commercialization, pure speculation", "neutral", -20),
        ("MINE", "Mayfair Gold - Carson Block on board, acquired GT Gold previously", "bullish", 70),
    ]
    
    for ticker, context, sentiment, conviction in tickers_data:
        mention = TickerMention(
            ticker=ticker,
            source_type="podcast",
            source_name="Muddy Waters",
            episode_title=episode.episode_title,
            context=context[:300],
            conviction_score=conviction,
            sentiment=sentiment,
            timeframe="long_term",
            is_contrarian=True,
            is_disruption_focused=False
        )
        db.add_ticker_mention(mention)
    
    print(f"  Added {len(tickers_data)} ticker mentions")
    return episode_id

def add_x_wolverine_episode(db):
    """Add X Podcast on Wolverine (machine-mediated hearing)"""
    episode = PodcastEpisode(
        podcast_name="X (Google X)",
        episode_title="Wolverine: Machine-Mediated Hearing and the Future of Audio Computing",
        episode_date=date(2024, 1, 15),  # Estimated based on content referencing 2017-2018
        transcript_path="transcripts/EWWMN6429295583.txt",
        summary="Astro Teller interviews Jason Rugolo about the Wolverine project at X - creating machine-mediated hearing devices. The project evolved from 30+ ideas to focus on audio wearables that enhance hearing while remaining socially acceptable. Key innovations include: real-time voice separation (the 'Big Knob' demo), translation capabilities, hearing protection, and privacy-preserving input/output. The device uses outward-facing microphones to capture sound, processes it through ML models, and delivers enhanced audio to the ear.",
        key_takeaways=[
            "Wolverine project evolved from 30+ ideas including nuclear humans and digital matrix living",
            "Machine-mediated hearing allows selective enhancement of voices in noisy environments",
            "Translation app (Babel) enables real-time conversation across languages",
            "Privacy-by-design: voice pickup from ear canal prevents ambient eavesdropping",
            "30ms latency requirement to avoid perceptible delay vs natural hearing",
            "Wearables must be stylish and comfortable - learning from Google Glass challenges",
            "Hearing protection built-in prevents dangerous sound levels from reaching eardrums",
            "Device can make hearing aids socially acceptable by adding consumer tech value"
        ],
        key_tickers=["GOOGL", "MSFT"],  # Google/Alphabet and competitors
        investment_thesis="Audio wearables represent next computing platform after smartphones. Success depends on solving wearability challenges and achieving social acceptance. Translation and hearing enhancement are killer apps that could drive mass adoption.",
        relevance_score=60
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"  Added X Wolverine episode (ID: {episode_id})")
    return episode_id

def add_x_food_waste_episode(db):
    """Add X Podcast on Food Waste (Delta project)"""
    episode = PodcastEpisode(
        podcast_name="X (Google X)",
        episode_title="Delta: Solving Food Waste with Technology",
        episode_date=date(2024, 6, 1),  # Estimated based on content
        transcript_path="transcripts/IMP3972824673.txt",
        summary="Astro Teller interviews Emily Ma about the Delta project tackling food waste at X. Food waste costs US households $1,500/year and generates significant methane emissions. The team built an 'air traffic control' system for surplus food using open-source standards (Open Product Recovery) to match surplus with need. The system now operates across Feeding America network and is expanding globally. Key insight: 40% of US food waste occurs at households, but X focused on upstream (farms, processors, retailers) for maximum impact.",
        key_takeaways=[
            "US households waste $1,500/year in food on average",
            "Food waste is largest source of methane from landfills - 80x worse than CO2",
            "40% of US food waste happens at consumer/household level",
            "Air traffic control system matches surplus food with recipients using blockchain-like trust chain",
            "Dana Yost in Arizona pioneered manual food surplus brokering - now automated",
            "Open Product Recovery is open-source standard adopted by Kroger, Feeding America",
            "Chorus project tracks temperature/chain of custody for perishables",
            "COVID vaccine distribution applied learnings from food supply chain tracking"
        ],
        key_tickers=["KR", "WMT"],  # Kroger, Walmart mentioned as partners
        investment_thesis="Food waste reduction represents ESG investment opportunity with measurable climate impact. Technology solutions for supply chain optimization and inventory management will see increased demand as retailers face sustainability mandates.",
        relevance_score=50
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"  Added X Food Waste episode (ID: {episode_id})")
    return episode_id

def add_meta_boz_episode(db):
    """Add a16z Podcast with Boz (Meta CTO)"""
    episode = PodcastEpisode(
        podcast_name="a16z AI Revolution",
        episode_title="Boz on the Post-Phone Era: AI, AR, and the Future of Computing",
        episode_date=date(2025, 12, 1),  # Estimated based on content referencing 2025 events
        transcript_path="transcripts/IMP9962311305.txt",
        summary="Meta CTO Andrew 'Boz' Bosworth discusses the shift from mobile to AI-enabled wearable computing. Ray-Ban Meta glasses transformed from 'smart glasses' to 'AI glasses' when Llama 3 arrived 6 months before production. Key insights: 1) AI enables intent-based computing vs app-based, 2) Orion AR glasses show post-phone world is possible, 3) Open source AI (Llama) aligns with Meta's business model - commoditizing complements, 4) Ecosystem risk remains biggest challenge but AI could provide bridge to new interaction models.",
        key_takeaways=[
            "Ray-Ban Meta glasses became AI glasses when Llama 3 hit - 6 months before production",
            "10-year vision: AR glasses widely adopted; 5-year: good but tethered to phone",
            "AI enables intent-based computing - 'play music' vs 'open Spotify'",
            "App model may invert - AI orchestrates services rather than user picking apps",
            "Orion glasses first glimpse of life after smartphones",
            "Open source AI aligns with Meta's business - commoditizing complements",
            "Privacy and social acceptability remain key hurdles for always-on devices",
            "Nuclear power derailed for 70 years - cautionary tale for overstepping with new tech"
        ],
        key_tickers=["META", "AAPL", "SNAP", "GOOGL"],
        investment_thesis="Meta is positioning for post-phone computing era through Reality Labs investments. AI tailwind accelerates timeline for AR/VR adoption. Open source strategy commoditizes AI models while Meta captures value through applications.",
        relevance_score=75
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"  Added a16z Boz episode (ID: {episode_id})")
    
    # Add ticker mentions
    tickers_data = [
        ("META", "Best positioned for AI + AR computing transition with Reality Labs investments", "bullish", 75),
        ("AAPL", "iPhone dominance creates anchor - hard to displace but also hard to abandon", "neutral", 20),
        ("SNAP", "AR/VR competitor but struggling to maintain momentum vs Meta", "neutral", 0),
        ("GOOGL", "Transformer paper originator but closed source strategy vs Meta's open approach", "neutral", 10),
    ]
    
    for ticker, context, sentiment, conviction in tickers_data:
        mention = TickerMention(
            ticker=ticker,
            source_type="podcast",
            source_name="a16z AI Revolution",
            episode_title=episode.episode_title,
            context=context[:300],
            conviction_score=conviction,
            sentiment=sentiment,
            timeframe="long_term",
            is_contrarian=False,
            is_disruption_focused=True
        )
        db.add_ticker_mention(mention)
    
    print(f"  Added {len(tickers_data)} ticker mentions")
    return episode_id

def add_insights_to_db(db):
    """Add top insights from the podcasts to latest_insights table"""
    print("\nAdding Latest Insights...")
    
    insights = [
        {
            "title": "Bitcoin's Liquidity Rotation: From Software to Hard Asset",
            "source_name": "The Jack Mallers Show",
            "source_date": date(2025, 2, 9),
            "summary": "Bitcoin has traded like a tech stock (0.8 correlation) but is undergoing a healthy decoupling as liquidity rotates from software to hard assets. AI capex is transforming software companies from cash machines to capital-intensive businesses. Fed yield curve control and China's treasury dump signal monetary regime change.",
            "key_takeaway": "Bitcoin's 20% drop is healthy capitulation shaking out tech tourists before hard asset repricing",
            "tickers": ["BTC", "MSTR", "COIN"],
            "sentiment": "bullish",
            "episode_id": None  # Will update after adding
        },
        {
            "title": "Milton Berg's Market Signals: Local Bottom or Major Top?",
            "source_name": "Monetary Matters",
            "source_date": date(2026, 2, 6),
            "summary": "Legendary technician sees conflicting signals: December VXN sell signal suggests major top, but Thursday's panic indicators (35% VXN spike, Russell island reversal) match historical local bottoms. April 2025 buy signals have not yet achieved projected 6-8% upside.",
            "key_takeaway": "Unprecedented Russell 2000 island reversal suggests sharp correction likely, but panic may be overdone short-term",
            "tickers": ["SPY", "QQQ", "IWM"],
            "sentiment": "bearish",
            "episode_id": None
        },
        {
            "title": "Carson Block: Don't Short AI Yet, Buy Gold Miners",
            "source_name": "Muddy Waters",
            "source_date": date(2025, 11, 15),
            "summary": "Short seller warns against fighting AI momentum despite recognizing bubble conditions. Real opportunity in mining: Snowline Gold is most compelling greenfield acquisition target as majors deplete reserves. Vietnam and India benefit from Cold War 2.0 FDI redirection.",
            "key_takeaway": "Wait for AI supply to overwhelm demand before shorting; gold miners offer M&A upside with less risk",
            "tickers": ["SNWGF", "MINE"],
            "sentiment": "bullish",
            "episode_id": None
        }
    ]
    
    insight_ids = []
    for insight_data in insights:
        with db._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO latest_insights 
                (title, source_type, source_name, source_date, summary, key_takeaway, 
                 tickers_mentioned, sentiment, display_on_main, display_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                insight_data["title"],
                "podcast",
                insight_data["source_name"],
                insight_data["source_date"],
                insight_data["summary"],
                insight_data["key_takeaway"],
                json.dumps(insight_data["tickers"]),
                insight_data["sentiment"],
                1,
                len(insight_ids) + 1
            ))
            insight_ids.append(cursor.lastrowid)
            print(f"  Added insight: {insight_data['title'][:50]}...")
    
    return insight_ids

def add_deep_dive_content(db, insight_ids):
    """Add deep dive content for the insights"""
    print("\nAdding Deep Dive Content...")
    
    deepdives = [
        {
            "insight_id": insight_ids[0],  # Bitcoin insight
            "overview": "Jack Mallers presents a macro thesis that Bitcoin is undergoing a necessary decoupling from tech stocks as liquidity rotates from software to hard assets. The correlation between Bitcoin and software stocks (~0.8) has been unhealthy for Bitcoin's development as hard money. The current correction, while painful, is shaking out 'tech tourists' and establishing a stronger holder base.",
            "key_takeaways_detailed": [
                "Bitcoin's 0.8 correlation to tech stocks vs 0.09 to gold shows misclassification by broader market",
                "Software companies transformed from cash machines to capital-intensive businesses due to AI capex (Amazon doubling to $200B, Google $100B bond sale)",
                "US policy pivoting from financial engineering to real economy (infrastructure, defense, critical minerals)",
                "Larry Fink acknowledged wealth creation went to narrow slice of society, creating political instability",
                "China urging banks to curb US treasury exposure while loading up on gold signals monetary regime change",
                "Fed's Warsh discussing yield curve control = money printing to cap yields, highly bullish for hard assets",
                "Only 50% of Bitcoin supply in profit at $70k - historically signals late-stage correction not bear market beginning",
                "Tech tourists getting flushed out is healthy for long-term Bitcoin adoption"
            ],
            "investment_thesis": "Bitcoin is the primary beneficiary of a liquidity rotation from paper assets to real assets. As the only truly scarce digital asset with a fixed supply, Bitcoin stands to gain as central banks implement yield curve control and sovereigns diversify from USD. The current correlation breakdown with tech stocks is a maturation event that will ultimately strengthen Bitcoin's monetary premium.",
            "positioning_guidance": "Accumulate Bitcoin on dips with long-term time horizon. Use DCA strategies during high volatility periods. Avoid excessive leverage. Consider Bitcoin proxies (MSTR, COIN) with awareness of additional risk layers. Focus on self-custody solutions for core holdings.",
            "risk_factors": [
                "Regulatory crackdown on Bitcoin self-custody or transactions",
                "Fed maintains hawkish stance longer than expected, delaying yield curve control",
                "Continued tech stock correlation drags Bitcoin lower in liquidation cascades",
                "China disruption of Bitcoin mining or protocol development",
                "Macro deflationary shock from AI job losses overwhelms inflation hedges"
            ],
            "catalysts": [
                "Fed announces yield curve control or similar treasury buying program (Q2-Q3 2025)",
                "Major sovereign announces Bitcoin reserve accumulation",
                "Spot Bitcoin ETFs approved in additional jurisdictions",
                "Halving supply shock effects materialize in reduced sell pressure"
            ]
        },
        {
            "insight_id": insight_ids[1],  # Milton Berg insight
            "overview": "Legendary technician Milton Berg analyzes conflicting market signals. December 11th VXN sell signal suggested major top forming, but February 5th panic indicators matched historical local bottoms. The unprecedented Russell 2000 one-day island reversal is extremely bearish, yet the VXN spike pattern has preceded 20-40% rallies. Positioning is challenging given the tension between timeframes.",
            "key_takeaways_detailed": [
                "April 2025 buy signals projected 74-80 S&P level - currently at 69.78, suggesting unfulfilled upside",
                "December 11th VXN sell signal triggered short position - historically precedes 13-32% declines",
                "Thursday Feb 5th panic matched 1997, 2015, 2024 local bottom patterns",
                "Russell 2000 one-day island reversal at peak is unprecedented - classic late-cycle behavior",
                "Market hasn't had 7% correction since April lows - historically unusual",
                "Small caps leading then crashing ('the dogs') is typical of market tops",
                "Berg flipped to covering shorts and going long on Feb 9th based on panic signals"
            ],
            "investment_thesis": "Technical indicators suggest we're at an inflection point with conflicting timeframes. Short-term panic indicators suggest a bounce is likely, while medium-term sell signals remain valid. The Russell island reversal and VXN spike suggest sharp correction, but historical patterns suggest potential for continued rally if April thrust momentum persists.",
            "positioning_guidance": "Reduce equity beta and raise cash given conflicting signals. If long, consider protective puts or collars. Short-term traders may play bounce from oversold levels but keep tight stops. Avoid initiating new long-term equity positions until clarity emerges on which signal set dominates.",
            "risk_factors": [
                "Bearish December signal proves correct leading to 20%+ correction",
                "Russell island reversal marks major top for small caps",
                "Liquidity conditions tighten faster than expected",
                "Earnings disappointment from AI capex not yet reflected in prices"
            ],
            "catalysts": [
                "Fed policy pivot clarity at next meeting",
                "Earnings season results from tech hyperscalers",
                "Economic data confirming or denying recession signals",
                "Continued rotation from growth to value stocks"
            ]
        },
        {
            "insight_id": insight_ids[2],  # Carson Block insight
            "overview": "Carson Block provides perspective on navigating bubble conditions. While AI is clearly in bubble territory, shorting too early can be fatal due to momentum persistence. Better opportunities exist in overlooked sectors like mining where M&A activity is accelerating. Snowline Gold represents the most compelling greenfield gold deposit globally. Vietnam and India offer geographic diversification benefiting from Cold War 2.0 dynamics.",
            "key_takeaways_detailed": [
                "AI bubble will pop when supply of speculative companies overwhelms demand - expect 2026 IPO flood",
                "Hyperscalers (MSFT, GOOGL, META) have cash flows to survive AI investments unlike dotcoms",
                "Snowline Gold is most compelling greenfield gold deposit for acquisition by majors",
                "Majors depleted reserves through brownfield focus - must acquire greenfield assets",
                "Vietnam benefits from FDI flows redirecting from China - decision paralysis improving",
                "India offers consumer growth story plus Cold War diversification benefits",
                "Chinese ADRs remain structurally uninvestable due to fraud and lack of enforcement",
                "Mining sector offers venture returns with better data due to under-allocation of human capital"
            ],
            "investment_thesis": "Focus on real assets benefiting from both fundamentals and capital flows. Gold miners are entering M&A cycle as majors deplete reserves. Avoid shorting AI momentum until clear breakdown occurs. Geographic diversification into Vietnam/India reduces China concentration risk.",
            "positioning_guidance": "Long: Gold exploration companies with tier-1 deposits (Snowline, Mayfair). Vietnam/India dedicated funds. Avoid: Chinese ADRs, speculative AI names without revenue. Short: Only when momentum breaks - watch for supply overwhelming demand in AI space.",
            "risk_factors": [
                "Gold price correction reduces M&A activity",
                "Vietnam/India face their own macro challenges",
                "AI bubble deflation drags all growth stocks lower",
                "Regulatory changes affecting mining permitting"
            ],
            "catalysts": [
                "Major gold miner announces acquisition of Snowline or similar",
                "SpaceX/XAI IPO triggers AI supply flood",
                "Vietnam FDI statistics confirm acceleration",
                "Fed rate cuts trigger commodity reflation"
            ]
        }
    ]
    
    for dd in deepdives:
        with db._get_connection() as conn:
            conn.execute("""
                INSERT INTO deep_dive_content 
                (insight_id, overview, key_takeaways_detailed, investment_thesis,
                 positioning_guidance, risk_factors, catalysts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                dd["insight_id"],
                dd["overview"],
                json.dumps(dd["key_takeaways_detailed"]),
                dd["investment_thesis"],
                dd["positioning_guidance"],
                json.dumps(dd["risk_factors"]),
                json.dumps(dd["catalysts"])
            ))
            print(f"  Added deep dive for insight ID {dd['insight_id']}")

def main():
    print("="*60)
    print("Processing 6 Podcast Transcripts")
    print("="*60)
    
    db = get_db()
    
    # Add all 6 podcast episodes
    print("\nAdding Podcast Episodes...")
    
    jack_id = add_jack_mallers_episode(db)
    milton_id = add_milton_berg_episode(db)
    carson_id = add_carson_block_episode(db)
    wolverine_id = add_x_wolverine_episode(db)
    food_waste_id = add_x_food_waste_episode(db)
    boz_id = add_meta_boz_episode(db)
    
    # Mark episodes as added to site
    for eid in [jack_id, milton_id, carson_id, wolverine_id, food_waste_id, boz_id]:
        if eid:
            db.mark_episode_added_to_site(eid)
    
    # Add insights for the investment-focused episodes
    insight_ids = add_insights_to_db(db)
    
    # Add deep dive content
    add_deep_dive_content(db, insight_ids)
    
    print("\n" + "="*60)
    print("Processing Complete!")
    print("="*60)
    print(f"Added 6 podcast episodes")
    print(f"Added {len(insight_ids)} insights to latest_insights")
    print(f"Added {len(insight_ids)} deep dive entries")
    
    # Show stats
    stats = db.get_stats()
    print("\nDatabase Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

if __name__ == "__main__":
    main()
