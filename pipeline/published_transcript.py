"""Use a publisher's full transcript when the show actually ships one.

Accept, in order:
  1. podcast:transcript (or a transcript enclosure) whose body is long enough
  2. RSS description / content:encoded that is the transcript, not show notes
  3. A Substack episode page whose publication RSS (/feed) content:encoded is the transcript

Anything shorter, or only chapter notes, returns None so the caller keeps Whisper.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from typing import Callable, Optional
from xml.etree import ElementTree as ET

_MIN_TRANSCRIPT_WORDS = 2500
_MIN_LABELED_WORDS = 800
_MAX_DOWNLOAD_BYTES = 8_000_000
_UA = "Mozilla/5.0"

_BLOCK_RE = re.compile(r"(?i)<br\s*/?>|</(p|div|h1|h2|h3|h4|li|tr|section|blockquote)>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b.*?>.*?</\1>")
_TAG_RE = re.compile(r"<[^>]+>")
_CLOCK_RE = re.compile(r"\[\d{1,2}:\d{2}:\d{2}\]")
_SPEAKER_STAMP_RE = re.compile(
    r"\b[A-Z][A-Za-z.'’\- ]{0,40}\s*[\[\(]\d{1,2}:\d{2}"
)
_TRANSCRIPT_TYPES = ("vtt", "srt", "subrip")


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    text = _SCRIPT_RE.sub(" ", raw)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _has_transcript_heading(text: str) -> bool:
    for line in text.splitlines():
        if line.strip().lower() in {"transcript", "full transcript", "episode transcript"}:
            return True
    return False


def is_full_transcript(text: str) -> bool:
    """True for a full spoken transcript. Chapter lists and show notes are false."""
    if not text:
        return False
    n = _word_count(text)
    if n < _MIN_TRANSCRIPT_WORDS:
        return False
    if len(_CLOCK_RE.findall(text)) >= 15 or len(_SPEAKER_STAMP_RE.findall(text)) >= 8:
        return True
    if _has_transcript_heading(text) and n >= 4000:
        return True
    return False


def _is_transcript_url(url: str, mime: str) -> bool:
    blob = f"{mime} {url}".lower()
    if any(kind in blob for kind in _TRANSCRIPT_TYPES):
        return True
    if "transcript" in blob and not blob.strip().endswith(".mp3"):
        return True
    return False


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def rss_item_transcript_hints(item: ET.Element) -> dict:
    """Pull transcript URLs and the longer HTML body off one RSS item."""
    urls: list[dict] = []
    bodies: list[str] = []
    link = ""
    for el in item.iter():
        name = _local(el.tag)
        if name == "link" and not link:
            link = (el.text or "").strip()
        elif name == "transcript":
            url = (el.attrib.get("url") or (el.text or "")).strip()
            if url.startswith("http"):
                urls.append({"url": url, "type": el.attrib.get("type") or ""})
        elif name == "enclosure":
            url = (el.attrib.get("url") or "").strip()
            mime = el.attrib.get("type") or ""
            if url.startswith("http") and _is_transcript_url(url, mime):
                urls.append({"url": url, "type": mime})
        elif name in ("encoded", "description"):
            raw = "".join(el.itertext()) or (el.text or "")
            if raw.strip():
                bodies.append(raw)
    body = max(bodies, key=len) if bodies else ""
    return {"link": link, "transcript_urls": urls, "rss_html": body}


def timed_text_to_plain(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.upper().startswith("WEBVTT") or s.upper().startswith("NOTE"):
            continue
        if "-->" in s or re.fullmatch(r"\d+", s):
            continue
        s = _TAG_RE.sub("", s)
        if s.strip():
            lines.append(s.strip())
    return "\n".join(lines)


def _from_json_transcript(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    segments = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segments, list):
        return ""
    parts = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        speaker = (seg.get("speaker") or "").strip()
        body = (seg.get("body") or seg.get("text") or "").strip()
        if not body:
            continue
        parts.append(f"{speaker}: {body}" if speaker else body)
    return "\n".join(parts)


def normalize_transcript_payload(raw: str, mime: str) -> str:
    blob = (mime or "").lower()
    sample = raw.lstrip()[:80].lower()
    if "json" in blob or sample.startswith("{") or sample.startswith("["):
        as_json = _from_json_transcript(raw)
        if as_json:
            return as_json
    if any(kind in blob for kind in _TRANSCRIPT_TYPES) or sample.startswith("webvtt") or "-->" in raw[:400]:
        return timed_text_to_plain(raw)
    return html_to_text(raw)


def _accept(text: str, *, labeled: bool) -> Optional[str]:
    text = (text or "").strip()
    if labeled:
        if _word_count(text) >= _MIN_LABELED_WORDS:
            return text
        return None
    if is_full_transcript(text):
        return text
    return None


def fetch_url_bytes(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(_MAX_DOWNLOAD_BYTES)


def _norm_link(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse((url or "").strip())
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def transcript_from_publication_feed(feed_xml: bytes, episode_link: str) -> Optional[str]:
    """Match a Substack (or similar) /feed item to the episode link."""
    wanted = _norm_link(episode_link)
    if not wanted:
        return None
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError:
        return None
    for item in root.findall(".//item"):
        link = ""
        for el in item:
            if _local(el.tag) == "link" and (el.text or "").strip():
                link = el.text.strip()
                break
        if _norm_link(link) != wanted:
            continue
        hints = rss_item_transcript_hints(item)
        return _accept(html_to_text(hints["rss_html"]), labeled=False)
    return None


def _substack_feed_url(episode_link: str) -> Optional[str]:
    from urllib.parse import urlparse

    parsed = urlparse((episode_link or "").strip())
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.netloc or not parsed.path.startswith("/p/"):
        return None
    return f"{parsed.scheme}://{parsed.netloc}/feed"


def resolve_published_transcript(
    episode: dict,
    fetch: Callable[[str], bytes] = fetch_url_bytes,
) -> Optional[str]:
    """Return full transcript text, or None to keep the Whisper path."""
    for hint in episode.get("transcript_urls") or []:
        url = (hint.get("url") or "").strip()
        if not url:
            continue
        try:
            payload = fetch(url).decode("utf-8", "replace")
        except Exception:
            continue
        text = _accept(normalize_transcript_payload(payload, hint.get("type") or ""), labeled=True)
        if text:
            return text

    inline = _accept(html_to_text(episode.get("rss_html") or ""), labeled=False)
    if inline:
        return inline

    feed_url = _substack_feed_url(episode.get("link") or "")
    if not feed_url:
        return None
    try:
        feed_xml = fetch(feed_url)
    except Exception:
        return None
    return transcript_from_publication_feed(feed_xml, episode.get("link") or "")


