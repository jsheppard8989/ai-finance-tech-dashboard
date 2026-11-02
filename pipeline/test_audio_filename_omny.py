"""Regression: generic audio URL stems (Omny/Podtrac .../<uuid>/audio.mp3) must not collide."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_latest import episode_audio_filename  # noqa: E402


def _ep(url, guid, date="2026-10-30"):
    return {"audio_url": url, "rss_guid": guid, "published_date": date,
            "podcast": "Credit Edge", "title": "t " + guid}


def test_two_omny_urls_get_different_filenames():
    a = _ep("https://traffic.omny.fm/d/clips/aaa/bbb/11111111-1111-1111-1111-111111111111/audio.mp3?utm=x", "guid-one")
    b = _ep("https://traffic.omny.fm/d/clips/aaa/bbb/22222222-2222-2222-2222-222222222222/audio.mp3?utm=x", "guid-two")
    fa, fb = episode_audio_filename(a), episode_audio_filename(b)
    assert fa != fb
    assert fa != "audio.mp3" and fb != "audio.mp3"


def test_podtrac_generic_audio_stem_uniquified():
    a = _ep("https://www.podtrac.com/pts/redirect.mp3/x/11/audio.mp3", "g1")
    b = _ep("https://www.podtrac.com/pts/redirect.mp3/x/22/audio.mp3", "g2")
    assert episode_audio_filename(a) != episode_audio_filename(b)


def test_specific_stem_unchanged():
    e = _ep("https://dts.podtrac.com/redirect.mp3/x/ABC123XYZ.mp3", "g")
    assert episode_audio_filename(e) == "ABC123XYZ.mp3"
