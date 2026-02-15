#!/usr/bin/env python3
"""
Master pipeline orchestrator.
Runs all ingestion, analysis, and exports data for website.
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime, date
import json

# Add pipeline directory to path
sys.path.insert(0, str(Path(__file__).parent))

from db_manager import get_db, TickerMention, PodcastEpisode, DailyScore
from pipeline_tracker import PodcastPipelineTracker

def run_step(name: str, script: str, args: list = None) -> bool:
    """Run a pipeline step and report status."""
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"{'='*60}")
    
    cmd = [sys.executable, script]
    if args:
        cmd.extend(args)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        if result.returncode == 0:
            print(f"✓ {name} completed")
            return True
        else:
            print(f"✗ {name} failed with code {result.returncode}")
            return False
    except Exception as e:
        print(f"✗ {name} error: {e}")
        return False

def import_podcasts_to_db():
    """Import processed podcast transcripts into database."""
    print("\n" + "="*60)
    print("Importing Podcasts to Database")
    print("="*60)
    
    db = get_db()
    transcript_dir = Path.home() / ".openclaw/workspace/pipeline/transcripts"
    
    imported = 0
    for transcript_file in transcript_dir.glob("*.txt"):
        # Skip already processed or check if in DB
        # This is a simplified version - you'd want more sophisticated matching
        podcast_name = transcript_file.stem
        
        # Read first few lines to get metadata
        try:
            with open(transcript_file, 'r') as f:
                content = f.read()
                preview = content[:500]
        except:
            continue
        
        # Add to processing queue or directly to mentions
        # For now, just log it
        print(f"  Found transcript: {podcast_name}")
        imported += 1
    
    print(f"✓ Found {imported} transcripts")
    return imported

def import_newsletters_to_db():
    """Import processed newsletters into database."""
    print("\n" + "="*60)
    print("Importing Newsletters to Database")
    print("="*60)
    
    db = get_db()
    inbox_dir = Path.home() / ".openclaw/workspace/pipeline/inbox"
    
    imported = 0
    for json_file in inbox_dir.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            # Process tickers from newsletter
            tickers = data.get('extracted_tickers', [])
            sender = data.get('sender', 'Unknown')
            subject = data.get('subject', '')
            
            # Check for disruption keywords
            content = str(subject) + ' ' + str(data.get('content_preview', ''))
            content_lower = content.lower()
            
            disruption_keywords = [
                'disruption', 'disruptive', 'paradigm shift', 'game changer',
                'breakthrough', 'transformation', 'revolutionary'
            ]
            is_disruption = any(kw in content_lower for kw in disruption_keywords)
            
            for ticker in tickers:
                mention = TickerMention(
                    ticker=ticker,
                    source_type='newsletter',
                    source_name=sender,
                    episode_title=subject[:100],
                    context=data.get('content_preview', '')[:300],
                    is_disruption_focused=is_disruption
                )
                db.add_ticker_mention(mention)
            
            imported += 1
            
        except Exception as e:
            print(f"  Error importing {json_file}: {e}")
    
    print(f"✓ Imported {imported} newsletters")
    return imported

def aggregate_daily_scores():
    """Aggregate today's mentions into daily scores."""
    print("\n" + "="*60)
    print("Aggregating Daily Scores")
    print("="*60)
    
    db = get_db()
    today = date.today()
    
    # Get top tickers from database
    top_tickers = db.get_top_tickers(date_filter=today, limit=30)
    
    scores = []
    for i, row in enumerate(top_tickers, 1):
        score = DailyScore(
            ticker=row['ticker'],
            date=today,
            total_score=row['total_score'],
            podcast_mentions=row['podcast_count'],
            newsletter_mentions=row['newsletter_count'],
            disruption_signals=0,  # Would need to calculate from mentions
            unique_sources=row['unique_sources'],
            conviction_level='medium',  # Would calculate from avg
            contrarian_signal='neutral',
            rank=i
        )
        scores.append(score)
    
    db.save_daily_scores(scores)
    print(f"✓ Saved {len(scores)} daily scores")
    return len(scores)

