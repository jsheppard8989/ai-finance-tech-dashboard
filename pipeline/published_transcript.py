"""Use a publisher's full transcript when the show actually ships one.

Accept, in order:
  1. podcast:transcript (or a transcript enclosure) whose body is long enough
  2. RSS description / content:encoded that is the transcript, not show notes
  3. A Substack episode page whose publication RSS (/feed) content:encoded is the transcript
  4. Macro Voices only: Apify-rendered sitemap loc for the Podbean slug, then the
     episode page's /guest-content/list-guest-transcripts/{id}-.../file PDF text

Anything shorter, or only chapter notes, returns None so the caller keeps Whisper.
Macro Voices stays on Whisper when Apify is unset, the page is blocked, or the
PDF text is not a full dialogue.
"""

from __future__ import annotations

import html
import json
import os
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



_MACROVOICES_SITEMAP = (
    "https://www.macrovoices.com/index.php?option=com_jmap&view=sitemap&format=xml"
)
_APIFY_WEB_FETCH = (
    "https://api.apify.com/v2/acts/apify~web-fetch/run-sync-get-dataset-items?timeout=120"
)
_PAGE_FOR_SLUG_RE_TMPL = r"https://www\.macrovoices\.com/\d+-{slug}(?![A-Za-z0-9-])"
_FILE_RE = re.compile(
    r"(?:https://www\.macrovoices\.com)?/guest-content/list-guest-transcripts/\d+-[A-Za-z0-9-]+/file"
)
_ERIK_TURN_RE = re.compile(r"(?i)\berik:")


def _is_macrovoices(episode: dict) -> bool:
    feed = (episode.get("feed") or "").lower()
    link = (episode.get("link") or "").lower()
    return "feed.podbean.com/macrovoices/" in feed or "macrovoices.podbean.com/" in link


def _podbean_episode_slug(link: str) -> str:
    match = re.search(r"macrovoices\.podbean\.com/e/([^/?#]+)", link or "", re.I)
    return match.group(1).strip("/") if match else ""


def _apify_web_fetch(url: str, formats: list) -> list:
    """One Apify web-fetch call. No token, or any error, yields no records."""
    token = (os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN") or "").strip()
    if not token:
        return []
    payload = json.dumps({"url": url, "formats": formats}).encode()
    req = urllib.request.Request(
        _APIFY_WEB_FETCH,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=150) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return []


def _record_text(items: list) -> str:
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in ("text", "markdown"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


def _sitemap_page_for_slug(sitemap_text: str, slug: str) -> str:
    if not slug:
        return ""
    pattern = re.compile(_PAGE_FOR_SLUG_RE_TMPL.format(slug=re.escape(slug)), re.I)
    match = pattern.search(sitemap_text or "")
    return match.group(0) if match else ""


def _transcript_file_url(items: list) -> str:
    blobs = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in ("markdown", "text", "html"):
            val = item.get(key)
            if isinstance(val, str):
                blobs.append(val)
        links = item.get("links") or []
        if isinstance(links, list):
            blobs.extend(str(link) for link in links)
    match = _FILE_RE.search("\n".join(blobs))
    if not match:
        return ""
    url = match.group(0)
    if url.startswith("/"):
        return "https://www.macrovoices.com" + url
    return url


def _accept_macrovoices_pdf(text: str) -> Optional[str]:
    text = (text or "").strip()
    if not text or "one moment, please" in text.lower()[:400]:
        return None
    if _word_count(text) < _MIN_TRANSCRIPT_WORDS:
        return None
    if len(_ERIK_TURN_RE.findall(text)) < 5:
        return None
    return text


def _macrovoices_transcript(episode: dict, apify_fetch: Callable) -> Optional[str]:
    """PDF transcript for this show only. None keeps Whisper."""
    if not _is_macrovoices(episode):
        return None
    slug = _podbean_episode_slug(episode.get("link") or "")
    if not slug:
        return None
    try:
        sitemap_items = apify_fetch(_MACROVOICES_SITEMAP, ["text"])
        page = _sitemap_page_for_slug(_record_text(sitemap_items), slug)
        if not page:
            return None
        page_items = apify_fetch(page, ["markdown", "links"])
        file_url = _transcript_file_url(page_items)
        if not file_url:
            return None
        file_items = apify_fetch(file_url, ["text"])
    except Exception:
        return None
    return _accept_macrovoices_pdf(_record_text(file_items))


def resolve_published_transcript(
    episode: dict,
    fetch: Callable[[str], bytes] = fetch_url_bytes,
    apify_fetch: Callable = _apify_web_fetch,
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
        return _macrovoices_transcript(episode, apify_fetch)
    try:
        feed_xml = fetch(feed_url)
    except Exception:
        return None
    return transcript_from_publication_feed(feed_xml, episode.get("link") or "")


