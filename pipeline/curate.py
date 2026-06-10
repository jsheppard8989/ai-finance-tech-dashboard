#!/usr/bin/env python3
"""
Podcast curator - fetches RSS feeds and approves all episodes from the feed list.
Feed list (podcast_feeds.txt) is the relevance filter; we do not apply per-episode relevance scoring.
"""

import xml.etree.ElementTree as ET
import urllib.request
import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, date

from workspace_paths import AUDIO_DIR, DB_PATH, FEEDS_FILE, STATE_DIR, TRANSCRIPT_DIR

# Config
CURATION_LOG = STATE_DIR / "curation_log.json"
# Forward-looking: only consider episodes from the current calendar month (no backfill of prior months).
CURRENT_MONTH_ONLY = True
# Fallback max age when CURRENT_MONTH_ONLY is False (not used when current-month filter is on).
MAX_EPISODE_AGE_DAYS = 60

# Hard stop: do not approve or process anything before this date.
from cutoff_date import CUTOFF_DATE_ISO, is_before_cutoff

# Feed list is the relevance filter: only feeds in podcast_feeds.txt are used.
# We do not apply per-episode relevance scoring; if it's in the feed list, it's relevant.

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

def fetch_feed_metadata(feed_url, skip_if_in_db=True):
    """Fetch and parse RSS feed to get episode metadata.
    If skip_if_in_db=True (default), episodes already in podcast_episodes are omitted.
    Set skip_if_in_db=False to get all episodes (age/cutoff only) for Pipeline Health.
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
        
        episodes = []
        
        # Find all items (episodes)
        for item in root.findall('.//item'):
            title = ""
            description = ""
            enclosure_url = ""
            pub_date = ""
            
            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                title = title_elem.text
            
            desc_elem = item.find('description')
            if desc_elem is not None and desc_elem.text:
                description = desc_elem.text[:500]  # First 500 chars
            
            # Also check content:encoded if available
            content_elem = item.find('.//{http://purl.org/rss/1.0/modules/content/}encoded')
            if content_elem is not None and content_elem.text:
                description = content_elem.text[:500]
            
            enclosure = item.find('enclosure')
            if enclosure is not None:
                enclosure_url = enclosure.get('url', '')
            
            pub_elem = item.find('pubDate')
            if pub_elem is not None and pub_elem.text:
                pub_date = pub_elem.text
            
            if title and enclosure_url:
                # Parse pub date
                pub_date_iso = None
                if pub_date:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_date_iso = parsedate_to_datetime(pub_date).strftime('%Y-%m-%d')
                    except Exception:
                        pass

                if pub_date_iso:
                    if is_before_cutoff(pub_date_iso):
                        continue
                    # Forward-looking: only current calendar month (e.g. March only, leave out Feb).
                    if CURRENT_MONTH_ONLY:
                        today = date.today()
                        try:
                            ep_date = date.fromisoformat(pub_date_iso)
                            if (ep_date.year, ep_date.month) != (today.year, today.month):
                                continue
                        except Exception:
                            continue
                    else:
                        age_days = (date.today() - date.fromisoformat(pub_date_iso)).days
                        if age_days > MAX_EPISODE_AGE_DAYS:
                            continue

                guid_el = item.find('guid')
                rss_guid = guid_el.text.strip() if guid_el is not None and guid_el.text else ''
                if skip_if_in_db and rss_guid:
                    import sqlite3 as _sq

                    _c = _sq.connect(str(DB_PATH))
                    existing = _c.execute('SELECT id FROM podcast_episodes WHERE rss_guid=?', (rss_guid,)).fetchone()
                    _c.close()
                    if existing:
                        continue

                episodes.append({
                    'podcast': podcast_title,
                    'title': title,
                    'description': description,
                    'audio_url': enclosure_url,
                    'published': pub_date,
                    'published_date': pub_date_iso,
                    'rss_guid': rss_guid,
                })
        
        return {
            'podcast': podcast_title,
            'feed_url': feed_url,
            'episodes': episodes[:10]  # Last 10 episodes
        }
        
    except Exception as e:
        print(f"Error fetching {feed_url}: {e}")
        return None

def flatten_feed_episodes(all_episodes):
    """Flatten per-feed episode lists into one list (so we can curate all, not only those with audio)."""
    flat = []
    for podcast in all_episodes:
        for ep in podcast.get('episodes', []):
            flat.append(ep)
    return flat


def get_feed_episodes_not_in_db():
    """
    Return episodes that are live on RSS (within age/cutoff) but not yet in podcast_episodes.
    Used by Pipeline Health to show "Available from RSS (not yet processed)".
    Uses same feed list and age/cutoff as curation; does not filter by keywords.
    """
    import sqlite3
    feeds = load_feeds()
    if not feeds:
        return []
    all_episodes = []
    for feed_url in feeds:
        metadata = fetch_feed_metadata(feed_url, skip_if_in_db=False)
        if metadata and metadata.get('episodes'):
            all_episodes.extend(metadata['episodes'])
    if not all_episodes:
        return []
    # Single DB check: all rss_guids we have
    db_path = DB_PATH
    if not db_path.exists():
        return [{"podcast": e["podcast"], "title": e["title"], "published": e.get("published", ""), "published_date": e.get("published_date")} for e in all_episodes]
    conn = sqlite3.connect(str(db_path))
    guids_in_db = set(row[0] for row in conn.execute("SELECT rss_guid FROM podcast_episodes WHERE rss_guid IS NOT NULL AND rss_guid != ''").fetchall())
    conn.close()
    out = []
    for e in all_episodes:
        guid = (e.get("rss_guid") or "").strip()
        if guid and guid in guids_in_db:
            continue
        out.append({
            "podcast": e.get("podcast", ""),
            "title": e.get("title", ""),
            "published": e.get("published", ""),
            "published_date": e.get("published_date"),
        })
    # Sort by published_date desc
    def pub_key(ep):
        d = ep.get("published_date") or ""
        if len(d) >= 10:
            return (d[:4], d[5:7], d[8:10])
        return ("0", "0", "0")
    out.sort(key=pub_key, reverse=True)
    return out


def match_audio_to_feed_episodes(all_feed_episodes):
    """
    Attach matching audio files to feed episodes where we have a download.
    Returns (all_feed_episodes, unmatched_audio_count).
    Episodes without a match keep no audio_file — they can still be approved (pending download).
    """
    audio_files = list(AUDIO_DIR.glob("*.mp3"))
    used_audio = set()

    for ep in all_feed_episodes:
        audio_url = ep.get('audio_url', '')
        ep.pop('audio_file', None)
        ep.pop('filename', None)
        for audio_file in audio_files:
            if str(audio_file) in used_audio:
                continue
            filename = audio_file.stem
            if filename in audio_url or filename.replace('%', '') in audio_url:
                ep['audio_file'] = str(audio_file)
                ep['filename'] = audio_file.name
                used_audio.add(str(audio_file))
                break
            if 'megaphone.fm' in audio_url:
                megaphone_id = (audio_url.split('/')[-1].split('.')[0] if audio_url else '')
                if megaphone_id and megaphone_id in filename:
                    ep['audio_file'] = str(audio_file)
                    ep['filename'] = audio_file.name
                    used_audio.add(str(audio_file))
                    break

    unmatched_count = len(audio_files) - len(used_audio)
    return all_feed_episodes, unmatched_count

def curate_episodes(matched_episodes):
    """Approve all episodes from the feed list. Feed list is the filter; no per-episode relevance score."""
    curated = []
    for ep in matched_episodes:
        ep['status'] = 'APPROVED'
        ep['matched_keywords'] = []
        curated.append(ep)
    return matched_episodes, curated


def download_audio_for_approved(episodes):
    """
    Download audio for approved episodes that don't yet have an audio_file.
    Feed list + current-month window decide relevance; this just ensures we
    attempt a download once we know about the episode.
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for ep in episodes:
        if ep.get('audio_file'):
            continue
        audio_url = ep.get('audio_url') or ''
        if not audio_url:
            continue

        safe_podcast = ''.join(c if c.isalnum() else '_' for c in (ep.get('podcast') or '').lower())[:40]
        safe_title = ''.join(c if c.isalnum() else '_' for c in (ep.get('title') or '').lower())[:60]
        h = hashlib.md5(audio_url.encode('utf-8')).hexdigest()[:8]
        filename = f"{safe_podcast}_{safe_title}_{h}.mp3"
        path = AUDIO_DIR / filename

        # If file already exists, just wire it up.
        if path.exists():
            ep['audio_file'] = str(path)
            ep['filename'] = filename
            continue

        try:
            print(f"  ↓ Downloading audio: {ep.get('podcast','')[:40]} – {ep.get('title','')[:60]}")
            # Some podcast hosts reject requests that look like "anonymous" (no UA).
            # Adding a conservative User-Agent keeps other downloads working.
            req = urllib.request.Request(
                audio_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp, open(path, 'wb') as out:
                shutil.copyfileobj(resp, out)
            ep['audio_file'] = str(path)
            ep['filename'] = filename
            downloaded += 1
        except Exception as e:
            print(f"  ⚠ Failed to download audio for '{ep.get('title','')[:60]}': {e}")

    print(f"  ✓ Downloaded audio for {downloaded} approved episode(s)")
    return episodes

def save_curation_log(all_episodes, curated):
    """Save curation log for reference."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_data = {
        'timestamp': datetime.now().isoformat(),
        'total_feed_episodes': len(all_episodes),
        'approved_for_transcription': len(curated),
        'episodes': all_episodes
    }
    
    with open(CURATION_LOG, 'w') as f:
        json.dump(log_data, f, indent=2)
    
    return CURATION_LOG

def main():
    print("=" * 70)
    print("Podcast Curation System")
    print("=" * 70)
    
    # Load feeds
    feeds = load_feeds()
    print(f"\nFound {len(feeds)} podcast feeds")
    
    if not feeds:
        print(f"\nNo feeds found. Create {FEEDS_FILE}")
        print("Add one feed URL per line")
        return
    
    # Fetch metadata from all feeds
    print("\nFetching episode metadata...")
    all_episodes = []
    
    for feed_url in feeds:
        print(f"  Fetching: {feed_url[:60]}...")
        metadata = fetch_feed_metadata(feed_url)
        if metadata:
            print(f"    ✓ {metadata['podcast']}: {len(metadata['episodes'])} episodes")
            all_episodes.append(metadata)
        else:
            print(f"    ✗ Failed")
    
    if not all_episodes:
        print("\nNo episodes fetched. Check feed URLs.")
        return
    
    # Flatten so we curate all feed episodes (not only those that already have audio)
    all_feed_episodes = flatten_feed_episodes(all_episodes)
    if CURRENT_MONTH_ONLY:
        from datetime import date
        today = date.today()
        print(f"\n  Total feed episodes (current month only: {today.year}-{today.month:02d}): {len(all_feed_episodes)}")
    else:
        print(f"\n  Total feed episodes (last {MAX_EPISODE_AGE_DAYS} days): {len(all_feed_episodes)}")

    # Attach audio file to episodes where we have a matching download
    print("\nMatching audio files to episodes...")
    all_feed_episodes, unmatched_audio_count = match_audio_to_feed_episodes(all_feed_episodes)
    with_audio = sum(1 for ep in all_feed_episodes if ep.get('audio_file'))
    print(f"  ✓ Episodes with matching audio: {with_audio}")
    print(f"  ? Unmatched audio files (no matching feed episode): {unmatched_audio_count}")
    print(f"  📥 Episodes pending download before auto-download: {len(all_feed_episodes) - with_audio}")

    # Feed list is the filter; all episodes from feeds are approved (no per-episode relevance score).
    print("\nApproving all episodes from feed list (feeds are pre-curated)...")
    all_matched, curated = curate_episodes(all_feed_episodes)

    # Auto-download any approved episodes that don't yet have audio.
    curated = download_audio_for_approved(curated)
    with_audio_after = sum(1 for ep in curated if ep.get('audio_file'))

    print(f"\n  APPROVED (will transcribe or download): {len(curated)}")
    print(f"  🎧 Approved episodes with audio after auto-download: {with_audio_after}")
    
    # Display results
    print("\n" + "=" * 70)
    print("CURATION RESULTS")
    print("=" * 70)
    
    print("\n📌 APPROVED (will transcribe or download):")
    for ep in curated:
        has_audio = ep.get('filename') or ep.get('audio_file')
        print(f"\n  ✓ {ep['podcast']}")
        print(f"    Title: {ep['title'][:70]}")
        print(f"    File: {ep['filename'] if has_audio else '(pending download)'}")
    
    # Save log (all feed episodes with status; pipeline shows APPROVED ones)
    log_file = save_curation_log(all_matched, curated)
    print(f"\n\n✓ Curation log saved: {log_file}")
    
    # Summary
    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print(f"\n1. Review approved episodes above")
    print(f"2. To transcribe approved episodes, run:")
    print(f"   python3 transcribe_curated.py")
    print(f"\n3. Or manually transcribe specific files (only for episodes that have audio):")
    for ep in curated:
        if ep.get('filename'):
            print(f"   whisper '{ep['filename']}' --model tiny --language en")

if __name__ == "__main__":
    main()
