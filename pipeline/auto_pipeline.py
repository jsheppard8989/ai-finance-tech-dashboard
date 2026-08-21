#!/usr/bin/env python3
"""
Fully automated pipeline - no approval step needed.
Runs end-to-end: fetch → transcribe → analyze → export → (Fridays CST: weekly debate) → push to GitHub.
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
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from db_manager import get_db, DailyScore
from datetime import date
from workspace_paths import PIPELINE_DIR, SITE_DIR, STATE_DIR, WORKSPACE_ROOT as WORKSPACE

LOCK_FILE = STATE_DIR / "auto_pipeline.lock"
TERM_CURATION_STATE_FILE = STATE_DIR / "term_curation_last_run.json"


def _load_dotenv(env_path: Path) -> None:
    """Load .env into os.environ (simple key=value). Used for GITHUB_PUSH_TOKEN."""
    if not env_path.exists():
        return
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if not k or not v:
                        continue
                    # Prefer .env for API keys when the shell left an empty placeholder.
                    prev = str(os.environ.get(k, "")).strip()
                    if k.endswith("_API_KEY") or k in ("GITHUB_PUSH_TOKEN", "MOONSHOT_API_KEY"):
                        if not prev:
                            os.environ[k] = v
                    elif k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass

def acquire_lock(max_age_hours: int = 6) -> bool:
    """
    Prevent concurrent runs by using a simple lock file.
    If the lock is older than max_age_hours, treat it as stale and replace it.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    try:
        # O_CREAT | O_EXCL ensures we fail if the file already exists
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        try:
            mtime = datetime.fromtimestamp(LOCK_FILE.stat().st_mtime)
            if now - mtime > timedelta(hours=max_age_hours):
                print(f"⚠ Stale lock detected (older than {max_age_hours}h); removing and continuing.")
                LOCK_FILE.unlink(missing_ok=True)
                return acquire_lock(max_age_hours)
        except Exception as e:
            print(f"⚠ Could not inspect existing lock file: {e}")
        print("Another auto_pipeline.py run appears to be in progress; exiting.")
        return False


def release_lock() -> None:
    """Remove the lock file if it exists."""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

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


