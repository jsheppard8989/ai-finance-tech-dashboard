#!/usr/bin/env python3
"""
Fetch and parse public article pages from https://grokipedia.com (the website),
not the xAI Grok API.

Used to build structured pundit profiles for the dashboard. Parsing relies on
the current Grokipedia HTML layout (main > article > aside infobox + article body).
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

try:
    import requests
except ImportError:
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

GROKIPEDIA_ORIGIN = "https://grokipedia.com"
USER_AGENT = "ScarcityAbundanceDashboard/1.0 (private dashboard; respectful crawl; contact via site)"

_REQUEST_DELAY_SEC = 1.25


def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = " ".join(s.split())
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return s.strip()


def _name_tokens(name: str) -> List[str]:
    raw = re.sub(r"[^a-zA-Z\s\-']", " ", (name or "").lower())
    parts = [p.strip("'-") for p in raw.split() if len(p.strip("'-")) >= 2]
    return parts


def _slug_variants(name: str) -> List[str]:
    """Grokipedia slugs look like First_Last or First_Middle_Last."""
    tokens = re.sub(r"[^a-zA-Z\s]", "", (name or "").strip()).split()
    if not tokens:
        return []
    out = []
    if len(tokens) >= 2:
        out.append("_".join(tokens))
        out.append(f"{tokens[0]}_{tokens[-1]}")
    elif len(tokens) == 1:
        out.append(tokens[0])
    seen = set()
    uniq = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _get(url: str) -> Optional[str]:
    if not requests:
        return None
    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        return r.text
    except Exception:
        return None


def grokipedia_search_slugs(query: str) -> List[str]:
    """Return ordered /page/ slug list from Grokipedia search HTML."""
    q = quote_plus(query.strip())
    html = _get(f"{GROKIPEDIA_ORIGIN}/search?q={q}")
    if not html:
        return []
    slugs: List[str] = []
    seen = set()
    for m in re.finditer(r'href="(/page/[A-Za-z0-9_]+)"', html):
        path = m.group(1)
        slug = path.split("/")[-1]
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    time.sleep(_REQUEST_DELAY_SEC)
    return slugs


def _score_slug(slug: str, name: str, known_for: str, bio: str) -> int:
    tokens = _name_tokens(name)
    if not tokens:
        return 0
    last = tokens[-1]
    s = slug.replace("_", " ").lower()
    ctx = f"{known_for} {bio}".lower()
    score = 0
    if last in s:
        score += 20
    for t in tokens[:-1]:
        if len(t) >= 3 and t in s:
            score += 6
    # Light context tie-break
    for word in re.findall(r"[a-zA-Z]{4,}", ctx):
        if word in s:
            score += 1
    # Obvious junk
    low = slug.lower()
    if "disambiguation" in low or low.endswith("_disambiguation"):
        score -= 50
    return score


def resolve_grokipedia_slug(
    name: str, known_for: str = "", bio: str = ""
) -> Tuple[Optional[str], Optional[str]]:
    """
    Pick the best-matching article slug using search + name tokens.
    Tries direct /page/First_Last URLs first when they exist.

    Returns (slug, cached_html_or_none) — cached HTML avoids a second download when parsing.
    """
    if not name.strip():
        return None, None
    for slug in _slug_variants(name):
        url = f"{GROKIPEDIA_ORIGIN}/page/{slug}"
        html = _get(url)
        time.sleep(_REQUEST_DELAY_SEC)
        if not html:
            continue
        if _page_looks_like_person(html, name):
            return slug, html
    slugs = grokipedia_search_slugs(name)
    if not slugs:
        return None, None
    scored: List[Tuple[int, str]] = [(_score_slug(s, name, known_for, bio), s) for s in slugs]
    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]
    chosen = slugs[0] if best_score <= 0 else best
    return chosen, None


def _page_looks_like_person(html: str, name: str) -> bool:
    """Reject soft-404 or wrong pages: expect infobox + last name in main text."""
    if BeautifulSoup is None:
        return len(html) > 5000 and (_name_tokens(name)[-1].lower() in html.lower() if _name_tokens(name) else False)
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if not main:
        return False
    aside = main.find("aside")
    if not aside:
        return False
    tokens = _name_tokens(name)
    if not tokens:
        return True
    last = tokens[-1]
    blob = _clean_text(main.get_text(" ", strip=True))[:8000].lower()
    return last in blob


def _parse_infobox(aside) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not aside:
        return out
    for row in aside.find_all("div", class_=lambda c: c and "flex-row" in c):
        dt = row.find("dt")
        dd = row.find("dd")
        if dt and dd:
            k = _clean_text(dt.get_text(" ", strip=True))
            v = _clean_text(dd.get_text(" ", strip=True))
            if k and v:
                out[k] = v
    return out


def _parse_article_flow(flow) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Lead paragraphs (before first h2) and h2 sections with condensed text."""
    lead: List[str] = []
    sections: List[Dict[str, Any]] = []
    if not flow:
        return lead, sections
    current_h2: Optional[str] = None
    buf: List[str] = []
    in_lead = True

    def flush_section():
        nonlocal buf, current_h2
        if not current_h2:
            return
        body = _clean_text(" ".join(buf))
        if len(body) > 40:
            sections.append({"heading": current_h2, "body": body[:3500]})
        buf = []

    for child in flow.children:
        if not getattr(child, "name", None):
            continue
        if child.name == "aside":
            continue
        if child.name == "h2":
            in_lead = False
            flush_section()
            current_h2 = _clean_text(child.get_text(" ", strip=True))
            buf = []
            continue
        if child.name == "h3" and current_h2:
            h3 = _clean_text(child.get_text(" ", strip=True))
            if h3:
                buf.append(f"[{h3}] ")
            continue
        if in_lead and child.name == "span":
            cls = child.get("class") or []
            if "break-words" in cls:
                t = _clean_text(child.get_text(" ", strip=True))
                if len(t) > 60:
                    lead.append(t)
        if not in_lead and child.name == "span":
            cls = child.get("class") or []
            if "break-words" in cls and current_h2:
                t = _clean_text(child.get_text(" ", strip=True))
                if len(t) > 20:
                    buf.append(t)
    flush_section()
    return lead, sections


