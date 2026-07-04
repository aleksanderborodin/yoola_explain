"""URL normalization (the cache key of the primary path) and the SSRF guard."""

import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"gclid", "fbclid", "msclkid", "ref", "mc_cid", "mc_eid", "igshid"}
TRACKING_PREFIXES = ("utm_",)


class UrlError(ValueError):
    pass


def normalize_url(url: str) -> str:
    """Canonical cache key: https, lowercase host, no fragment/default port/tracking params."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UrlError(f"unsupported scheme: {parts.scheme!r}")
    if not parts.hostname:
        raise UrlError("missing host")
    host = parts.hostname.lower().rstrip(".")
    port = parts.port
    default_port = {"http": 80, "https": 443}[parts.scheme]
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in TRACKING_PARAMS and not k.startswith(TRACKING_PREFIXES)
    ]
    # Trailing slashes are preserved: many sites 301 between the variants, and
    # stripping them here caused redirect ping-pong. Slash variants of the same
    # page converge via the content hash instead.
    path = parts.path or "/"
    return urlunsplit((parts.scheme, netloc, path, urlencode(query), ""))


def assert_public_host(url: str) -> None:
    """Reject URLs whose host resolves to any non-global address (SSRF guard).

    Checked per redirect hop in fetch.py. Note the TOCTOU limit: httpx re-resolves
    DNS after this check; acceptable for our threat model (docs/gotchas.md).
    """
    host = urlsplit(url).hostname
    if not host:
        raise UrlError("missing host")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UrlError(f"cannot resolve host {host!r}: {e}") from e
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise UrlError(f"host {host!r} resolves to non-public address {addr}")
