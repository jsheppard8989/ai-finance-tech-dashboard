#!/usr/bin/env python3
"""
Smart podcast curator - fetches RSS feeds, checks episode titles/descriptions,
only transcribes investment-relevant content.
"""

import xml.etree.ElementTree as ET
import urllib.request
import json
from pathlib import Path
from datetime import datetime

# Config
AUDIO_DIR = Path.home() / ".openclaw/workspace/audio"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
FEEDS_FILE = Path.home() / ".openclaw/workspace/podcast_feeds.txt"
CURATION_LOG = Path.home() / ".openclaw/workspace/pipeline/curation_log.json"

# Investment-related keywords to look for
INVESTMENT_KEYWORDS = [
    'invest', 'stock', 'market', 'trading', 'portfolio', 'equity', 'equities',
    'finance', 'financial', 'earnings', 'revenue', 'profit', 'valuation',
    'bull', 'bear', 'rally', 'crash', 'correction',
    'fed', 'interest rate', 'inflation', 'recession',
    'ipo', 'merger', 'acquisition', 'buyout',
    'crypto', 'bitcoin', 'btc', 'blockchain', 'satoshi', 'lightning network',
    'altcoin', 'ethereum', 'eth', 'defi', 'web3', 'digital asset',
    'ai', 'artificial intelligence', 'machine learning',
    'semiconductor', 'chip', 'nvidia', 'amd', 'intel',
    'tech', 'technology', 'startup', 'venture',
    'analysis', 'research', 'outlook', 'forecast'
]

# Explicitly EXCLUDE keywords (to avoid food waste, lifestyle, etc.)
EXCLUDE_KEYWORDS = [
    'food waste', 'culinary', 'cooking', 'recipe', 'chef',
    'meditation', 'mindfulness', 'yoga', 'wellness',
    'dating', 'relationship', 'parenting',
    'sports', 'football', 'basketball', 'baseball'
]

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

def fetch_feed_metadata(feed_url):
    """Fetch and parse RSS feed to get episode metadata."""
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

                # Skip episodes older than 2 days
                if pub_date_iso:
                    from datetime import date
                    age_days = (date.today() - date.fromisoformat(pub_date_iso)).days
                    if age_days > 2:
                        continue

                # Skip if rss_guid already in DB
                guid_el = item.find('guid')
                rss_guid = guid_el.text.strip() if guid_el is not None and guid_el.text else ''
                if rss_guid:
                    import sqlite3 as _sq
                    from pathlib import Path as _P
                    _c = _sq.connect(str(_P.home() / '.openclaw/workspace/pipeline/dashboard.db'))
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

def score_episode_relevance(episode):
    """Score how relevant an episode is to investing."""
    full_text = f"{episode['title']} {episode['description']}".lower()
    
    # Check for exclusion keywords first
    for keyword in EXCLUDE_KEYWORDS:
        if keyword in full_text:
            return -1  # Exclude this episode
    
    # Count investment keywords
    score = 0
    matched_keywords = []
    
    for keyword in INVESTMENT_KEYWORDS:
        if keyword in full_text:
            score += 1
            matched_keywords.append(keyword)
    
    return score, matched_keywords

def match_audio_files_to_episodes(all_episodes):
    """Match downloaded audio files to their episode metadata."""
    audio_files = list(AUDIO_DIR.glob("*.mp3"))
    
    matched = []
    unmatched = []
    
    for audio_file in audio_files:
        # Extract filename (remove extension)
        filename = audio_file.stem
        
        # Try to match to an episode URL
        matched_episode = None
        
        for podcast in all_episodes:
            for ep in podcast.get('episodes', []):
                audio_url = ep.get('audio_url', '')
                
                # Match by filename in URL
                if filename in audio_url or filename.replace('%', '') in audio_url:
                    matched_episode = ep
                    matched_episode['audio_file'] = str(audio_file)
                    matched_episode['filename'] = audio_file.name
                    break
                
                # For megaphone files, try matching by ID
                if 'megaphone.fm' in audio_url:
                    megaphone_id = audio_url.split('/')[-1].split('.')[0]
                    if megaphone_id in filename:
                        matched_episode = ep
                        matched_episode['audio_file'] = str(audio_file)
                        matched_episode['filename'] = audio_file.name
                        break
            
            if matched_episode:
                break
        
        if matched_episode:
            matched.append(matched_episode)
        else:
            unmatched.append({
                'filename': audio_file.name,
                'path': str(audio_file)
            })
    
    return matched, unmatched

def curate_episodes(matched_episodes):
    """Curate episodes - only keep investment-relevant ones."""
    curated = []
    
    for ep in matched_episodes:
        score_result = score_episode_relevance(ep)
        
        if score_result == -1:
            # Explicitly excluded
            ep['relevance_score'] = -1
            ep['status'] = 'EXCLUDED'
            ep['matched_keywords'] = []
        elif isinstance(score_result, tuple):
            score, keywords = score_result
            ep['relevance_score'] = score
            ep['matched_keywords'] = keywords
            
            if score >= 2:  # Threshold for relevance
                ep['status'] = 'APPROVED'
                curated.append(ep)
            else:
                ep['status'] = 'SKIPPED (low relevance)'
        else:
            ep['relevance_score'] = 0
            ep['status'] = 'SKIPPED (no match)'
            ep['matched_keywords'] = []
    
    return matched_episodes, curated

def save_curation_log(all_episodes, curated):
    """Save curation log for reference."""
    log_data = {
        'timestamp': datetime.now().isoformat(),
        'total_audio_files': len(all_episodes),
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
        print("\nNo feeds found. Create ~/.openclaw/workspace/podcast_feeds.txt")
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
    
    # Match to downloaded audio files
    print("\nMatching audio files to episodes...")
    matched, unmatched = match_audio_files_to_episodes(all_episodes)
    
    print(f"  ✓ Matched: {len(matched)} files")
    print(f"  ? Unmatched: {len(unmatched)} files")
    
    # Curate episodes
    print("\nCurating episodes for investment relevance...")
    all_matched, curated = curate_episodes(matched)
    
    print(f"\n  APPROVED for transcription: {len(curated)}")
    print(f"  SKIPPED/EXCLUDED: {len(all_matched) - len(curated)}")
    
    # Display results
    print("\n" + "=" * 70)
    print("CURATION RESULTS")
    print("=" * 70)
    
    print("\n📌 APPROVED (will transcribe):")
    for ep in curated:
        print(f"\n  ✓ {ep['podcast']}")
        print(f"    Title: {ep['title'][:70]}")
        print(f"    Keywords: {', '.join(ep['matched_keywords'][:5])}")
        print(f"    File: {ep['filename']}")
    
    print("\n" + "-" * 70)
    print("\n📋 REVIEW ALL:")
    for ep in all_matched:
        status_icon = "✓" if ep['status'] == 'APPROVED' else "✗"
        print(f"\n  {status_icon} [{ep['status']}] {ep['podcast']}")
        print(f"    Title: {ep['title'][:60]}")
        if ep['matched_keywords']:
            print(f"    Keywords: {', '.join(ep['matched_keywords'][:5])}")
    
    # Save log
    log_file = save_curation_log(all_matched, curated)
    print(f"\n\n✓ Curation log saved: {log_file}")
    
    # Summary
    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print(f"\n1. Review approved episodes above")
    print(f"2. To transcribe approved episodes, run:")
    print(f"   python3 transcribe_curated.py")
    print(f"\n3. Or manually transcribe specific files:")
    for ep in curated:
        print(f"   whisper '{ep['filename']}' --model tiny --language en")

if __name__ == "__main__":
    main()
