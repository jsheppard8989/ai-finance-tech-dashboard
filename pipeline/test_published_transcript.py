"""Published-transcript detection. No network."""

import json
from xml.etree import ElementTree as ET

from published_transcript import (
    html_to_text,
    is_full_transcript,
    normalize_transcript_payload,
    resolve_published_transcript,
    rss_item_transcript_hints,
    transcript_from_publication_feed,
)


def _words(n, extra=""):
    return ("word " * n) + extra


def test_show_notes_are_not_a_transcript():
    notes = "<p>(0:00) Guest intro</p><p>(6:10) Topic two</p><p>Read the transcript.</p>"
    assert not is_full_transcript(html_to_text(notes))
    assert resolve_published_transcript({"rss_html": notes, "link": "https://example.com/ep"}) is None


def test_clock_stamped_body_is_a_transcript():
    body = _words(3000) + " ".join(f"Host [{i:02d}:00:00]: line" for i in range(20))
    assert is_full_transcript(body)


def test_heading_plus_length_is_a_transcript():
    body = "Intro blurb\n\nTranscript\n\n" + _words(4500)
    assert is_full_transcript(body)
    # The word alone, inside a short blurb, is not enough.
    assert not is_full_transcript("See the transcript.\n" + _words(100))


def test_podcast_transcript_tag_and_vtt(monkeypatch):
    xml = """<item>
      <link>https://example.com/ep</link>
      <description><![CDATA[<p>Short show notes only.</p>]]></description>
      <podcast:transcript xmlns:podcast="https://podcastindex.org/namespace/1.0"
        url="https://cdn.example.com/ep.vtt" type="text/vtt"/>
    </item>"""
    hints = rss_item_transcript_hints(ET.fromstring(xml))
    assert hints["transcript_urls"][0]["url"].endswith(".vtt")
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n" + " ".join(["spoken"] * 900)
    episode = {
        "link": hints["link"],
        "rss_html": hints["rss_html"],
        "transcript_urls": hints["transcript_urls"],
    }
    text = resolve_published_transcript(episode, fetch=lambda url: vtt.encode())
    assert text and text.startswith("spoken")
    assert "-->" not in text


def test_short_labeled_caption_is_rejected():
    assert normalize_transcript_payload("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi", "text/vtt") == "Hi"
    episode = {"transcript_urls": [{"url": "https://cdn.example.com/a.vtt", "type": "text/vtt"}], "rss_html": ""}
    assert resolve_published_transcript(episode, fetch=lambda url: b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi") is None


def test_substack_feed_match_skips_other_posts():
    long_body = "<h2>Transcript</h2><p>" + ("alpha " * 4500) + "</p>"
    feed = f"""<?xml version="1.0"?>
    <rss><channel>
      <item><link>https://show.example/p/other</link>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[<p>nope</p>]]></content:encoded>
      </item>
      <item><link>https://show.example/p/this-one?utm=rss</link>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[{long_body}]]></content:encoded>
      </item>
    </channel></rss>"""
    got = transcript_from_publication_feed(feed.encode(), "https://show.example/p/this-one")
    assert got and "alpha" in got and "nope" not in got
    episode = {
        "link": "https://show.example/p/this-one",
        "rss_html": "<p>New episode. Watch on YouTube.</p>",
        "transcript_urls": [],
    }
    text = resolve_published_transcript(episode, fetch=lambda url: feed.encode())
    assert text and "alpha" in text


def test_json_segments_count_as_labeled_transcript():
    payload = json.dumps({"segments": [{"speaker": "Host", "body": "word " * 900}]})
    plain = normalize_transcript_payload(payload, "application/json")
    assert plain.startswith("Host:")
    episode = {"transcript_urls": [{"url": "https://cdn.example.com/t.json", "type": "application/json"}]}
    assert resolve_published_transcript(episode, fetch=lambda url: payload.encode())


def _macrovoices_episode(slug):
    return {
        "feed": "https://feed.podbean.com/macrovoices/feed.xml",
        "link": f"https://macrovoices.podbean.com/e/{slug}/",
        "rss_html": "<p>Short show notes. Not a transcript.</p>",
        "transcript_urls": [],
    }


def test_macrovoices_pdf_from_apify_is_used():
    slug = "macrovoices-551-michael-every-decoding-the-global-geopolitical-puzzle-part-2"
    page = f"https://www.macrovoices.com/1552-{slug}"
    file_url = (
        "https://www.macrovoices.com/guest-content/list-guest-transcripts/"
        "6225-transcript-of-the-podcast-interview-between-erik-townsend-and-michael-every-part-2/file"
    )
    body = ("Erik: line\n" * 8) + ("word " * 2600)
    calls = []

    def apify(url, formats):
        calls.append(url)
        if url.endswith("format=xml"):
            other = "https://www.macrovoices.com/10-macrovoices-550-someone-else"
            prefixed = f"https://www.macrovoices.com/9-{slug}-extra"
            return [{"text": f"{other}\n{prefixed}\n{page}\n"}]
        if url == page:
            return [{"markdown": f"Download the podcast transcript: {file_url}", "links": [file_url]}]
        if url == file_url:
            return [{"text": body}]
        raise AssertionError(url)

    def fetch(_url):
        raise AssertionError("plain http")

    text = resolve_published_transcript(_macrovoices_episode(slug), fetch=fetch, apify_fetch=apify)
    assert text and text.startswith("Erik:")
    assert calls == [
        "https://www.macrovoices.com/index.php?option=com_jmap&view=sitemap&format=xml",
        page,
        file_url,
    ]


def test_macrovoices_slug_does_not_match_a_longer_url():
    short = "macrovoices-551-michael-every-decoding-the-global-geopolitical-puzzle"
    longer = short + "-part-2"
    page = f"https://www.macrovoices.com/1552-{longer}"

    def apify(url, formats):
        if url.endswith("format=xml"):
            return [{"text": page}]
        raise AssertionError("should not fetch a page for the other slug")

    assert resolve_published_transcript(_macrovoices_episode(short), apify_fetch=apify) is None


def test_macrovoices_wall_or_show_notes_stay_on_whisper():
    slug = "macrovoices-551-michael-every-decoding-the-global-geopolitical-puzzle-part-2"
    page = f"https://www.macrovoices.com/1552-{slug}"
    file_url = "https://www.macrovoices.com/guest-content/list-guest-transcripts/6225-example/file"

    def apify(url, formats):
        if url.endswith("format=xml"):
            return [{"text": page}]
        if url == page:
            return [{"links": [file_url]}]
        return [{"text": "One moment, please… " + ("word " * 100)}]

    assert resolve_published_transcript(_macrovoices_episode(slug), apify_fetch=apify) is None


def test_other_shows_do_not_call_apify():
    def apify(url, formats):
        raise AssertionError(url)

    episode = {
        "feed": "https://feeds.megaphone.fm/DVVTS2890392624",
        "link": "https://example.com/ep",
        "rss_html": "<p>Show notes only.</p>",
        "transcript_urls": [],
    }
    assert resolve_published_transcript(episode, apify_fetch=apify) is None
