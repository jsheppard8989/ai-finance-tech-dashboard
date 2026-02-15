#!/usr/bin/env python3
"""
Generate local RSS feeds for a list of Twitter handles using the Twitter API v2.

Dependencies:
    pip install python-dotenv tweepy feedgen

Usage:
    scripts/generate_twitter_rss.py
"""
import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
import tweepy
from feedgen.feed import FeedGenerator

# Load Twitter credentials from .env in workspace root
root = Path(__file__).parent.parent
load_dotenv(root / '.env')

BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN')
if not BEARER_TOKEN:
    print("Missing TWITTER_BEARER_TOKEN in .env", file=sys.stderr)
    exit(1)

# List of handles to generate feeds for
HANDLES = [
    'digiii', 'elonmusk', 'jackmallers', 'visserlabs', 'jam_croissant',
    'aixbt_agent', 'elizaOS', 'saylor', 'CaitlinLong_', 'Werkman',
    'LynAldenContact', 'krugermacro', 'JeffBooth', 'balajis',
    'bengreenfield', 'FZucchi', 'TenYearNote', 'SoberLook'
]

# Number of recent tweets to include
COUNT = 5

# Create output directory
out_dir = root / 'site' / 'feeds'
out_dir.mkdir(exist_ok=True)

# Initialize Twitter client
client = tweepy.Client(bearer_token=BEARER_TOKEN)

for handle in HANDLES:
    try:
        user = client.get_user(username=handle)
        uid = user.data.id
        tweets = client.get_users_tweets(
            id=uid,
            max_results=COUNT,
            tweet_fields=['created_at', 'text']
        )
    except Exception as e:
        print(f"Error fetching tweets for {handle}: {e}")
        continue

    fg = FeedGenerator()
    fg.id(f"https://twitter.com/{handle}")
    fg.title(f"Tweets by @{handle}")
    fg.link(href=f"https://twitter.com/{handle}", rel='alternate')
    fg.description(f"Latest {COUNT} tweets from @{handle}")
    fg.link(href=f"file://{out_dir / f'{handle}.rss'}", rel='self')
    fg.updated(datetime.now(timezone.utc))

    if tweets.data:
        for tweet in tweets.data:
            fe = fg.add_entry()
            fe.id(str(tweet.id))
            fe.title(tweet.text.replace('\n', ' ')[:64] + '...')
            fe.link(href=f"https://twitter.com/{handle}/status/{tweet.id}")
            fe.published(tweet.created_at)
    else:
        print(f"No tweets found for {handle}")

    rss_path = out_dir / f"{handle}.rss"
    fg.rss_file(rss_path)
    print(f"Generated feed for {handle}: {rss_path}")