def load_term_curation_summary() -> dict:
    """Best-effort load of auto_curate_terms run summary."""
    if not TERM_CURATION_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(TERM_CURATION_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def analyze_transcripts() -> int:
    """Run AI analysis on unprocessed transcripts."""
    print("\n" + "="*60)
    print("STEP: Transcript AI Analysis")
    print("="*60)
    _load_dotenv(WORKSPACE / ".env")
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


def sync_main_insights_with_deepdives(max_on_main: int = 8) -> int:
    """Turn on main-page display only for insights that already have Deep Dive content.

    Clears display_on_main for all non-archived rows, then enables the top ``max_on_main``
    by source_date among insights that have a ``deep_dive_content`` row. Aligns
    ``podcast_episodes.added_to_site`` with whether the episode is on the main insight list.
    """
    db = get_db()
    with db._get_connection() as conn:
        conn.execute(
            """
            UPDATE latest_insights SET display_on_main = 0
            WHERE archived_date IS NULL
            """
        )
        rows = conn.execute(
            """
            SELECT li.id FROM latest_insights li
            INNER JOIN deep_dive_content ddc ON ddc.insight_id = li.id
            WHERE li.archived_date IS NULL
            ORDER BY li.source_date DESC, li.id DESC
            LIMIT ?
            """,
            (max_on_main,),
        ).fetchall()
        main_ids = [int(r["id"]) for r in rows]
        for iid in main_ids:
            conn.execute(
                "UPDATE latest_insights SET display_on_main = 1 WHERE id = ?",
                (iid,),
            )
        conn.execute(
            """
            UPDATE podcast_episodes
            SET added_to_site = CASE
                WHEN id IN (
                    SELECT podcast_episode_id FROM latest_insights
                    WHERE display_on_main = 1 AND podcast_episode_id IS NOT NULL
                ) THEN 1 ELSE 0 END
            WHERE id IN (
                SELECT DISTINCT podcast_episode_id FROM latest_insights
                WHERE podcast_episode_id IS NOT NULL
            )
            """
        )
    print(f"  ✓ Main insight list synced with Deep Dives ({len(main_ids)} on main)")
    return len(main_ids)


def promote_episodes_to_insights() -> int:
    """Promote newly-analyzed podcast episodes into latest_insights for website display.
    
    Picks up any podcast_episodes that are is_processed=1 but have no corresponding
    latest_insights row, and inserts insight rows with display_on_main=0 until Deep Dives
    exist; auto_pipeline calls sync_main_insights_with_deepdives() after generate_deepdives.
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
                   pe.summary, pe.key_takeaways, pe.key_tickers, pe.investment_thesis,
                   pe.transcript_path
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

    from analyze_transcript import is_hostile_transcript_stem

    for ep in episodes:
        ep = dict(ep)

        tp = (ep.get("transcript_path") or "").strip()
        if tp:
            stem = Path(tp).stem
            pn = (ep.get("podcast_name") or "").strip()
            if is_hostile_transcript_stem(stem) and pn in ("Unknown Podcast", "Unknown", ""):
                print(
                    f"  ⏭ Not promoting episode {ep['id']}: transcript stem is URL-like/CDN "
                    f"and podcast_name is unknown — fix or delete this row."
                )
                continue

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

        # Date consistency: source_date MUST equal episode release date so insights and pundits show the same date for the same episode.
        ep_date = ep['episode_date']
        try:
            source_date = str(ep_date) if ep_date else str(date.today())
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
                VALUES (?, 'podcast', ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
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
            print(
                f"  ✓ Queued insight (awaiting Deep Dive before main page): "
                f"'{ep['episode_title'][:60]}' (sentiment={sentiment})"
            )

    print(f"✓ Promoted {promoted} new podcast insight row(s) (off main until Deep Dive + sync)")
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
                VALUES (?, 'newsletter', ?, ?, ?, ?, ?, ?, 0, 0, ?)
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
    """Export data.js and supporting files for the website (uses export_data for single implementation)."""
    print("\n" + "="*60)
    print("STEP: Export Website Data")
    print("="*60)
    try:
        from export_data import export_website_data, generate_website_js
        export_website_data()
        generate_website_js()
    except Exception as e:
        print(f"✗ Export failed: {e}")
        return False

    # data.js query string is bumped for all site/*.html in export_data.generate_website_js()
    return True


def _is_friday_america_chicago() -> bool:
    """True if local date is Friday in America/Chicago (matches debate_weekly.friday_iso_cst)."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Chicago")
        return datetime.now(tz).weekday() == 4
    except Exception:
        return datetime.now().weekday() == 4


def maybe_run_weekly_debate_after_export() -> bool:
    """
    debate_weekly.py reads site/data/pundits.json (written by export). Run only on Fridays CST.
    If the contract is already current for this Friday, debate_weekly exits quickly.
    Failures are non-fatal for the rest of the pipeline (site data still pushes).
    """
    if not _is_friday_america_chicago():
        return True
    return run_script("Weekly Debate", "debate_weekly.py", timeout=7200)


