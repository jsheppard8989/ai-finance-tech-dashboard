#!/usr/bin/env python3
"""
Fully automated pipeline - no approval step needed.
Runs end-to-end: fetch → transcribe → analyze → export → push to GitHub.
Sends a summary notification after completion.

Usage:
  python3 auto_pipeline.py              # Full pipeline
  python3 auto_pipeline.py --analyze-only  # Just analyze unprocessed transcripts + export
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from db_manager import get_db, DailyScore
from datetime import date

WORKSPACE = Path.home() / ".openclaw/workspace"
PIPELINE_DIR = WORKSPACE / "pipeline"
SITE_DIR = WORKSPACE / "site"

def send_notification(title: str, message: str, priority: int = 0):
    """Send Pushover + iMessage notification."""
    pushover = WORKSPACE / "pushover.sh"
    imessage = WORKSPACE / "send_imessage.sh"

    if pushover.exists():
        try:
            subprocess.run([str(pushover), title, message, str(priority)],
                           capture_output=True, timeout=15)
        except Exception as e:
            print(f"  Pushover failed: {e}")

    if imessage.exists():
        try:
            full_msg = f"{title}\n\n{message}"
            subprocess.run([str(imessage), "+16306437437", full_msg],
                           capture_output=True, timeout=15)
        except Exception as e:
            print(f"  iMessage failed: {e}")


def run_script(name: str, script: str, timeout: int = 300) -> bool:
    """Run a pipeline script and return success."""
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True,
            cwd=PIPELINE_DIR, timeout=timeout
        )
        print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr[-1000:])
        ok = result.returncode == 0
        print(f"{'✓' if ok else '✗'} {name} {'completed' if ok else 'failed'}")
        return ok
    except subprocess.TimeoutExpired:
        print(f"✗ {name} timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"✗ {name} error: {e}")
        return False


def analyze_transcripts() -> int:
    """Run AI analysis on unprocessed transcripts."""
    print("\n" + "="*60)
    print("STEP: Transcript AI Analysis")
    print("="*60)
    try:
        from analyze_transcript import process_all_transcripts
        result = process_all_transcripts()
        processed = result.get('processed', 0)
        print(f"✓ Analyzed {processed} new transcripts")
        return processed
    except Exception as e:
        print(f"✗ Transcript analysis failed: {e}")
        import traceback; traceback.print_exc()
        return 0


def import_newsletters() -> int:
    """Import newsletters from inbox/ into database."""
    print("\n" + "="*60)
    print("STEP: Newsletter Import")
    print("="*60)
    db = get_db()
    inbox_dir = PIPELINE_DIR / "inbox"
    imported = 0

    disruption_keywords = [
        'disruption', 'disruptive', 'paradigm shift', 'game changer',
        'breakthrough', 'transformation', 'revolutionary', 'inflection point'
    ]

    from db_manager import TickerMention

    for json_file in inbox_dir.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

            sender = data.get('sender', 'Unknown')
            subject = data.get('subject', '')
            content = str(subject) + ' ' + str(data.get('content_preview', ''))
            is_disruption = any(kw in content.lower() for kw in disruption_keywords)

            # Insert into newsletters table directly
            with db._get_connection() as conn:
                # Check for duplicate
                existing = conn.execute(
                    "SELECT id FROM newsletters WHERE subject = ? AND sender = ?",
                    (subject[:200], sender)
                ).fetchone()
                if existing:
                    print(f"  ⏭ Already in DB: {subject[:60]}")
                    continue

                conn.execute("""
                    INSERT INTO newsletters (sender, subject, received_date,
                        content_preview, extracted_tickers, is_processed,
                        disruption_keywords_found, added_to_site)
                    VALUES (?, ?, ?, ?, ?, 1, ?, 0)
                """, (
                    sender,
                    subject[:200],
                    data.get('date', str(datetime.now().date())),
                    data.get('content_preview', '')[:1000],
                    json.dumps(data.get('extracted_tickers', [])),
                    is_disruption
                ))

            # Add ticker mentions
            for ticker in data.get('extracted_tickers', []):
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
            print(f"  ✓ Imported: {sender}: {subject[:60]}")

        except Exception as e:
            print(f"  ✗ Error importing {json_file.name}: {e}")

    print(f"✓ Total newsletters imported: {imported}")
    return imported


def aggregate_scores():
    """Aggregate daily ticker scores with proper conviction and contrarian calculations."""
    print("\n" + "="*60)
    print("STEP: Aggregate Daily Scores")
    print("="*60)
    db = get_db()
    today = date.today()
    top_tickers = db.get_top_tickers(date_filter=today, limit=30)
    
    # Get all sentiment and timeframe data for today in one query
    with db._get_connection() as conn:
        cursor = conn.execute("""
            SELECT ticker, sentiment, COUNT(*) as count 
            FROM ticker_mentions 
            WHERE date(mention_date) = ?
            GROUP BY ticker, sentiment
        """, (today,))
        sentiment_rows = cursor.fetchall()
        
        cursor = conn.execute("""
            SELECT ticker, timeframe, COUNT(*) as count 
            FROM ticker_mentions 
            WHERE date(mention_date) = ?
            GROUP BY ticker, timeframe
        """, (today,))
        timeframe_rows = cursor.fetchall()
    
    # Organize sentiment data by ticker
    sentiment_by_ticker = {}
    for r in sentiment_rows:
        if r['ticker'] not in sentiment_by_ticker:
            sentiment_by_ticker[r['ticker']] = {}
        sentiment_by_ticker[r['ticker']][r['sentiment']] = r['count']
    
    # Organize timeframe data by ticker
    timeframe_by_ticker = {}
    for r in timeframe_rows:
        if r['ticker'] not in timeframe_by_ticker:
            timeframe_by_ticker[r['ticker']] = {}
        timeframe_by_ticker[r['ticker']][r['timeframe']] = r['count']
    
    scores = []
    for i, row in enumerate(top_tickers, 1):
        # Calculate conviction level from average conviction score
        avg_conviction = row.get('avg_conviction', 50) or 50
        if avg_conviction >= 70:
            conviction_level = 'high'
        elif avg_conviction >= 40:
            conviction_level = 'medium'
        else:
            conviction_level = 'low'
        
        # Get sentiment distribution for contrarian signal calculation
        sentiment_counts = sentiment_by_ticker.get(row['ticker'], {})
        bullish = sentiment_counts.get('bullish', 0)
        bearish = sentiment_counts.get('bearish', 0)
        total = sum(sentiment_counts.values())
        
        # Determine contrarian signal
        if total >= 3 and bearish > bullish:
            contrarian_signal = 'contrarian'
        elif total >= 3 and bullish > bearish * 2:
            contrarian_signal = 'crowded'
        else:
            contrarian_signal = 'neutral'
        
        # Calculate timeframe - use most common timeframe
        timeframe_counts = timeframe_by_ticker.get(row['ticker'], {})
        if timeframe_counts:
            # Sort by count descending and pick most common
            most_common = max(timeframe_counts.items(), key=lambda x: x[1])
            timeframe = most_common[0] if most_common[0] else 'unspecified'
        else:
            timeframe = 'unspecified'
        
        score = DailyScore(
            ticker=row['ticker'],
            date=today,
            total_score=row['total_score'],
            podcast_mentions=row['podcast_count'],
            newsletter_mentions=row['newsletter_count'],
            disruption_signals=0,
            unique_sources=row['unique_sources'],
            conviction_level=conviction_level,
            contrarian_signal=contrarian_signal,
            timeframe=timeframe,
            rank=i
        )
        scores.append(score)
    db.save_daily_scores(scores)
    print(f"✓ Saved {len(scores)} daily scores")
    return len(scores)


def export_website():
    """Export data.js and supporting files for the website."""
    print("\n" + "="*60)
    print("STEP: Export Website Data")
    print("="*60)
    db = get_db()
    site_data_dir = SITE_DIR / "data"

    # Export JSON files
    stats = db.export_for_website(site_data_dir)
    print(f"✓ Exported JSON: {stats}")

    # Generate data.js
    archive = db.export_archive_data()
    main_content = db.get_main_page_content()
    deepdives = db.get_all_deep_dive_content()
    suggested_terms = db.get_suggested_terms_for_website(limit=3)

    try:
        with open(site_data_dir / 'ticker_scores.json', 'r') as f:
            ticker_scores = json.load(f)
    except FileNotFoundError:
        ticker_scores = []

    js_content = f"""// Auto-generated - {datetime.now().isoformat()}