def auto_archive_content():
    """Automatically archive old content based on age rules."""
    print("\n" + "="*60)
    print("Auto-Archiving Content")
    print("="*60)
    
    db = get_db()
    archived_count = {'insights': 0, 'overton': 0}
    
    with db._get_connection() as conn:
        # Archive insights older than 14 days (keep only most recent 5)
        cursor = conn.execute("""
            SELECT id, title, source_date, display_on_main
            FROM latest_insights
            WHERE display_on_main = 1
              AND source_date < date('now', '-14 days')
            ORDER BY source_date DESC
            LIMIT -1 OFFSET 5
        """)
        
        old_insights = cursor.fetchall()
        for insight in old_insights:
            conn.execute("""
                UPDATE latest_insights 
                SET display_on_main = 0, 
                    archived_date = date('now'),
                    archived_reason = 'Auto-archived: Aged out (>14 days)'
                WHERE id = ?
            """, (insight['id'],))
            print(f"  Archived insight: {insight['title'][:40]}... ({insight['source_date']})")
            archived_count['insights'] += 1
        
        # Archive Overton terms older than 90 days or graduated
        cursor = conn.execute("""
            SELECT id, term, first_detected_date, status
            FROM overton_terms
            WHERE display_on_main = 1
              AND (first_detected_date < date('now', '-90 days')
                   OR status = 'graduated')
        """)
        
        old_terms = cursor.fetchall()
        for term in old_terms:
            reason = 'Graduated to mainstream' if term['status'] == 'graduated' else 'Auto-archived: Aged out (>90 days)'
            conn.execute("""
                UPDATE overton_terms 
                SET display_on_main = 0,
                    status = CASE WHEN status = 'active' THEN 'archived' ELSE status END,
                    archived_date = date('now'),
                    archived_reason = ?
                WHERE id = ?
            """, (reason, term['id']))
            print(f"  Archived Overton term: {term['term']} ({reason})")
            archived_count['overton'] += 1
        
        # Keep only top 10 definitions by vote count (archive others)
        cursor = conn.execute("""
            SELECT id, term, vote_count
            FROM definitions
            WHERE display_on_main = 1
            ORDER BY vote_count DESC, added_date DESC
            LIMIT -1 OFFSET 10
        """)
        
        low_vote_defs = cursor.fetchall()
        for d in low_vote_defs:
            conn.execute("""
                UPDATE definitions
                SET display_on_main = 0,
                    archived_date = date('now'),
                    archived_reason = 'Auto-archived: Lower vote count (outside top 10)'
                WHERE id = ?
            """, (d['id'],))
            print(f"  Archived definition: {d['term']} (votes: {d['vote_count']})")
            archived_count['definitions'] = archived_count.get('definitions', 0) + 1
    
    total = sum(archived_count.values())
    print(f"✓ Auto-archived {total} items: {archived_count}")
    return archived_count

def export_website_data():
    """Export data for website."""
    print("\n" + "="*60)
    print("Exporting Website Data")
    print("="*60)
    
    db = get_db()
    site_dir = Path.home() / ".openclaw/workspace/site/data"
    
    stats = db.export_for_website(site_dir)
    print(f"✓ Exported: {stats}")
    return stats

def generate_website_js():
    """Generate JavaScript file with data for website."""
    print("\n" + "="*60)
    print("Generating Website JavaScript")
    print("="*60)
    
    db = get_db()
    site_dir = Path.home() / ".openclaw/workspace/site/data"
    
    # Get all data including archive
    archive = db.export_archive_data()
    main_content = db.get_main_page_content()
    deepdives = db.get_all_deep_dive_content()
    suggested_terms = db.get_suggested_terms_for_website(limit=3)
    
    # Load ticker scores
    try:
        with open(site_dir / 'ticker_scores.json', 'r') as f:
            ticker_scores = json.load(f)
    except FileNotFoundError:
        ticker_scores = []
    
    # Generate data.js that the HTML can load
    js_content = f"""// Auto-generated data file - {datetime.now().isoformat()}
// DO NOT EDIT MANUALLY

const dashboardData = {{
  generatedAt: "{datetime.now().isoformat()}",
  tickerScores: {json.dumps(ticker_scores, indent=2)},
  archive: {json.dumps(archive, indent=2)},
  mainContent: {json.dumps(main_content, indent=2)},
  deepDives: {json.dumps(deepdives, indent=2)},
  suggestedTerms: {json.dumps(suggested_terms, indent=2)}
}};

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {{
  module.exports = dashboardData;
}}
"""
    
    with open(site_dir / 'data.js', 'w') as f:
        f.write(js_content)
    
    total_archive = sum(len(v) for v in archive.values())
    print(f"✓ Generated data.js with {len(ticker_scores)} tickers, {total_archive} archive items, {len(deepdives)} deep dives, {len(suggested_terms)} suggested terms")
    return True