def git_push(commit_msg: str, pathspecs=None) -> bool:
    """Commit and push changes to GitHub. On failure, log stderr and send notification.
    If GITHUB_PUSH_TOKEN is set in workspace .env, uses it for push (so cron can push without keychain).

    If pathspecs is set (e.g. [\"site\"]), only those paths are staged — use for publish_site.py so
    unrelated workspace changes are not swept into the same commit.
    """
    print("\n" + "="*60)
    print("STEP: Push to GitHub")
    print("="*60)
    _load_dotenv(WORKSPACE / ".env")
    token = os.environ.get("GITHUB_PUSH_TOKEN", "").strip()
    original_url = None
    if token:
        try:
            r = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                capture_output=True, text=True, cwd=WORKSPACE, timeout=5
            )
            if r.returncode == 0 and r.stdout:
                url = r.stdout.strip()
                # Build https://USER:PAT@github.com/owner/repo.git
                if url.startswith("https://github.com/"):
                    path = url.replace("https://github.com", "", 1)
                    user = os.environ.get("GITHUB_USERNAME", "").strip() or path.strip("/").split("/")[0]
                    auth_url = f"https://{user}:{token}@github.com{path}"
                    subprocess.run(
                        ["git", "config", "remote.origin.url", auth_url],
                        check=True, cwd=WORKSPACE, capture_output=True
                    )
                    original_url = url
        except Exception:
            pass
    try:
        # Integrate remote main before commit/push so we avoid non-fast-forward rejections
        # when GitHub (or another machine) advanced main after our last fetch.
        skip_pull = os.environ.get("SKIP_GIT_PULL_BEFORE_PUSH", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not skip_pull:
            print("Git: fetch + pull --rebase --autostash origin main (before commit/push)...")
            r_fetch = subprocess.run(
                ["git", "fetch", "origin"],
                capture_output=True,
                text=True,
                cwd=WORKSPACE,
                timeout=120,
            )
            if r_fetch.returncode != 0:
                msg = (r_fetch.stderr or r_fetch.stdout or "git fetch failed").strip()
                print(f"✗ {msg}")
                send_notification("Pipeline: Git fetch failed", msg[:900], priority=1)
                return False
            r_pull = subprocess.run(
                ["git", "pull", "--rebase", "--autostash", "origin", "main"],
                capture_output=True,
                text=True,
                cwd=WORKSPACE,
                timeout=180,
            )
            if r_pull.returncode != 0:
                msg = (r_pull.stderr or r_pull.stdout or "git pull --rebase failed").strip()
                print(f"✗ {msg}")
                send_notification(
                    "Pipeline: Git pull failed before push",
                    msg[:900] + "\n\nResolve conflicts, then push manually.",
                    priority=1,
                )
                return False

        status_cmd = ["git", "status", "--porcelain"]
        if pathspecs:
            status_cmd.extend(["--"] + list(pathspecs))
        result = subprocess.run(status_cmd, capture_output=True, text=True, cwd=WORKSPACE)
        if result.stdout.strip():
            if pathspecs:
                subprocess.run(
                    ["git", "add", "--"] + list(pathspecs),
                    check=True,
                    cwd=WORKSPACE,
                    capture_output=True,
                )
            else:
                subprocess.run(["git", "add", "-A"], check=True, cwd=WORKSPACE, capture_output=True)
            subprocess.run(["git", "commit", "-m", commit_msg], check=True,
                           cwd=WORKSPACE, capture_output=True)

        def _do_push() -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", "push", "origin", "main"],
                capture_output=True,
                text=True,
                cwd=WORKSPACE,
                timeout=60,
            )

        push_result = _do_push()
        if push_result.returncode != 0:
            err = (push_result.stderr or push_result.stdout or str(push_result)).strip()
            # Remote often advances between pull and push (another clone, GitHub UI, CI).
            # One extra fetch + rebase + push usually clears "fetch first" without manual steps.
            transient = (
                "fetch first" in err.lower()
                or "non-fast-forward" in err.lower()
                or "rejected" in err.lower()
            )
            if transient and not skip_pull:
                print("Git: push rejected (remote moved); retrying after pull --rebase --autostash...")
                r2 = subprocess.run(
                    ["git", "fetch", "origin"],
                    capture_output=True,
                    text=True,
                    cwd=WORKSPACE,
                    timeout=120,
                )
                if r2.returncode == 0:
                    r3 = subprocess.run(
                        ["git", "pull", "--rebase", "--autostash", "origin", "main"],
                        capture_output=True,
                        text=True,
                        cwd=WORKSPACE,
                        timeout=180,
                    )
                    if r3.returncode == 0:
                        push_result = _do_push()
            if push_result.returncode != 0:
                err = (push_result.stderr or push_result.stdout or str(push_result)).strip()
                print(f"✗ Git push failed: {err}")
                send_notification(
                    "Pipeline: Git push failed",
                    "Site not updated on GitHub. From the repo root run:\n"
                    "  git fetch origin && git pull --rebase --autostash origin main\n"
                    "then resolve any conflicts and: git push origin main\n\n"
                    f"{err[:500]}",
                    priority=1,
                )
                return False
        if result.stdout.strip():
            print(f"✓ Pushed to GitHub: {commit_msg}")
        else:
            print("✓ Already up to date (no new commits to push)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Git commit/add failed: {e}")
        send_notification("Pipeline: Git commit failed", str(e), priority=1)
        return False
    except subprocess.TimeoutExpired:
        print("✗ Git push timed out (60s)")
        send_notification("Pipeline: Git push timed out", "Run 'git push origin main' from the workspace.", priority=1)
        return False
    finally:
        if original_url:
            try:
                subprocess.run(
                    ["git", "config", "remote.origin.url", original_url],
                    check=True, cwd=WORKSPACE, capture_output=True
                )
            except Exception:
                pass


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
    terms_promoted = int(results.get("terms_promoted", 0) or 0)
    terms_review = int(results.get("terms_review", 0) or 0)
    terms_pending_after = results.get("terms_pending_after")
    if terms_promoted or terms_review or terms_pending_after is not None:
        extra = []
        if terms_promoted:
            extra.append(f"{terms_promoted} promoted")
        if terms_review:
            extra.append(f"{terms_review} flagged for review")
        if terms_pending_after is not None:
            extra.append(f"{int(terms_pending_after)} pending")
        lines.append("🪟 Overton candidates: " + ", ".join(extra))

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

    if results.get("deep_dives_ok") is False:
        lines.append("\n⚠ Site export skipped (Deep Dive step did not complete).")
    else:
        lines.append("\n🌐 Website export ran (see git push result for publish).")
    return "\n".join(lines)


