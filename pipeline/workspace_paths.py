"""
Repo workspace layout (default: repo root containing pipeline/ + site/).
Override directory with WORKSPACE_ROOT (absolute path recommended).
"""

import os
from pathlib import Path
from typing import Optional

_PIPELINE_DIR = Path(__file__).resolve().parent


def workspace_root() -> Path:
    override = os.environ.get("WORKSPACE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _PIPELINE_DIR.parent.resolve()


_WS = workspace_root()
WORKSPACE_ROOT = _WS
PIPELINE_DIR = _WS / "pipeline"
SITE_DIR = _WS / "site"
SITE_DATA_DIR = SITE_DIR / "data"
SITE_CHARTS_DIR = SITE_DIR / "charts"
DB_PATH = PIPELINE_DIR / "dashboard.db"
AUDIO_DIR = _WS / "audio"
PIPELINE_AUDIO_DIR = PIPELINE_DIR / "audio"
WHISPER_QUEUE_DIR = _WS / "whisper_queue"
WHISPER_DONE_DIR = _WS / "whisper_done"
TRANSCRIPT_DIR = PIPELINE_DIR / "transcripts"
STATE_DIR = PIPELINE_DIR / "state"
INBOX_DIR = PIPELINE_DIR / "inbox"
# Newsletter JSON + transcript .processed markers share this directory historically
NEWSLETTER_PROCESSED_DIR = PIPELINE_DIR / "processed"
PROCESSING_MARKER_DIR = NEWSLETTER_PROCESSED_DIR
FEEDS_FILE = _WS / "podcast_feeds.txt"
TRANSCRIPTION_LOG_JSON = _WS / "transcription_log.json"


def agent_auth_profiles_path() -> Optional[Path]:
    """Optional OpenAI-compatible auth snippet path (set CURSOR_AGENT_AUTH_PROFILES_PATH)."""
    raw = os.environ.get("CURSOR_AGENT_AUTH_PROFILES_PATH", "").strip()
    return Path(raw).expanduser().resolve() if raw else None
