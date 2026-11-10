"""Crawler: fetches pages from a website (same domain, up to MAX_PAGES) and
extracts their readable text content and metadata (URL, title)."""

from __future__ import annotations

import argparse
import hashlib
import logging
import time
from collections import deque
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "SiteChatWidgetBot/1.0"
TIMEOUT_SECONDS = 10.0
DELAY_SECONDS = 0.5

# Link types we never want to download: files, images, and non-web links.
SKIPPED_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".zip", ".gz", ".tar", ".rar", ".mp3", ".mp4", ".mov", ".avi",
    ".css", ".js", ".xml", ".json", ".doc", ".docx", ".xls", ".xlsx",
)
SKIPPED_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "ftp:")


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Turn a link into one clean, comparable URL, or None if it's not usable.

    Example: "../about/?ref=nav#team" on https://site.com/blog/
             becomes "https://site.com/about".
    """
    url = url.strip()

    # Ignore links that aren't web pages (email, phone, JavaScript...).
    if url.lower().startswith(SKIPPED_SCHEMES):
        return None

    # Turn relative links ("/about", "../contact") into full URLs.
    if base:
        url = urljoin(base, url)

    # Drop the "#section" part: it points to the same page.
    url, _fragment = urldefrag(url)

    parts = urlsplit(url)

    # Only http and https pages can be crawled.
    if parts.scheme not in ("http", "https"):
        return None

    # Drop the "?query" part and the trailing slash, and lowercase the
    # domain, so "/about/" and "/about?x=1" count as the same page.
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _domain(url: str) -> str:
    """Return the host name without a leading "www." (www.site.com == site.com)."""
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def _is_same_domain(url: str, start_url: str) -> bool:
    return _domain(url) == _domain(start_url)


def _page_key(url: str) -> str:
    """Identity of a page, ignoring http/https and "www."

    Many sites mix http:// and https:// links (or redirect between them),
    so we compare pages on domain + path only.
    """
    return _domain(url) + urlsplit(url).path


def _use_https(url: str) -> str:
    """Rewrite a URL to https (used when the site was started on https)."""
    return urlunsplit(("https",) + tuple(urlsplit(url))[1:])


def _content_fingerprint(soup: BeautifulSoup) -> str:
    """A short hash of the page's visible text, to spot duplicate pages
    served under different URLs (e.g. /tag/love and /tag/love/page/1)."""
    text = " ".join(soup.get_text(" ").split())
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _main_heading(soup: BeautifulSoup, title: str) -> str | None:
    """First h1/h2/h3 whose text differs from the <title>, if any."""
    for heading in soup.find_all(["h1", "h2", "h3"]):
        text = " ".join(heading.get_text(" ").split())
        if text and text != title:
            return text
    return None


def _looks_like_file(url: str) -> bool:
    """True if the URL ends with a file extension we don't want (pdf, jpg...)."""
    return urlsplit(url).path.lower().endswith(SKIPPED_EXTENSIONS)


