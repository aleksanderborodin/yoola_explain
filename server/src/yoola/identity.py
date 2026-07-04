"""Document identity: canonicalization, content hash (doc_version), SimHash.

Canonicalization exists only server-side (Design v4 C1) — there is no client
copy to keep in sync. The SimHash is used for cross-variant dedup and never
serves a summary on its own (C7); see pipeline.near_duplicate_check.
"""

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def canonicalize(text: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text).lower()).strip()


def doc_version(text: str) -> str:
    digest = hashlib.sha256(canonicalize(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def simhash64(text: str) -> int:
    """64-bit SimHash over word 3-shingles of the canonical text."""
    tokens = canonicalize(text).split()
    if not tokens:
        return 0
    if len(tokens) < 3:
        shingles = {" ".join(tokens)}
    else:
        shingles = {" ".join(tokens[i : i + 3]) for i in range(len(tokens) - 2)}
    bits = [0] * 64
    for shingle in shingles:
        h = int.from_bytes(hashlib.blake2b(shingle.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            bits[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i, b in enumerate(bits) if b > 0)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
