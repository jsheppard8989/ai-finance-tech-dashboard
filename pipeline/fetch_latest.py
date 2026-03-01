#!/usr/bin/env python3
"""
Fetch and transcribe latest podcast episodes.
Run this to get the most recent episode from each feed.
"""

import os
import xml.etree.ElementTree as ET
import urllib.request
import subprocess
import json
import shutil
from pathlib import Path
from datetime import datetime

# Config
AUDIO_DIR = Path.home() / ".openclaw/workspace/audio"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
FEEDS_FILE = Path.home() / ".openclaw/workspace/podcast_feeds.txt"
LOG_FILE = Path.home() / ".openclaw/workspace/pipeline/fetch_log.json"

AUDIO_DIR.mkdir(exist_ok=True)
TRANSCRIPT_DIR.mkdir(exist_ok=True)

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

def fetch_latest_episode(feed_url, max_age_days=2):
    """Fetch the most recent episode from an RSS feed.
    
    Returns None if the latest episode is older than max_age_days,
    or if its rss_guid already exists in the database.
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
        
        # Find first item (most recent episode)
        item = root.find('.//item')
        if item is None:
            return None
        
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
            return None

        # Parse published date
        pub_date_iso = None
        if pub_date_str:
            try:
                from email.utils import parsedate_to_datetime
                pub_date_iso = parsedate_to_datetime(pub_date_str).strftime('%Y-%m-%d')
            except Exception:
                pass

        # Gate: skip episodes older than max_age_days
        if pub_date_iso:
            from datetime import date
            pub = date.fromisoformat(pub_date_iso)
            age_days = (date.today() - pub).days
            if age_days > max_age_days:
                print(f"  ⏭ Skipping '{title[:50]}' — published {pub_date_iso} ({age_days}d ago, >{max_age_days}d limit)")
                return None

        # Gate: skip if rss_guid already in database
        if rss_guid:
            import sqlite3 as _sqlite3
            from pathlib import Path as _Path
            db_path = _Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
            _conn = _sqlite3.connect(str(db_path))
            existing = _conn.execute(
                "SELECT id FROM podcast_episodes WHERE rss_guid=?", (rss_guid,)
            ).fetchone()
            _conn.close()
            if existing:
                print(f"  ⏭ Already have '{title[:50]}' (guid match, ep_id={existing[0]})")
                return None

        return {
            'podcast': podcast_title,
            'title': title,
            'audio_url': enclosure_url,
            'published': pub_date_str,
            'published_date': pub_date_iso,
            'rss_guid': rss_guid,
            'feed': feed_url
        }

    except Exception as e:
        print(f"  ✗ Error fetching {feed_url}: {e}")
        return None

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
            with open(filepath, 'wb') as f:
                f.write(response.read())
        print(f"     ✓ Downloaded to {filepath}")
        return str(filepath)
    except Exception as e:
        print(f"     ✗ Download failed: {e}")
        return None

WHISPER_QUEUE_DIR = Path.home() / ".openclaw/workspace/whisper_queue"
WHISPER_DONE_DIR  = Path.home() / ".openclaw/workspace/whisper_done"


def sweep_completed_transcripts():
    """
    Sweep any completed transcripts from whisper_done into the pipeline transcripts dir.
    This makes the system resilient if a previous run timed out or was interrupted
    after Whisper finished but before the move occurred.
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

    if moved:
        print(f"  ✓ Swept {moved} completed transcript file(s) from whisper_done into transcripts")

def transcribe_via_launchagent(audio_path, episode, poll_interval=15, timeout_secs=3600):
    """
    Submit audio to the whisper LaunchAgent queue and poll for completion.
    The LaunchAgent runs outside the OpenClaw sandbox, avoiding OOM SIGKILL.
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
    """Transcribe: use openai-whisper local if USE_FASTER_WHISPER=1, else LaunchAgent queue."""
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
    
    with open(LOG_FILE, 'w') as f:
        json.dump(log_data, f, indent=2)
    
    return LOG_FILE

def main():
    print("=" * 70)
    print("Fetch & Transcribe Latest Podcast Episodes")
    print("=" * 70)

    # First, sweep any transcripts that Whisper finished after a previous run timed out.
    sweep_completed_transcripts()

    feeds = load_feeds()
    print(f"\nFound {len(feeds)} podcast feeds")
    
    if not feeds:
        print("\nNo feeds found. Check ~/.openclaw/workspace/podcast_feeds.txt")
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
