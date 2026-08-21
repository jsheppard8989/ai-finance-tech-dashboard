"""Load active and on-hold podcast RSS feed URLs from workspace files."""

from workspace_paths import FEEDS_FILE, FEEDS_ON_HOLD_FILE


def _read_feed_urls(path) -> list[str]:
    urls: list[str] = []
    if not path.exists():
        return urls
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("http"):
                urls.append(line)
    return urls


def load_active_feeds() -> list[str]:
    """Feeds in podcast_feeds.txt — fetched, curated, and transcribed."""
    return _read_feed_urls(FEEDS_FILE)


def load_on_hold_feeds() -> list[str]:
    """Feeds in podcast_feeds_on_hold.txt — skipped by pipeline."""
    return _read_feed_urls(FEEDS_ON_HOLD_FILE)