def main():
    if not acquire_lock():
        return

    analyze_only = "--analyze-only" in sys.argv
    ENABLE_AI_ENTITY_PIPELINE = False  # flip to True when ready

    print("="*60)
    print("AUTO PIPELINE")
    print(f"Mode: {'analyze-only' if analyze_only else 'full'}")
    print(f"Started: {datetime.now()}")
    print("="*60)

    results = {}
    errors = []

    try:
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

        # Optional: semantic layer AI pipeline (entities/appearances/ideas)
        if ENABLE_AI_ENTITY_PIPELINE:
            db = get_db()
            with db._get_connection() as conn:
                ep_rows = conn.execute(
                    """
                    SELECT id, transcript_path
                    FROM podcast_episodes
                    WHERE is_processed = 1
                    """
                ).fetchall()
            for row in ep_rows:
                ep_id = row["id"]
                tpath = row["transcript_path"]
                if not tpath or not (PIPELINE_DIR / Path(tpath).name).exists():
                    # Prefer absolute paths; if transcript_path is relative, best-effort resolution
                    continue
                run_script(
                    f"AI Analyze Transcript {ep_id}",
                    "ai_analyze_transcript.py",
                    timeout=600,
                    extra_args=["--episode-id", str(ep_id), "--transcript-path", tpath],
                )
        results['newsletters_imported'] = import_newsletters()
        results['insights_promoted'] = promote_episodes_to_insights()
        results['insights_promoted'] += promote_newsletters_to_insights()
        results['scores'] = aggregate_scores()

        # Opportunistic semantic-layer enrichment for pundits (net worth, bios).
        # Script is idempotent and conservative; safe to run before exporting site JSON.
        try:
            from enrich_pundits import enrich_pundits
            results['pundits_enriched'] = enrich_pundits(max_pundits=20)
        except Exception as e:
            print(f"  ⚠ Pundit enrichment skipped: {e}")
            results['pundits_enriched'] = 0

        # Deep Dives must succeed before we expose insights on the main page or publish site data.
        dd_ok = run_script("Generate Deep Dives", "generate_deepdives.py", timeout=900)
        results["deep_dives_ok"] = bool(dd_ok)
        if dd_ok:
            results["main_insights_synced"] = sync_main_insights_with_deepdives()
        else:
            errors.append("deep_dives")
            results["main_insights_synced"] = 0
            send_notification(
                "Pipeline: Deep Dives failed",
                "generate_deepdives.py did not complete successfully. Export and git push were skipped; "
                "insights stay off the main list until the next successful run.",
                priority=1,
            )

        run_script("Fetch Prices", "fetch_prices.py", timeout=120)
        # Generate 2-week charts and price data for the website
        if not run_script("Generate Charts", "generate_charts.py", timeout=600):
            errors.append("charts")
            send_notification(
                "Pipeline: Charts failed",
                "generate_charts.py failed. Existing chart images may be stale. Check pipeline logs.",
                priority=1,
            )
        run_script("Process Term Promotion Replies", "process_term_promotion_replies.py", timeout=120)
        run_script("Auto-Curate Terms", "auto_curate_terms.py", timeout=60)
        term_summary = load_term_curation_summary()
        results["terms_promoted"] = int(term_summary.get("promoted", 0) or 0)
        results["terms_review"] = int(term_summary.get("review", 0) or 0)
        if "pending_after" in term_summary:
            results["terms_pending_after"] = int(term_summary.get("pending_after", 0) or 0)
        if "pending_before" in term_summary:
            results["terms_pending_before"] = int(term_summary.get("pending_before", 0) or 0)
        run_script("Extract Podcast Guests", "extract_guests.py", timeout=180)

        export_ok = False
        if dd_ok:
            export_ok = export_website()
            if not export_ok:
                errors.append("export")
            elif not maybe_run_weekly_debate_after_export():
                errors.append("weekly_debate")
                send_notification(
                    "Pipeline: Weekly debate failed",
                    "debate_weekly.py failed after export; debate contract/audio were not updated.",
                    priority=1,
                )
        else:
            print("  ⏭ Skipping export and git push (Deep Dive step did not complete).")

        # Build commit message
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"Pipeline update {ts}: {results['transcripts_analyzed']} podcasts, {results['insights_promoted']} insights, {results['newsletters_imported']} newsletters"
        pushed_ok = git_push(commit_msg, pathspecs=["site"]) if export_ok else False
        if not export_ok and dd_ok:
            print("  ⚠ Skipping git push (export failed).")

        # Drop episode downloads once commits are published (transcripts retained)
        if pushed_ok:
            try:
                from fetch_latest import cleanup_audio_for_site_published_episodes

                cleanup_audio_for_site_published_episodes()
            except Exception as e:
                print(f"  ⚠ Post-publish audio cleanup skipped: {e}")

        # Send summary notification
        summary = build_summary(results)
        if (
            results.get('transcripts_analyzed', 0) > 0
            or results.get('newsletters_imported', 0) > 0
            or results.get("terms_promoted", 0) > 0
            or results.get("terms_review", 0) > 0
        ):
            send_notification("Pipeline Update", summary)
        else:
            print("Nothing new — skipping notification")

        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        finished_at = datetime.now()
        print(f"Finished: {finished_at}")
        print("="*60)
        print(summary)

        # Write local run report for debugging/ops.
        try:
            db = get_db()
            stats = db.get_stats() if hasattr(db, "get_stats") else {}
        except Exception as e:
            print(f"  ⚠ Could not load DB stats for report: {e}")
            stats = {}

        try:
            report = {
                "last_run_iso": finished_at.isoformat(),
                "step_results": {k: (v if isinstance(v, (bool, int)) else bool(v)) for k, v in results.items()},
                "counts": stats,
                "errors": errors[:],
            }
            state_dir = STATE_DIR
            state_dir.mkdir(parents=True, exist_ok=True)
            with open(state_dir / "last_run_report.json", "w") as f:
                json.dump(report, f, indent=2, default=str)
        except Exception as e:
            print(f"  ⚠ Could not write local run report: {e}")

        # Mark successful run for catch-up logic (so "run on wake" knows we ran today)
        try:
            (STATE_DIR / "last_evening_run.txt").write_text(datetime.now().strftime("%Y-%m-%d %H:%M"))
        except Exception as e:
            print(f"  (Could not write last_evening_run.txt: {e})")

        if errors:
            print(f"\n⚠ Non-fatal errors in: {', '.join(errors)}")
    finally:
        release_lock()


if __name__ == "__main__":
    main()