// DO NOT EDIT MANUALLY

const dashboardData = {{
  generatedAt: "{datetime.now().isoformat()}",
  tickerScores: {json.dumps(ticker_scores, indent=2)},
  archive: {json.dumps(archive, indent=2)},
  mainContent: {json.dumps(main_content, indent=2)},
  deepDives: {json.dumps(deepdives, indent=2)},
  suggestedTerms: {json.dumps(suggested_terms, indent=2)}
}};

if (typeof module !== 'undefined' && module.exports) {{
  module.exports = dashboardData;
}}
"""
    with open(site_data_dir / 'data.js', 'w') as f:
        f.write(js_content)

    total = sum(len(v) if isinstance(v, list) else 0 for v in archive.values())
    print(f"✓ Generated data.js: {len(ticker_scores)} tickers, {total} archive items, {len(deepdives)} deep dives")
    return True


def git_push(commit_msg: str) -> bool:
    """Commit and push changes to GitHub."""
    print("\n" + "="*60)
    print("STEP: Push to GitHub")
    print("="*60)
    try:
        result = subprocess.run(["git", "status", "--porcelain"],
                                capture_output=True, text=True, cwd=WORKSPACE)
        if not result.stdout.strip():
            print("✓ No changes to push")
            return True

        subprocess.run(["git", "add", "-A"], check=True, cwd=WORKSPACE, capture_output=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True,
                       cwd=WORKSPACE, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], check=True,
                       cwd=WORKSPACE, capture_output=True)
        print(f"✓ Pushed to GitHub: {commit_msg}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Git push failed: {e}")
        return False


def build_summary(results: dict) -> str:
    """Build a human-readable summary of what was processed."""
    lines = ["📊 Pipeline Complete\n"]

    new_podcasts = results.get('transcripts_analyzed', 0)
    new_newsletters = results.get('newsletters_imported', 0)
    scores = results.get('scores', 0)

    if new_podcasts:
        lines.append(f"🎙️ {new_podcasts} new podcast(s) analyzed")
    if new_newsletters:
        lines.append(f"📧 {new_newsletters} newsletter(s) imported")
    if scores:
        lines.append(f"📈 {scores} tickers scored")

    # Get top tickers
    try:
        db = get_db()
        top = db.get_top_tickers(date_filter=date.today(), limit=5)
        if top:
            lines.append("\nTop tickers today:")
            for t in top[:5]:
                lines.append(f"  {t['ticker']}: score {t['total_score']:.0f}")
    except Exception:
        pass

    lines.append(f"\n🌐 Website updated")
    return "\n".join(lines)


def main():
    analyze_only = "--analyze-only" in sys.argv

    print("="*60)
    print("AUTO PIPELINE")
    print(f"Mode: {'analyze-only' if analyze_only else 'full'}")
    print(f"Started: {datetime.now()}")
    print("="*60)

    results = {}
    errors = []

    if not analyze_only:
        # Full pipeline: fetch new episodes first
        if not run_script("Podcast Curation", "curate.py", timeout=120):
            errors.append("curation")

        if not run_script("Fetch & Transcribe", "fetch_latest.py", timeout=7200):
            errors.append("fetch")

        if not run_script("Newsletter Ingestion", "ingest.py", timeout=120):
            errors.append("ingest")

    # Always: analyze + export
    results['transcripts_analyzed'] = analyze_transcripts()
    results['newsletters_imported'] = import_newsletters()
    results['scores'] = aggregate_scores()

    run_script("Fetch Prices", "fetch_prices.py", timeout=120)
    run_script("Process Votes", "process_votes.py", timeout=60)

    export_website()

    # Build commit message
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg = f"Pipeline update {ts}: {results['transcripts_analyzed']} podcasts, {results['newsletters_imported']} newsletters"
    git_push(commit_msg)

    # Send summary notification
    summary = build_summary(results)
    if results.get('transcripts_analyzed', 0) > 0 or results.get('newsletters_imported', 0) > 0:
        send_notification("Pipeline Update", summary)
    else:
        print("Nothing new — skipping notification")

    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print(f"Finished: {datetime.now()}")
    print("="*60)
    print(summary)

    if errors:
        print(f"\n⚠ Non-fatal errors in: {', '.join(errors)}")


if __name__ == "__main__":
    main()
