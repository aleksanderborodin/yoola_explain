"""Server-side page fetching — the primary content path (Design v4 C1).

Redirects are followed manually so every hop passes the SSRF guard.
Headless-browser fallback for JS-walled pages is roadmap (docs/roadmap.md);
today those fall back to client-submitted content in the pipeline.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .urltools import UrlError, assert_public_host, normalize_url

MAX_REDIRECTS = 5
ACCEPTED_TYPES = ("text/html", "application/xhtml", "text/plain", "application/pdf")
# Browser-like headers: CDN bot walls (Cloudflare et al.) 403 self-identified
# bots outright, which made many mainstream ToS pages unreadable. We only ever
# fetch public legal pages, so presenting as a normal browser is fair; pages
# that still block us fall back to in-browser extraction (quarantined path).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    html: str
    final_url: str
    pdf: bytes | None = None  # set instead of html when the document is a PDF


async def fetch_page(url: str, settings: Settings) -> FetchResult:
    current = normalize_url(url)
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=settings.fetch_timeout_s,
        headers=FETCH_HEADERS,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                assert_public_host(current)
            except UrlError as e:
                raise FetchError(str(e)) from e
            try:
                response = await _get_capped(client, current, settings.fetch_max_bytes)
            except httpx.HTTPError as e:
                raise FetchError(f"fetch failed: {e}") from e
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect without location")
                # Follow the target as-is (re-normalizing can fight the site);
                # each hop still passes the scheme + SSRF checks above.
                target = str(httpx.URL(current).join(location))
                if urlsplit(target).scheme not in ("http", "https"):
                    raise FetchError(f"redirect to unsupported scheme: {target!r}")
                current = target
                continue
            if response.status_code != 200:
                raise FetchError(f"status {response.status_code}")
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not content_type.startswith(ACCEPTED_TYPES):
                raise FetchError(f"unsupported content type {content_type!r}")
            if content_type.startswith("application/pdf") or (
                not content_type and response.content[:5] == b"%PDF-"
            ):
                return FetchResult(html="", final_url=current, pdf=response.content)
            return FetchResult(html=response.text, final_url=current)
    raise FetchError("too many redirects")


async def _get_capped(client: httpx.AsyncClient, url: str, max_bytes: int) -> httpx.Response:
    async with client.stream("GET", url) as response:
        if response.status_code in (301, 302, 303, 307, 308) or response.status_code != 200:
            await response.aread()
            return response
        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > max_bytes:
                raise FetchError(f"response larger than {max_bytes} bytes")
        response._content = body
        return response
