#!/usr/bin/env python3
"""
Fetch and transcribe latest podcast episodes.
Run this to get the most recent episode from each feed.

Default: uses queue + worker (whisper_worker.sh). Episodes are enqueued to
whisper_queue/ and the worker writes transcripts to whisper_done/. Either wait
for completion (default) or use --queue-only to enqueue and exit (transcripts
picked up on next run). Do not set USE_FASTER_WHISPER unless you want in-process
transcription (can OOM/timeout).
"""

import os
import sys
import xml.etree.ElementTree as ET
import urllib.request
import subprocess
import json
import shutil
from pathlib import Path
from datetime import datetime

from workspace_paths import (
    AUDIO_DIR,
    DB_PATH,
    FEEDS_FILE,
    PIPELINE_AUDIO_DIR,
    PIPELINE_DIR,
    TRANSCRIPT_DIR,
    WHISPER_DONE_DIR,
    WHISPER_QUEUE_DIR,
)
# Hard stop: do not download anything older than Feb 2026
from cutoff_date import is_before_cutoff

LOG_FILE = PIPELINE_DIR / "state" / "fetch_log.json"

AUDIO_DIR.mkdir(exist_ok=True)
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
PIPELINE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

def load_feeds():
    """Load podcast feed URLs from file."""
    feeds = []
    if FEEDS_FILE.exists():
        with open(FEEDS_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('http'):
                    feeds.append(line)
    return feeds

def fetch_latest_episode(feed_url, max_age_days=14, max_items_scan=25):
    """Pick the newest RSS episode for this feed that passes date rules and is not already in the DB.

    Feeds are usually ordered newest-first, but we **scan multiple `<item>` rows** (not only the first).
    Otherwise, when item #1 is already ingested (e.g. April 30) and item #2 is new (May 1), we would
    incorrectly return "no work" and never download the newer episode.
    """
    try:
        req = urllib.request.Request(feed_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            xml_content = response.read()
        
        root = ET.fromstring(xml_content)
        
        # Find podcast title
        channel = root.find('.//channel')
        podcast_title = "Unknown"
        if channel is not None:
            title_elem = channel.find('title')
            if title_elem is not None:
                podcast_title = title_elem.text
        
        items = root.findall('.//item')[:max_items_scan]
        if not items:
            return None

        try:
            from curate import CURRENT_MONTH_ONLY
        except Exception:
            CURRENT_MONTH_ONLY = True

        from datetime import date

        for item in items:
            title = ""
            enclosure_url = ""
            pub_date_str = ""
            rss_guid = ""

            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                title = title_elem.text

            enclosure = item.find('enclosure')
            if enclosure is not None:
                enclosure_url = enclosure.get('url', '')

            pub_elem = item.find('pubDate')
            if pub_elem is not None and pub_elem.text:
                pub_date_str = pub_elem.text

            guid_elem = item.find('guid')
            if guid_elem is not None and guid_elem.text:
                rss_guid = guid_elem.text.strip()

            if not title or not enclosure_url:
                continue

            # Parse published date
            pub_date_iso = None
            if pub_date_str:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_date_iso = parsedate_to_datetime(pub_date_str).strftime('%Y-%m-%d')
                except Exception:
                    pass

            if pub_date_iso:
                pub = date.fromisoformat(pub_date_iso)
                if CURRENT_MONTH_ONLY:
                    today = date.today()
                    if (pub.year, pub.month) != (today.year, today.month):
                        print(f"  ⏭ Skipping '{title[:50]}' — published {pub_date_iso} (not in current month)")
                        continue
                elif max_age_days is not None:
                    age_days = (date.today() - pub).days
                    if age_days > max_age_days:
                        print(f"  ⏭ Skipping '{title[:50]}' — published {pub_date_iso} ({age_days}d ago, >{max_age_days}d limit)")
                        continue

                if is_before_cutoff(pub_date_iso):
                    print(f"  ⏭ Skipping '{title[:50]}' — published {pub_date_iso} (before cutoff)")
                    continue

            # Gate: skip if rss_guid already in database
            if rss_guid:
                import sqlite3 as _sqlite3

                _conn = _sqlite3.connect(str(DB_PATH))
                existing = _conn.execute(
                    "SELECT id FROM podcast_episodes WHERE rss_guid=?", (rss_guid,)
                ).fetchone()
                _conn.close()
                if existing:
                    print(f"  ⏭ Already have '{title[:50]}' (guid match, ep_id={existing[0]}) — scanning feed for next…")
                    continue

            return {
                'podcast': podcast_title,
                'title': title,
                'audio_url': enclosure_url,
                'published': pub_date_str,
                'published_date': pub_date_iso,
                'rss_guid': rss_guid,
                'feed': feed_url
            }

        return None

    except Exception as e:
        print(f"  ✗ Error fetching {feed_url}: {e}")
        return None


def check_feeds(limit_per_feed=5):
    """Fetch each feed and print latest episodes (no download, no DB check)."""
    from datetime import date
    from email.utils import parsedate_to_datetime

    feeds = load_feeds()
    if not feeds:
        print(f"No feeds found. Check {FEEDS_FILE}")
        return

    print("=" * 70)
    print("RSS feed check — latest episodes (no download)")
    print("=" * 70)
    today = date.today()

    for feed_url in feeds:
        try:
            req = urllib.request.Request(feed_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                xml_content = response.read()
            root = ET.fromstring(xml_content)
            channel = root.find('.//channel')
            podcast_title = "Unknown"
            if channel is not None:
                t = channel.find('title')
                if t is not None and t.text:
                    podcast_title = t.text

            items = root.findall('.//item')[:limit_per_feed]
            print(f"\n📻 {podcast_title}")
            print(f"   Feed: {feed_url[:60]}...")
            if not items:
                print("   No episodes found")
                continue
            for i, item in enumerate(items):
                title_elem = item.find('title')
                pub_elem = item.find('pubDate')
                title = (title_elem.text or "").strip()[:70]
                pub_date_str = (pub_elem.text or "").strip()
                pub_date_iso = None
                age_days = None
                if pub_date_str:
                    try:
                        dt = parsedate_to_datetime(pub_date_str)
                        pub_date_iso = dt.strftime("%Y-%m-%d")
                        pub = dt.date()
                        age_days = (today - pub).days
                    except Exception:
                        pass
                label = "  NEW" if (age_days is not None and age_days <= 2) else ""
                age_str = f" ({age_days}d ago)" if age_days is not None else ""
                print(f"   {i+1}. {title} — {pub_date_iso or pub_date_str}{age_str}{label}")
        except Exception as e:
            print(f"\n📻 {feed_url[:50]}...")
            print(f"   ✗ Error: {e}")
    print("\n" + "=" * 70)


def _safe_filename_stem(s):
    """Short alphanumeric slug for use in filenames."""
    import re
    s = re.sub(r'[^\w\s-]', '', (s or '').lower())
    s = re.sub(r'[-\s]+', '_', s).strip('_')[:32]
    return s or 'ep'


def download_episode(episode):
    """Download the audio file for an episode."""
    audio_url = episode['audio_url']
    
    # Create filename from URL
    if 'megaphone.fm' in audio_url:
        # Extract megaphone ID
        filename = audio_url.split('/')[-1].split('?')[0]
    elif 'anchor.fm' in audio_url or 'cloudfront.net' in audio_url:
        # Use last part of path
        filename = audio_url.split('/')[-1].split('?')[0]
    else:
        filename = audio_url.split('/')[-1].split('?')[0]
    
    if not filename.endswith('.mp3'):
        filename += '.mp3'
    
    # Fallback: Simplecast and other feeds often use generic URLs (e.g. default.mp3)
    # so every episode would overwrite. Use a unique name from podcast + date + guid/title.
    stem = Path(filename).stem
    if stem == 'default' or 'simplecast.com' in audio_url:
        pub = (episode.get('published_date') or '').replace('-', '')[:8]
        guid = (episode.get('rss_guid') or '')
        if guid and len(guid) < 50 and '/' not in guid:
            unique = _safe_filename_stem(guid)
        else:
            unique = _safe_filename_stem(episode.get('title', 'ep'))
        pod_slug = _safe_filename_stem(episode.get('podcast', 'podcast'))[:20]
        filename = f"{pod_slug}_{pub}_{unique}.mp3"
    
    filepath = AUDIO_DIR / filename
    
    # Skip if already downloaded
    if filepath.exists():
        print(f"  ✓ Already downloaded: {filename}")
        return str(filepath)
    
    print(f"  ⬇️  Downloading: {filename}")
    print(f"     Title: {episode['title'][:60]}...")
    
    try:
        req = urllib.request.Request(audio_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()
        if not data or len(data) < 1000:
            print(f"     ✗ Download empty or too small ({len(data)} bytes), skipping")
            return None
        with open(filepath, 'wb') as f:
            f.write(data)
        print(f"     ✓ Downloaded to {filepath}")
        return str(filepath)
    except Exception as e:
        print(f"     ✗ Download failed: {e}")
        if filepath.exists():
            try:
                filepath.unlink()
            except OSError:
                pass
        return None

def _delete_audio_for_stem(stem: str) -> int:
    """Delete episode audio for this transcript stem under workspace/audio, whisper_queue, pipeline/audio."""
    deleted = 0
    for base_dir in (AUDIO_DIR, WHISPER_QUEUE_DIR, PIPELINE_AUDIO_DIR):
        if not base_dir.exists():
            continue
        for ext in (".mp3", ".m4a"):
            path = base_dir / f"{stem}{ext}"
            if path.exists():
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    pass
    return deleted


def cleanup_audio_for_site_published_episodes() -> int:
    """
    Remove downloaded episode audio once an episode is on the site (DB added_to_site=1),
    is fully processed (is_processed=1), and the transcript file still exists on disk.

    Keeps transcripts and site assets under site/audio. Skips entirely if DISABLE_AUDIO_CLEANUP=1.

    Call after export/publish (e.g. after a successful git push) so unpublished work-in-flight
    still keeps its MP3s.

    Returns the number of audio files removed.
    """
    if os.environ.get("DISABLE_AUDIO_CLEANUP", "").strip().lower() in ("1", "true", "yes"):
        print("  ⏭ Audio cleanup skipped (DISABLE_AUDIO_CLEANUP is set)")
        return 0
    try:
        from db_manager import get_db
    except ImportError:
        print("  ⚠ Audio cleanup skipped: db_manager unavailable")
        return 0

    db = get_db()
    deleted_total = 0
    stems_done: set[str] = set()
    query = """
        SELECT DISTINCT transcript_path
        FROM podcast_episodes
        WHERE added_to_site = 1
          AND is_processed = 1
          AND transcript_path IS NOT NULL
          AND TRIM(transcript_path) != ''
    """
    try:
        with db._get_connection() as conn:
            rows = conn.execute(query).fetchall()
        for row in rows:
            raw = (row["transcript_path"] or "").strip()
            if not raw:
                continue
            tp = Path(raw)
            if not tp.is_absolute():
                tp = (PIPELINE_DIR / tp).resolve()
            else:
                tp = tp.resolve()
            if tp.suffix.lower() != ".txt":
                continue
            if not tp.is_file():
                continue
            stem = tp.stem
            if stem in stems_done:
                continue
            stems_done.add(stem)
            deleted_total += _delete_audio_for_stem(stem)
        if deleted_total:
            print(
                f"  ✓ Post-publish audio cleanup: removed {deleted_total} file(s) "
                f"(kept transcripts; unpublished episodes untouched)"
            )
        return deleted_total
    except Exception as e:
        print(f"  ⚠ Audio cleanup skipped: {e}")
        return 0


def sweep_completed_transcripts():
    """
    Sweep completed transcripts from whisper_done into pipeline/transcripts.
    Source MP3s are left in place until the episode is on the site — see cleanup_audio_for_site_published_episodes().
    """
    WHISPER_DONE_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    moved = 0

    # Move transcript text files
    for txt in WHISPER_DONE_DIR.glob("*.txt"):
        dest = TRANSCRIPT_DIR / txt.name
        if not dest.exists():
            shutil.move(str(txt), str(dest))
            moved += 1

    # Move matching metadata files
    for meta in WHISPER_DONE_DIR.glob("*.meta.json"):
        dest = TRANSCRIPT_DIR / meta.name
        if not dest.exists():
            shutil.move(str(meta), str(dest))
            moved += 1

    # Keep corresponding MP3s until the episode is on the site (see cleanup_audio_for_site_published_episodes).

    if moved:
        print(f"  ✓ Swept {moved} completed transcript file(s) from whisper_done into transcripts")


def cleanup_orphan_audio():
    """
    Deprecated: transcripts alone no longer trigger audio deletion.
    Audio is removed only after episodes are marked on-site — see cleanup_audio_for_site_published_episodes().
    """
    cleanup_audio_for_site_published_episodes()

def transcribe_via_launchagent(audio_path, episode, poll_interval=15, timeout_secs=3600):
    """
    Submit audio to the whisper LaunchAgent queue and poll for completion.
    The LaunchAgent runs outside the constrained automation sandbox, avoiding OOM SIGKILL.
    Returns path to transcript file on success, None on failure/timeout.
    """
    import json as _json, time

    audio_file = Path(audio_path)
    name = audio_file.stem
    WHISPER_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    WHISPER_DONE_DIR.mkdir(parents=True, exist_ok=True)

    # Final transcript destination (in TRANSCRIPT_DIR)
    transcript_file = TRANSCRIPT_DIR / f"{name}.txt"
    if transcript_file.exists():
        print(f"  ✓ Already transcribed: {transcript_file.name}")
        return str(transcript_file)

    # Write sidecar meta before submitting
    meta_file = WHISPER_QUEUE_DIR / f"{name}.meta.json"
    meta = {
        'podcast_name':  episode.get('podcast', 'Unknown'),
        'episode_title': episode.get('title', ''),
        'audio_url':     episode.get('audio_url', ''),
        'feed_url':      episode.get('feed', ''),
        'published':     episode.get('published', ''),
        'published_date':episode.get('published_date', ''),
        'rss_guid':      episode.get('rss_guid', ''),
    }
    meta_file.write_text(_json.dumps(meta, indent=2))

    # Copy audio into queue (move would be faster but copy is safer)
    queue_mp3 = WHISPER_QUEUE_DIR / audio_file.name
    if not queue_mp3.exists():
        import shutil
        shutil.copy2(str(audio_path), str(queue_mp3))
        print(f"  📥 Submitted to whisper queue: {queue_mp3.name}")
    else:
        print(f"  📥 Already in queue: {queue_mp3.name}")

    # Enqueue-only: do not wait for worker (transcripts picked up on next run)
    if os.environ.get("USE_QUEUE_ONLY"):
        print(f"  ⏭ Queue-only mode: not waiting. Run pipeline again after worker finishes.")
        return None

    # Poll for completion
    done_txt  = WHISPER_DONE_DIR / f"{name}.txt"
    done_meta = WHISPER_DONE_DIR / f"{name}.meta.json"
    deadline  = time.time() + timeout_secs
    elapsed   = 0
    print(f"  ⏳ Waiting for LaunchAgent to transcribe (up to {timeout_secs//60} min)...")

    while time.time() < deadline:
        if done_txt.exists():
            # Move results into pipeline transcript dir
            import shutil
            shutil.move(str(done_txt), str(transcript_file))
            if done_meta.exists():
                shutil.move(str(done_meta), str(TRANSCRIPT_DIR / f"{name}.meta.json"))
            print(f"  ✓ Transcription complete: {transcript_file.name}")
            return str(transcript_file)
        time.sleep(poll_interval)
        elapsed += poll_interval
        if elapsed % 120 == 0:
            print(f"  ⏳ Still waiting... ({elapsed//60} min elapsed)")

    print(f"  ✗ Transcription timed out after {timeout_secs//60} min")
    return None


def get_audio_duration(audio_path):
    """Return duration in seconds using ffprobe, or None on failure."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(audio_path)],
            capture_output=True, text=True, timeout=30
        )
        import json as _json
        data = _json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception:
        return None


def chunk_audio(audio_path, chunk_secs=1800):
    """
    Split audio into chunks of chunk_secs seconds using ffmpeg.
    Returns list of chunk file paths. Chunks are written to /tmp/.
    """
    duration = get_audio_duration(audio_path)
    if duration is None:
        return [audio_path]  # can't probe — try full file

    audio_file = Path(audio_path)
    chunks = []
    start = 0
    idx = 1
    while start < duration:
        chunk_path = Path('/tmp') / f"{audio_file.stem}_chunk{idx}.mp3"
        subprocess.run(
            ['ffmpeg', '-i', str(audio_path), '-ss', str(start), '-t', str(chunk_secs),
             '-acodec', 'copy', str(chunk_path), '-y'],
            capture_output=True, timeout=120
        )
        if chunk_path.exists():
            chunks.append(chunk_path)
        start += chunk_secs
        idx += 1
    return chunks if chunks else [audio_path]


def transcribe_episode(audio_path, episode):
    """Transcribe: use queue+worker (default), or in-process if USE_FASTER_WHISPER=1.
    With USE_QUEUE_ONLY=1 or --queue-only, only enqueue and return None (no wait).
    """
    print(f"  🎙️  Transcribing: {Path(audio_path).name}")
    if os.environ.get("USE_FASTER_WHISPER"):
        return _transcribe_via_openai_whisper_local(audio_path, episode)
    return transcribe_via_launchagent(audio_path, episode)


def _transcribe_via_openai_whisper_local(audio_path, episode):
    """
    Transcribe in-process with openai-whisper (PyTorch). Stable on macOS.
    Set USE_FASTER_WHISPER=1 to use this instead of the LaunchAgent.
    """
    try:
        from transcribe_local import transcribe_file, TRANSCRIPT_DIR
    except ImportError:
        print("  ✗ transcribe_local not found (need openai-whisper: pip install openai-whisper)")
        return None
    audio_file = Path(audio_path)
    transcript_file = TRANSCRIPT_DIR / f"{audio_file.stem}.txt"
    if transcribe_file(audio_file, output_path=transcript_file):
        return str(transcript_file)
    return None

def save_log(results):
    """Save fetch and transcription log."""
    log_data = {
        'timestamp': datetime.now().isoformat(),
        'results': results
    }
    
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'w') as f:
        json.dump(log_data, f, indent=2)
    
    return LOG_FILE

def main():
    # Check feeds only (no download, no DB) — just list latest episodes
    if "--check-only" in sys.argv or "-c" in sys.argv:
        check_feeds()
        return

    # Support --queue-only (enqueue without waiting for transcription)
    if "--queue-only" in sys.argv:
        os.environ["USE_QUEUE_ONLY"] = "1"

    if "--cleanup-published-audio" in sys.argv:
        print("Cleaning up workspace audio for site-published episodes (transcripts retained)...")
        n = cleanup_audio_for_site_published_episodes()
        print(f"Done ({n} audio file(s) removed).")
        return

    print("=" * 70)
    print("Fetch & Transcribe Latest Podcast Episodes")
    print("=" * 70)

    # First, sweep any transcripts that Whisper finished after a previous run timed out.
    sweep_completed_transcripts()

    feeds = load_feeds()
    print(f"\nFound {len(feeds)} podcast feeds")
    
    if not feeds:
        print(f"\nNo feeds found. Check {FEEDS_FILE}")
        return
    
    results = []
    
    for feed_url in feeds:
        print(f"\n📻 Processing: {feed_url[:50]}...")
        
        # Fetch latest episode
        episode = fetch_latest_episode(feed_url)
        if not episode:
            print("  ✗ No episode found")
            continue

        print(f"  📋 Latest: {episode['title'][:60]}...")

        # Download
        audio_path = download_episode(episode)
        if not audio_path:
            continue
        
        # Transcribe
        transcript_path = transcribe_episode(audio_path, episode)
        
        results.append({
            'podcast': episode['podcast'],
            'title': episode['title'],
            'audio_path': audio_path,
            'transcript_path': transcript_path,
            'success': transcript_path is not None
        })
    
    # Save log
    log_file = save_log(results)
    print(f"\n✓ Log saved: {log_file}")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total feeds: {len(feeds)}")
    print(f"Successfully transcribed: {sum(1 for r in results if r['success'])}")
    print(f"Failed: {sum(1 for r in results if not r['success'])}")
    
    print("\nCompleted episodes:")
    for r in results:
        if r['success']:
            print(f"  ✓ {r['podcast']}: {r['title'][:50]}...")
    
    print("\n\nNext step: Run 'python3 research.py' to analyze transcripts")

if __name__ == "__main__":
    main()
