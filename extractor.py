# ~/nixos-config/modules/nixos/homelab/article2pod-src/extractor.py
import os
import json
import logging
import re
import urllib.request
import urllib.error

import trafilatura
import trafilatura.settings

log = logging.getLogger(__name__)

FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT = 20


class ExtractionError(Exception):
    pass


def _fetch_direct(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise ExtractionError(f"HTTP {e.code} fetching {url}") from e
    except Exception as e:
        raise ExtractionError(f"Fetch error: {e}") from e


def _fetch_via_flaresolverr(url: str) -> str:
    payload = json.dumps({
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 60000,
    }).encode()
    req = urllib.request.Request(
        f"{FLARESOLVERR_URL}/v1",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        if data.get("status") != "ok":
            raise ExtractionError(f"FlareSolverr error: {data.get('message', data)}")
        return data["solution"]["response"]
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"FlareSolverr request failed: {e}") from e


def _title_from_html(html: str) -> str | None:
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    t = re.sub(r'\s+', ' ', m.group(1)).strip()
    for sep in (' | ', ' - ', ' – ', ' — ', ' · '):
        if sep in t:
            t = t.rsplit(sep, 1)[0].strip()
    return t or None


def _parse(html: str, url: str) -> dict:
    result = trafilatura.extract(
        html,
        url=url,
        output_format="json",
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not result:
        raise ExtractionError("trafilatura returned no content")
    data = json.loads(result)
    text = data.get("text", "").strip()
    if len(text) < 100:
        raise ExtractionError(f"Extracted text too short ({len(text)} chars)")
    return {
        "title": (data.get("title") or _title_from_html(html) or "Untitled").strip(),
        "author": (data.get("author") or "Unknown").strip(),
        "pub_date": data.get("date") or "",
        "text": text,
    }


def _looks_like_challenge(html: str) -> bool:
    markers = [
        "cf-browser-verification",
        "cf_chl_opt",
        "Enable JavaScript and cookies",
        "challenges.cloudflare.com",
        "Just a moment...",
    ]
    return any(m.lower() in html.lower() for m in markers)


def extract(url: str) -> dict:
    """Return dict with title, author, pub_date, text. Raises ExtractionError on failure."""
    log.info("Fetching %s", url)

    # Try direct fetch first
    try:
        html = _fetch_direct(url)
        if not _looks_like_challenge(html):
            return _parse(html, url)
        log.info("Cloudflare challenge detected, trying FlareSolverr")
    except ExtractionError as e:
        log.warning("Direct fetch failed (%s), trying FlareSolverr", e)

    # FlareSolverr fallback
    html = _fetch_via_flaresolverr(url)
    return _parse(html, url)