def push_to_github():
    """Push updates to GitHub for Pages deployment."""
    print("\n" + "="*60)
    print("Pushing to GitHub")
    print("="*60)
    
    # Check if git is configured
    workspace_dir = Path.home() / ".openclaw/workspace"
    git_dir = workspace_dir / ".git"
    
    if not git_dir.exists():
        print("⚠ Git not initialized. Skipping push.")
        print("  Run setup_github.sh first to configure GitHub deployment.")
        return False
    
    try:
        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=workspace_dir
        )
        
        if not result.stdout.strip():
            print("✓ No changes to push")
            return True
        
        # Add changes
        subprocess.run(
            ["git", "add", "-A"],
            check=True,
            cwd=workspace_dir,
            capture_output=True
        )
        
        # Commit
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "commit", "-m", f"Auto-update: {timestamp}\n\n- Updated ticker scores\n- Latest podcast insights\n- Archive content"],
            check=True,
            cwd=workspace_dir,
            capture_output=True
        )
        
        # Push
        subprocess.run(
            ["git", "push", "origin", "main"],
            check=True,
            cwd=workspace_dir,
            capture_output=True
        )
        
        print(f"✓ Pushed to GitHub at {timestamp}")
        print("  GitHub Pages will auto-deploy in 2-3 minutes")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"⚠ Git push failed: {e}")
        print("  You may need to run manually:")
        print("  cd ~/.openclaw/workspace")
        print("  git push origin main")
        return False
    except Exception as e:
        print(f"⚠ Error pushing to GitHub: {e}")
        return False

def main():
    """Run full pipeline."""
    print("="*60)
    print("AI FINANCE TECH - MASTER PIPELINE")
    print(f"Started: {datetime.now()}")
    print("="*60)
    
    # Show current pipeline status
    print("\n📊 Current Pipeline Status:")
    tracker = PodcastPipelineTracker()
    tracker.scan_pipeline()
    
    results = {}
    
    # Step 1: Curate podcasts (find new episodes)
    results['curate'] = run_step("Podcast Curation", "curate.py")
    
    # Step 2: Fetch and transcribe new podcasts
    results['fetch'] = run_step("Fetch & Transcribe", "fetch_latest.py")
    
    # Step 3: Ingest newsletters
    results['ingest'] = run_step("Newsletter Ingestion", "ingest.py")
    
    # Step 4: Import to database
    results['import_podcasts'] = import_podcasts_to_db()
    results['import_newsletters'] = import_newsletters_to_db()
    
    # Step 5: Run analysis
    results['analysis'] = run_step("Ticker Analysis", "analyze_enhanced.py")
    
    # Step 6: Aggregate scores
    results['aggregate'] = aggregate_daily_scores()
    
    # Step 6b: Auto-archive old content
    results['auto_archive'] = auto_archive_content()
    
    # Step 6c: Fetch current prices
    results['prices'] = run_step("Price Update", "fetch_prices.py")
    
    # Step 6d: Manage suggested terms
    results['suggested_terms'] = run_step("Suggested Terms Management", "manage_suggested_terms.py")
    
    # Step 7: Generate charts
    results['charts'] = run_step("Chart Generation", "generate_charts.py")
    
    # Step 8: Export for website
    results['export'] = export_website_data()
    results['generate_js'] = generate_website_js()

    # Step 9: Push to GitHub (if configured)
    results['github_push'] = push_to_github()

    # Summary
    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print("="*60)
    print(f"Finished: {datetime.now()}")
    print("\nResults:")
    for key, value in results.items():
        status = "✓" if value else "✗"
        print(f"  {status} {key}: {value}")
    
    # Database stats
    db = get_db()
    stats = db.get_stats()
    print("\nDatabase Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

if __name__ == "__main__":
    main()