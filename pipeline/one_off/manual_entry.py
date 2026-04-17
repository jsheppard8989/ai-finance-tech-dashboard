#!/usr/bin/env python3
"""
Manual podcast entry for high-quality episodes.
Used when AI APIs are unavailable but we have transcripts.
"""

import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db, PodcastEpisode, TickerMention

def add_brett_adcock_episode():
    """Add Brett Adcock Figure AI episode."""
    db = get_db()
    
    episode = PodcastEpisode(
        podcast_name="Moonshots with Peter Diamandis",
        episode_title="EP #229: Brett Adcock - Humanoid Run on Neural Net, Autonomous Manufacturing, $50T Market",
        episode_date=date(2026, 2, 11),
        transcript_path="transcripts/peter_diamandis_brett_adcock_ep229.txt",
        summary="Brett Adcock, founder of Figure AI, reveals how his humanoid robots are now fully autonomous using only neural nets—no C++ code. The company has eliminated 109,000 lines of C++ and moved entirely to end-to-end neural net control. Figure 3 robots are already walking factory halls, doing dishes, and will be deployed on BMW production lines this year. Adcock predicts humanoid robots will become the largest economy in the world, creating ubiquitous goods and services in an age of abundance.",
        key_takeaways=[
            "Figure AI eliminated 109,000 lines of C++ code - now 100% neural net controlled",
            "Helix 2 enables full-body autonomous manipulation without pre-programming",
            "Once one robot learns a task, every robot in the fleet knows it instantly",
            "Figure 3 robots being deployed on BMW production lines in 2026",
            "Robots will build robots - full automation of manufacturing coming",
            "Humanoid robots will be the largest economy in the world ($50T+ market)",
            "Neural nets create data moats - accumulated training data becomes barrier to entry",
            "Palm cameras and flexible toes enable human-like dexterity"
        ],
        key_tickers=["FIGURE", "BMW", "TSLA", "NVDA", "GOOGL", "AMZN"],
        investment_thesis="Humanoid robotics is transitioning from science fiction to industrial reality faster than expected. Figure AI's neural net approach creates exponential learning curves—each robot improves the entire fleet. The market is potentially larger than automotive. Key beneficiaries: chip makers (NVDA), cloud providers (AMZN, GOOGL), and early manufacturing partners. Timeline: commercial deployment 2026, consumer homes by 2028-2029.",
        relevance_score=95
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"✓ Added Brett Adcock episode (ID: {episode_id})")
    
    # Add ticker mentions
    tickers_data = [
        ("NVDA", "Neural net training requires massive GPU compute - primary infrastructure beneficiary", "bullish", 90),
        ("TSLA", "Tesla Optimus is competitor but validates market - Figure claims technical lead", "bullish", 70),
        ("AMZN", "AWS cloud infrastructure for robot training and fleet management", "bullish", 60),
        ("GOOGL", "Google Cloud and AI models for robotic control systems", "bullish", 60),
        ("BMW", "First major auto partner - production line deployment in 2026", "bullish", 75),
        ("APP", "AppLovin mentioned in context of ad tech/AI - tangential", "neutral", 30),
    ]
    
    for ticker, context, sentiment, conviction in tickers_data:
        try:
            mention = TickerMention(
                ticker=ticker,
                source_type="podcast",
                source_name="Moonshots with Peter Diamandis",
                episode_title=episode.episode_title,
                context=context[:300],
                conviction_score=conviction,
                sentiment=sentiment,
                timeframe="long_term",
                is_contrarian=False,
                is_disruption_focused=True
            )
            db.add_ticker_mention(mention)
        except Exception as e:
            print(f"  ⚠ Skipping {ticker}: {e}")
    
    print(f"✓ Added {len(tickers_data)} ticker mentions")
    return episode_id

