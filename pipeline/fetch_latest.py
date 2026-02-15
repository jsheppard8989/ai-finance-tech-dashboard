#!/usr/bin/env python3
"""
Fetch and transcribe latest podcast episodes.
Run this to get the most recent episode from each feed.
"""

import xml.etree.ElementTree as ET
import urllib.request
import subprocess
import json
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

def fetch_latest_episode(feed_url):
    """Fetch the most recent episode from an RSS feed."""
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
        pub_date = ""
        
        title_elem = item.find('title')
        if title_elem is not None and title_elem.text:
            title = title_elem.text
        
        enclosure = item.find('enclosure')
        if enclosure is not None:
            enclosure_url = enclosure.get('url', '')
        
        pub_elem = item.find('pubDate')
        if pub_elem is not None and pub_elem.text:
            pub_date = pub_elem.text
        
        if title and enclosure_url:
            return {
                'podcast': podcast_title,
                'title': title,
                'audio_url': enclosure_url,
                'published': pub_date,
                'feed': feed_url
            }
        
        return None
        
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

def transcribe_episode(audio_path, episode):
    """Transcribe the audio file using Whisper."""
    import os
    
    audio_file = Path(audio_path)
    transcript_file = TRANSCRIPT_DIR / f"{audio_file.stem}.txt"
    
    # Skip if already transcribed
    if transcript_file.exists():
        print(f"  ✓ Already transcribed: {transcript_file.name}")
        return str(transcript_file)
    
    print(f"  🎙️  Transcribing: {audio_file.name}")
    print(f"     This may take 30-60 minutes depending on length...")
    
    try:
        # Set PATH to include whisper
        env = os.environ.copy()
        env['PATH'] = '/Library/Frameworks/Python.framework/Versions/3.9/bin:' + env.get('PATH', '')
        
        result = subprocess.run(
            ['whisper', str(audio_path), '--model', 'tiny', '--language', 'en', 
             '--output_format', 'txt', '--output_dir', str(TRANSCRIPT_DIR)],
            capture_output=True,
            text=True,
            env=env,
            timeout=7200  # 2 hour timeout
        )
        
        if result.returncode == 0:
            print(f"     ✓ Transcription complete: {transcript_file.name}")
            return str(transcript_file)
        else:
            print(f"     ✗ Transcription failed: {result.stderr[:200]}")
            return None
            
    except subprocess.TimeoutExpired:
        print(f"     ✗ Transcription timed out (2 hours)")
        return None
    except Exception as e:
        print(f"     ✗ Error: {e}")
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