def _load_robots(client: httpx.Client, start_url: str) -> RobotFileParser:
    """Download and parse the site's robots.txt (the site's rules for bots)."""
    parts = urlsplit(start_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = RobotFileParser(robots_url)

    try:
        response = client.get(robots_url)
    except httpx.HTTPError as exc:
        # Can't reach robots.txt: assume everything is allowed.
        logger.warning("Could not fetch %s (%s); assuming all pages allowed", robots_url, exc)
        parser.parse([])
        return parser

    if response.status_code in (401, 403):
        # The site refuses access to its rules: play safe and crawl nothing.
        logger.warning("%s returned %s; treating site as off-limits", robots_url, response.status_code)
        parser.disallow_all = True
    elif response.status_code >= 400:
        # No robots.txt (usually 404): everything is allowed.
        parser.parse([])
    else:
        parser.parse(response.text.splitlines())

    return parser


def _extract_title(soup: BeautifulSoup, fallback: str) -> str:
    """Use the page <title>, or the URL if the page has no title."""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            return title
    return fallback


def crawl(start_url: str, max_pages: int | None = None) -> list[dict]:
    """Crawl a website breadth-first and return its HTML pages.

    Each page is a dict: {"url": str, "title": str, "html": str}.
    Stops after `max_pages` pages (defaults to MAX_PAGES from settings).
    """
    if max_pages is None:
        from app.config import get_settings

        max_pages = get_settings().max_pages

    start = normalize_url(start_url)
    if start is None:
        raise ValueError(f"Not a valid http(s) URL: {start_url!r}")

    # If the user started on https, keep every page on https, even when the
    # site links to (or redirects to) the http:// version.
    force_https = urlsplit(start).scheme == "https"

    def same_site(url: str) -> str:
        return _use_https(url) if force_https else url

    pages: list[dict] = []
    headings: dict[str, str | None] = {}  # url -> main heading, for titles

    # BFS: the queue holds pages still to visit, in the order we found them.
    # "seen" holds the key of every page already queued (ignoring http/https),
    # so each page is fetched once.
    queue: deque[str] = deque([start])
    seen: set[str] = {_page_key(start)}

    # Fingerprints of the text of pages already kept, to skip copies.
    seen_content: dict[str, str] = {}  # fingerprint -> first url with it

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        robots = _load_robots(client, start)
        first_request = True

        while queue and len(pages) < max_pages:
            url = queue.popleft()

            # Skip pages the site asked bots not to visit.
            if not robots.can_fetch(USER_AGENT, url):
                logger.info("Blocked by robots.txt: %s", url)
                continue

            # Be polite: wait a little between two requests to the same site.
            if not first_request:
                time.sleep(DELAY_SECONDS)
            first_request = False

            # Download the page. Network errors are logged, never fatal.
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                logger.warning("Request failed for %s: %s", url, exc)
                continue

            # Keep only successful HTML pages (no 404s, no images, no PDFs).
            content_type = response.headers.get("content-type", "")
            if response.status_code != 200:
                logger.info("Skipping %s (status %s)", url, response.status_code)
                continue
            if "text/html" not in content_type.lower():
                logger.info("Skipping %s (content-type %r)", url, content_type)
                continue

            # Redirects can land on another URL: use the final one, and drop
            # it if it left the site or if we already have that page.
            final_url = normalize_url(str(response.url)) or url
            if not _is_same_domain(final_url, start):
                logger.info("Skipping %s (redirected off-site to %s)", url, final_url)
                continue
            final_url = same_site(final_url)
            if _page_key(final_url) != _page_key(url):
                if _page_key(final_url) in seen:
                    continue
                seen.add(_page_key(final_url))

            # Parse the HTML to read the title and find links.
            try:
                html = response.text
                soup = BeautifulSoup(html, "html.parser")
            except Exception as exc:  # malformed pages must not stop the crawl
                logger.warning("Could not parse %s: %s", final_url, exc)
                continue

            # Same text as a page we already kept? It's a copy under another
            # URL: skip it (its links are the same too, so no need to follow).
            fingerprint = _content_fingerprint(soup)
            if fingerprint in seen_content:
                logger.info("Skipping %s (same content as %s)", final_url, seen_content[fingerprint])
                continue
            seen_content[fingerprint] = final_url

            title = _extract_title(soup, final_url)
            headings[final_url] = _main_heading(soup, title)
            pages.append({"url": final_url, "title": title, "html": html})
            logger.info("[%d/%d] %s", len(pages), max_pages, final_url)

            # Add every new same-site page link to the end of the queue.
            for anchor in soup.find_all("a", href=True):
                link = normalize_url(anchor["href"], base=final_url)
                if link is None or _page_key(link) in seen:
                    continue
                if not _is_same_domain(link, start) or _looks_like_file(link):
                    continue
                seen.add(_page_key(link))
                queue.append(same_site(link))

    _disambiguate_titles(pages, headings)
    return pages


def _disambiguate_titles(pages: list[dict], headings: dict[str, str | None]) -> None:
    """Give pages that share the same <title> a more specific one.

    Some sites use one title everywhere ("Quotes to Scrape"). For those
    pages we prepend the page's main heading: "Albert Einstein — Quotes to
    Scrape". Pages with a unique title, and the home page, are left as is.
    """
    counts: dict[str, int] = {}
    for page in pages:
        counts[page["title"]] = counts.get(page["title"], 0) + 1

    for page in pages:
        is_home = urlsplit(page["url"]).path == ""
        heading = headings.get(page["url"])
        if counts[page["title"]] > 1 and not is_home and heading:
            page["title"] = f"{heading} — {page['title']}"


def main() -> None:
    """Command line: python -m app.crawler https://example.com [--max-pages N]"""
    parser = argparse.ArgumentParser(description="Crawl a website and list its pages.")
    parser.add_argument("url", help="Start URL, e.g. https://example.com")
    parser.add_argument("--max-pages", type=int, default=None, help="Page limit (default: MAX_PAGES)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    pages = crawl(args.url, max_pages=args.max_pages)

    print(f"\nCrawled {len(pages)} page(s):")
    for page in pages:
        print(f"- {page['url']}  |  {page['title']}")


if __name__ == "__main__":
    main()