def add_sam_altman_episode():
    """Add Sam Altman AI CEO episode."""
    db = get_db()
    
    episode = PodcastEpisode(
        podcast_name="Moonshots with Peter Diamandis",
        episode_title="EP #230: The AI CEO Arrives - Sam Altman's Succession Plan, Job Loss Continues",
        episode_date=date(2026, 2, 13),
        transcript_path="transcripts/peter_diamandis_sam_altman_ep230.txt",
        summary="Sam Altman reveals succession plans where AI could become CEO of OpenAI. The panel discusses 'Solve Everything' - a roadmap to abundance by 2035. Job losses are accelerating at fastest rate since Great Recession, with knowledge work being automated first. The social contract is 'pixelating away' as tasks evaporate. AI CEOs will run billion-dollar companies soon, with course corrections happening in minutes instead of years. Companies must adopt AI governance or become uncompetitive.",
        key_takeaways=[
            "Sam Altman has succession plan for AI to become CEO of OpenAI",
            "Job losses in January 2026 fastest since Great Recession",
            "'Solve Everything' paper outlines path to abundance by 2035",
            "AI CEOs will assimilate information and suggest course corrections in minutes",
            "Traditional 5-year business plans are obsolete - death to strategic planning",
            "Companies must become 'AI organizations' or face extinction",
            "AI governance shift: from tool to governance actor",
            "Next 18 months set rules for the next century",
        ],
        key_tickers=["MSFT", "GOOGL", "AMZN", "META", "CRM", "NOW", "PLTR"],
        investment_thesis="The AI CEO thesis represents a fundamental shift in corporate governance. Companies that embrace AI decision-making will have massive competitive advantages through time dilation (minutes vs years for strategy shifts). Enterprise software (CRM, NOW, PLTR) that enables AI governance will see accelerated adoption. Cloud providers (MSFT, AMZN, GOOGL) are infrastructure beneficiaries. Timeline: AI board members by 2026, AI CEOs by 2027-2028.",
        relevance_score=95
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"✓ Added Sam Altman episode (ID: {episode_id})")
    
    # Add ticker mentions
    tickers_data = [
        ("MSFT", "OpenAI partnership - AI CEO capabilities directly benefit Azure ecosystem", "bullish", 90),
        ("PLTR", "AI governance and decision-making platforms - core competency match", "bullish", 85),
        ("NOW", "ServiceNow automating enterprise workflows - AI management layer", "bullish", 80),
        ("CRM", "Salesforce AI agents managing customer relationships - governance applications", "bullish", 75),
        ("GOOGL", "Google Cloud AI and enterprise automation tools", "bullish", 70),
        ("AMZN", "AWS infrastructure for AI governance systems", "bullish", 65),
        ("META", "AI automation in social platforms and enterprise tools", "neutral", 50),
    ]
    
    for ticker, context, sentiment, conviction in tickers_data:
        try:
            mention = TickerMention(
                ticker=ticker,
                source_type="podcast",
                source_name="Moonshots with Peter Diamandis",
                episode_title=episode.episode_title,
                context=context[:300],
                conviction_score=conviction,
                sentiment=sentiment,
                timeframe="medium_term",
                is_contrarian=False,
                is_disruption_focused=True
            )
            db.add_ticker_mention(mention)
        except Exception as e:
            print(f"  ⚠ Skipping {ticker}: {e}")
    
    print(f"✓ Added {len(tickers_data)} ticker mentions")
    return episode_id

def main():
    """Add manual episodes."""
    print("="*60)
    print("Manual Podcast Entry - High Quality Episodes")
    print("="*60)
    
    db = get_db()
    
    # Check if already added
    existing = db.get_podcast_summaries_for_site()
    existing_titles = [e['episode_title'] for e in existing]
    
    added = []
    
    if "EP #229: Brett Adcock" not in str(existing_titles):
        id1 = add_brett_adcock_episode()
        added.append(f"Brett Adcock (ID: {id1})")
    else:
        print("⏭ Brett Adcock episode already exists")
    
    if "EP #230: The AI CEO Arrives" not in str(existing_titles):
        id2 = add_sam_altman_episode()
        added.append(f"Sam Altman (ID: {id2})")
    else:
        print("⏭ Sam Altman episode already exists")
    
    print("\n" + "="*60)
    if added:
        print(f"✓ Added {len(added)} episodes:")
        for a in added:
            print(f"  - {a}")
        print("\nNext: Run 'python3 run_pipeline.py' to export to website")
    else:
        print("All episodes already in database")

if __name__ == "__main__":
    main()
