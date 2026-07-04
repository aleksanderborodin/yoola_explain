"""Real client IP resolution behind a trusted reverse proxy.

Direct (dev): use the socket peer. Behind N trusted proxies that APPEND to
X-Forwarded-For (Caddy/nginx default), the real client is the Nth entry from
the right — a spoofed leading entry a client injects lands further left and is
ignored. See docs/gotchas.md before changing the indexing.
"""

import hashlib


def client_ip(peer: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    if trusted_hops <= 0 or not forwarded_for:
        return peer or "unknown"
    chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    if len(chain) >= trusted_hops:
        return chain[-trusted_hops]
    return peer or "unknown"


def reporter_hash(ip: str, salt: str) -> str:
    """Opaque per-reporter id for de-duplicating flags without storing raw IPs."""
    return hashlib.blake2b(f"{salt}:{ip}".encode(), digest_size=16).hexdigest()
