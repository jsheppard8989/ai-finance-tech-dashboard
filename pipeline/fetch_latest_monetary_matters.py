import queue
import urllib.request
import xml.etree.ElementTree as ET
import time
import json

# Configurations
FEED_URL = 'https://feeds.megaphone.fm/DVVTS2890392624'
LOG_FILE = '/Users/jaredsheppard/.openclaw/workspace/transcription_log.json'

# Initialize the queue
transcription_queue = queue.Queue()

# Load the specific feed
transcription_queue.put(FEED_URL)

def fetch_latest_episode(feed_url):
    """Fetch the most recent episode from the RSS feed."""
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
    """Dummy transcription function to simulate a real transcription."""
    print(f'Transcribing: {episode["title"]}')
    time.sleep(5)  # Simulate processing time for actual transcription
    return True

def process_queue():
    while not transcription_queue.empty():
        feed_url = transcription_queue.get()
        episode = fetch_latest_episode(feed_url)
        if episode:
            success = transcribe_episode(episode)
            log_entry = {
                'title': episode['title'],
                'success': success,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            with open(LOG_FILE, 'a') as log_file:
                log_file.write(json.dumps(log_entry) + '\n')

# Start processing the queue
process_queue()