def _derive_profile_fields(
    infobox: Dict[str, str], sections: List[Dict[str, Any]]
) -> Dict[str, str]:
    derived: Dict[str, str] = {}

    title = infobox.get("Title") or ""
    org = infobox.get("Organization") or ""
    occ = infobox.get("Occupation") or ""
    if title and org:
        derived["current_role"] = f"{title}, {org}"
    elif org:
        derived["current_role"] = org
    elif occ:
        derived["current_role"] = occ

    if infobox.get("Former Positions"):
        derived["former_positions"] = infobox["Former Positions"]
    if infobox.get("Board Memberships"):
        derived["boards"] = infobox["Board Memberships"]
    if infobox.get("Education"):
        derived["education"] = infobox["Education"]
    if infobox.get("Political party") or infobox.get("Party"):
        derived["political_affiliation"] = infobox.get("Political party") or infobox.get("Party") or ""
    if infobox.get("Notable Works") or infobox.get("Publications"):
        derived["books_or_works"] = infobox.get("Notable Works") or infobox.get("Publications") or ""

    # Section-based fallbacks
    blob = {s["heading"].lower(): s["body"] for s in sections}
    for key, label in [
        ("political engagement", "political_summary"),
        ("political career", "political_summary"),
        ("bibliography", "books_or_works"),
        ("publications", "books_or_works"),
        ("academic career", "teaching_summary"),
        ("teaching", "teaching_summary"),
    ]:
        if label in derived and derived[label]:
            continue
        for h, body in blob.items():
            if key in h:
                derived[label] = body[:1200]
                break

    return {k: v for k, v in derived.items() if v}


def fetch_pundit_profile_from_grokipedia(
    name: str, known_for: str = "", bio: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Resolve article, download HTML, return structured profile dict for DB/JSON.
    Returns None if BeautifulSoup/requests missing or page not found.
    """
    if not BeautifulSoup or not requests:
        return None
    slug, cached_html = resolve_grokipedia_slug(name, known_for=known_for, bio=bio)
    if not slug:
        return None
    url = f"{GROKIPEDIA_ORIGIN}/page/{slug}"
    html = cached_html or _get(url)
    if not cached_html:
        time.sleep(_REQUEST_DELAY_SEC)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if not main:
        return None
    article = main.find("article") or main
    h1 = article.find("h1")
    page_title = _clean_text(h1.get_text(" ", strip=True)) if h1 else name
    aside = article.find("aside")
    infobox = _parse_infobox(aside)
    flow = None
    for div in article.find_all("div", class_=True):
        cls = div.get("class") or []
        if "flow-root" in cls:
            flow = div
            break
    lead_paragraphs, sections = _parse_article_flow(flow)
    derived = _derive_profile_fields(infobox, sections)

    # Cliff notes: first ~900 words from lead
    cliff_parts = lead_paragraphs[:8]
    cliff = _clean_text(" ".join(cliff_parts))
    if len(cliff) > 2800:
        cliff = cliff[:2800].rsplit(" ", 1)[0] + "…"

    now = datetime.now(timezone.utc).isoformat()
    return {
        "source": "grokipedia",
        "source_url": url,
        "page_slug": slug,
        "page_title": page_title,
        "fetched_at": now,
        "infobox": infobox,
        "lead_paragraphs": lead_paragraphs[:12],
        "cliff_notes": cliff,
        "sections": sections[:24],
        "derived": derived,
    }
