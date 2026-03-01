import queue
import urllib.request
import xml.etree.ElementTree as ET
import time
import json
import subprocess

# Configurations
FEEDS_FILE = '/Users/jaredsheppard/.openclaw/workspace/podcast_feeds.txt'
LOG_FILE = '/Users/jaredsheppard/.openclaw/workspace/transcription_log.json'

# Initialize the queue
transcription_queue = queue.Queue()

def load_feeds():
    """Load podcast feed URLs from file."""
    feeds = []
    with open(FEEDS_FILE, 'r') as f:
        feeds = [line.strip() for line in f if line.startswith('http')]
    return feeds

def fetch_latest_episode(feed_url):
    """Fetch the most recent episode from an RSS feed."""
    try:
        response = urllib.request.urlopen(feed_url)
        xml_content = response.read()
        root = ET.fromstring(xml_content)
        item = root.find('.//item')
        if item is not None:
            title = item.find('title').text
            audio_url = item.find('enclosure').get('url')
            return {'title': title, 'audio_url': audio_url}
    except Exception as e:
        print(f'Error fetching {feed_url}: {e}') 
    return None

def transcribe_episode(episode):
    """Transcription using Whisper or equivalent service."""
    print(f'Transcribing: {episode["title"]}')
    # Actual transcription logic (placeholder)
    time.sleep(2)  # Simulate processing time for actual transcription
    return True

def process_queue():
    while not transcription_queue.empty():
        episode = transcription_queue.get()
        success = transcribe_episode(episode)
        log_entry = {
            'title': episode['title'],
            'success': success,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(LOG_FILE, 'a') as log_file:
            log_file.write(json.dumps(log_entry) + '\n')

# Load feeds and add to queue
feeds = load_feeds()
for feed in feeds:
    episode = fetch_latest_episode(feed)
    if episode:
        transcription_queue.put(episode)

# Start processing the queue
process_queue()
