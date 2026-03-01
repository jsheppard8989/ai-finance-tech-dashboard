#!/usr/bin/env python3
"""
Fully automated pipeline - no approval step needed.
Runs end-to-end: fetch → transcribe → analyze → export → push to GitHub.
Sends a summary notification after completion.

Fetch step uses --queue-only: new episodes are enqueued to whisper_queue/ and
the external worker (whisper_worker.sh) transcribes them; completed transcripts
are swept from whisper_done/ on the next run. Ensure the worker is running for
transcription to complete.

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


def run_script(name: str, script: str, timeout: int = 300, extra_args: list = None) -> bool:
    """Run a pipeline script and return success. extra_args: optional list of CLI args (e.g. ['--queue-only'])."""
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"{'='*60}")
    cmd = [sys.executable, script]
    if extra_args:
        cmd.extend(extra_args)
    try:
        result = subprocess.run(
            cmd,
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


def promote_episodes_to_insights() -> int:
    """Promote newly-analyzed podcast episodes into latest_insights for website display.
    
    Picks up any podcast_episodes that are is_processed=1 but have no corresponding
    latest_insights row, and inserts insight cards for them.
    Auto-archives old insights beyond the 8 most recent to keep the main page fresh.
    """
    print("\n" + "="*60)
    print("STEP: Promote Episodes to Insights")
    print("="*60)
    db = get_db()
    promoted = 0

    with db._get_connection() as conn:
        # Find processed episodes not yet in latest_insights
        cursor = conn.execute("""
            SELECT pe.id, pe.podcast_name, pe.episode_title, pe.episode_date,
                   pe.summary, pe.key_takeaways, pe.key_tickers, pe.investment_thesis
            FROM podcast_episodes pe
            WHERE pe.is_processed = 1
              AND pe.id NOT IN (
                  SELECT podcast_episode_id FROM latest_insights
                  WHERE podcast_episode_id IS NOT NULL
              )
            ORDER BY pe.episode_date DESC, pe.id DESC
        """)
        episodes = cursor.fetchall()

    print(f"Found {len(episodes)} processed episodes not yet in insights")

    for ep in episodes:
        ep = dict(ep)

        # Derive key_takeaway from investment_thesis or first key_takeaway bullet
        key_takeaway = ep['investment_thesis'] or ''
        if not key_takeaway and ep['key_takeaways']:
            try:
                takeaways = json.loads(ep['key_takeaways']) if isinstance(ep['key_takeaways'], str) else ep['key_takeaways']
                key_takeaway = takeaways[0] if takeaways else ''
            except Exception:
                key_takeaway = ''
        key_takeaway = (key_takeaway or '')[:500]

        # Derive tickers_mentioned from key_tickers JSON
        tickers = ep['key_tickers'] or '[]'

        # Infer sentiment from summary/thesis keywords
        text = ((ep['summary'] or '') + ' ' + (ep['investment_thesis'] or '')).lower()
        bullish_words = ['bullish', 'buy', 'long', 'upside', 'opportunity', 'growth', 'breakout', 'undervalued']
        bearish_words = ['bearish', 'sell', 'short', 'downside', 'risk', 'collapse', 'overvalued', 'avoid']
        bull_score = sum(1 for w in bullish_words if w in text)
        bear_score = sum(1 for w in bearish_words if w in text)
        sentiment = 'bullish' if bull_score > bear_score else ('bearish' if bear_score > bull_score else 'neutral')

        # Use episode_date as source_date only if it looks recent (within 2 years).
        # Old/unknown dates (scraped episodes with 2023 dates etc.) get today's date
        # so freshly-promoted insights always sort to the top of the main page.
        ep_date = ep['episode_date']
        try:
            from datetime import datetime as _dt
            parsed = _dt.strptime(str(ep_date), '%Y-%m-%d').date()
            days_old = (date.today() - parsed).days
            source_date = str(ep_date) if days_old < 730 else str(date.today())
        except Exception:
            source_date = str(date.today())

        with db._get_connection() as conn:
            # Final duplicate guard: skip if title already exists
            existing = conn.execute(
                "SELECT id FROM latest_insights WHERE title = ?",
                (ep['episode_title'],)
            ).fetchone()
            if existing:
                print(f"  ⏭ Insight already exists: '{ep['episode_title'][:60]}'")
                continue

            conn.execute("""
                INSERT INTO latest_insights
                    (title, source_type, source_name, source_date, summary,
                     key_takeaway, tickers_mentioned, sentiment,
                     display_on_main, display_order, added_date, podcast_episode_id)
                VALUES (?, 'podcast', ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
            """, (
                ep['episode_title'],
                ep['podcast_name'],
                source_date,
                (ep['summary'] or '')[:2000],
                key_takeaway,
                tickers,
                sentiment,
                str(date.today()),
                ep['id']
            ))
            promoted += 1
            print(f"  ✓ Promoted: '{ep['episode_title'][:60]}' (sentiment={sentiment})")

    # Auto-archive oldest insights beyond 8 on main page
    with db._get_connection() as conn:
        main_ids = conn.execute("""
            SELECT id FROM latest_insights
            WHERE display_on_main = 1 AND archived_date IS NULL
            ORDER BY source_date DESC, id DESC
        """).fetchall()

        if len(main_ids) > 8:
            to_archive = [row['id'] for row in main_ids[8:]]
            for insight_id in to_archive:
                conn.execute("""
                    UPDATE latest_insights
                    SET display_on_main = 0,
                        archived_date = date('now'),
                        archived_reason = 'Auto-archived: keep 8 most recent on main'
                    WHERE id = ?
                """, (insight_id,))
            print(f"  ✓ Auto-archived {len(to_archive)} older insights")

    print(f"✓ Promoted {promoted} new insight(s) to website")
    return promoted


def promote_newsletters_to_insights() -> int:
    """Promote unshown newsletters into latest_insights using AI analysis."""
    print("\n" + "="*60)
    print("STEP: Promote Newsletters to Insights")
    print("="*60)
    db = get_db()
    promoted = 0

    # Get newsletters not yet on site
    with db._get_connection() as conn:
        rows = conn.execute("""
            SELECT id, sender, subject, received_date, content_preview
            FROM newsletters
            WHERE added_to_site = 0 AND is_processed = 1
            ORDER BY received_date DESC
        """).fetchall()

    print(f"Found {len(rows)} newsletters not yet on site")
    if not rows:
        return 0

    # Get AI client
    try:
        from analyze_transcript import get_ai_client, analyze_transcript_with_ai
        client_info = get_ai_client()
    except Exception as e:
        print(f"  ✗ Could not get AI client: {e}")
        client_info = None

    # Load full content from inbox JSON files
    inbox_dir = PIPELINE_DIR / "inbox"

    for row in rows:
        nl_id, sender, subject, received_date, content_preview = row
        nl_id = nl_id if not hasattr(nl_id, 'keys') else dict(row)['id']
        row = dict(row)
        nl_id = row['id']
        sender = row['sender']
        subject = row['subject']
        received_date = row['received_date']

        # Decode subject first
        try:
            import email.header
            decoded = email.header.decode_header(subject)
            subject_clean = ''.join(
                part.decode(enc or 'utf-8') if isinstance(part, bytes) else part
                for part, enc in decoded
            )
        except Exception:
            subject_clean = subject

        # Clean sender → human-readable publication name
        # "The Rundown AI <news@daily.therundown.ai>" → "The Rundown AI"
        # "gandolf2026 <gandolf2026@proton.me>" → use subject as publication hint
        import re as _re
        sender_name = sender
        m = _re.match(r'^(.+?)\s*<[^>]+>$', sender.strip())
        if m:
            sender_name = m.group(1).strip().strip('"')
        # If sender_name looks like an email username/handle (no spaces, ends in digits),
        # fall back to subject line as publication name (strip Fw:/Re: prefixes first)
        if not sender_name or '@' in sender_name or _re.match(r'^[a-z0-9_]+\d+$', sender_name.lower()):
            subj_clean = _re.sub(r'^(Fw|Fwd|Re):\s*', '', subject_clean, flags=_re.IGNORECASE).strip()
            if ':' in subj_clean:
                sender_name = subj_clean.split(':')[0].strip()[:50]
            else:
                sender_name = subj_clean[:50] if subj_clean else 'Newsletter'

        # Find matching inbox JSON for full content
        full_content = row.get('content_preview', '')
        for jf in inbox_dir.glob("*.json"):
            try:
                d = json.load(open(jf))
                if d.get('subject', '') == subject or subject_clean in d.get('subject', ''):
                    full_content = d.get('content', d.get('content_preview', ''))
                    break
            except Exception:
                pass

        # Strip markdown links/images to get readable text
        import re
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', full_content)
        text = re.sub(r'View image:.*', '', text)
        text = re.sub(r'Follow image link:.*', '', text)
        text = re.sub(r'Caption:.*', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        if len(text) < 100:
            print(f"  ⏭ Skipping '{subject_clean[:50]}' — content too short")
            continue

        # Use AI to generate insight title + summary if client available
        insight_title = subject_clean.strip()
        summary = text[:500]
        key_takeaway = ''
        tickers_mentioned = row.get('extracted_tickers', '[]') or '[]'

        if client_info:
            try:
                prompt = f"""You are analyzing a newsletter for investment insights.

Newsletter: {subject_clean}
From: {sender}
Content:
{text[:3000]}

Return JSON with:
- "title": punchy 8-12 word insight title (no clickbait, investment-focused)
- "summary": 2-3 sentence summary of key investment implications
- "key_takeaway": single most important actionable insight for investors
- "tickers": list of relevant ticker symbols mentioned
- "sentiment": "bullish", "bearish", or "neutral"
"""
                client_type, client = client_info
                if client_type in ('openai', 'moonshot'):
                    model_name = "moonshot-v1-8k" if client_type == 'moonshot' else "gpt-4o-mini"
                    resp = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        response_format={"type": "json_object"},
                        max_tokens=400
                    )
                    result = json.loads(resp.choices[0].message.content)
                elif client_type == 'gemini':
                    import google.generativeai as genai
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    resp = model.generate_content(prompt)
                    result = json.loads(resp.text)
                else:
                    result = {}

                insight_title = result.get('title', insight_title)[:200]
                summary = result.get('summary', summary)[:2000]
                key_takeaway = result.get('key_takeaway', '')[:500]
                tickers_mentioned = json.dumps(result.get('tickers', []))
                sentiment = result.get('sentiment', 'neutral')
            except Exception as e:
                print(f"  ⚠ AI analysis failed for newsletter: {e}")
                sentiment = 'neutral'
        else:
            sentiment = 'neutral'

        # Parse received_date for source_date
        try:
            from email.utils import parsedate_to_datetime
            source_date = parsedate_to_datetime(received_date).strftime('%Y-%m-%d')
        except Exception:
            source_date = str(date.today())

        # Insert insight
        with db._get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM latest_insights WHERE title = ?", (insight_title,)
            ).fetchone()
            if existing:
                print(f"  ⏭ Already exists: '{insight_title[:60]}'")
                conn.execute("UPDATE newsletters SET added_to_site=1 WHERE id=?", (nl_id,))
                continue

            conn.execute("""
                INSERT INTO latest_insights
                    (title, source_type, source_name, source_date, summary,
                     key_takeaway, tickers_mentioned, sentiment,
                     display_on_main, display_order, added_date)
                VALUES (?, 'newsletter', ?, ?, ?, ?, ?, ?, 1, 0, ?)
            """, (
                insight_title,
                sender_name,
                source_date,
                summary,
                key_takeaway,
                tickers_mentioned,
                sentiment,
                str(date.today())
            ))
            conn.execute("UPDATE newsletters SET added_to_site=1 WHERE id=?", (nl_id,))
            promoted += 1
            print(f"  ✓ Promoted: '{insight_title[:60]}'")

    print(f"✓ Promoted {promoted} newsletter insight(s)")
    return promoted


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
  "generatedAt": "{datetime.now().isoformat()}",
  "tickerScores": {json.dumps(ticker_scores, indent=2)},
  "archive": {json.dumps(archive, indent=2)},
  "mainContent": {json.dumps(main_content, indent=2)},
  "deepDives": {json.dumps(deepdives, indent=2)},
  "suggestedTerms": {json.dumps(suggested_terms, indent=2)}
}};

if (typeof module !== 'undefined' && module.exports) {{
  module.exports = dashboardData;
}}
"""
    with open(site_data_dir / 'data.js', 'w') as f:
        f.write(js_content)

    # Bump cache-buster in index.html so browsers always load fresh data.js
    index_html = SITE_DIR / "index.html"
    if index_html.exists():
        import re as _re
        html = index_html.read_text()
        cache_ver = int(datetime.now().timestamp())
        html_updated = _re.sub(r'data/data\.js\?v=\d+', f'data/data.js?v={cache_ver}', html)
        if html_updated != html:
            index_html.write_text(html_updated)
            print(f"✓ Bumped data.js cache-buster to v={cache_ver}")

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

        if not run_script("Fetch & Transcribe", "fetch_latest.py", timeout=7200, extra_args=["--queue-only"]):
            errors.append("fetch")

        if not run_script("Newsletter Ingestion", "ingest.py", timeout=120):
            errors.append("ingest")

    # Always: analyze + export
    results['transcripts_analyzed'] = analyze_transcripts()
    results['newsletters_imported'] = import_newsletters()
    results['insights_promoted'] = promote_episodes_to_insights()
    results['insights_promoted'] += promote_newsletters_to_insights()
    results['scores'] = aggregate_scores()
    
    # Generate Deep Dives for any insights that don't have one (so site always has full content)
    run_script("Generate Deep Dives", "generate_deepdives.py", timeout=900)
    
    run_script("Fetch Prices", "fetch_prices.py", timeout=120)
    # Generate 2-week charts and price data for the website
    run_script("Generate Charts", "generate_charts.py", timeout=600)
    run_script("Auto-Curate Terms", "auto_curate_terms.py", timeout=60)

    export_website()

    # Build commit message
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg = f"Pipeline update {ts}: {results['transcripts_analyzed']} podcasts, {results['insights_promoted']} insights, {results['newsletters_imported']} newsletters"
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
