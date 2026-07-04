"""Server-side plausibility gate — the enforcement point that keeps Yoola from
being a free general-purpose summarizer (Design v4 §3 step 5). Cheap and
non-LLM by construction: legal-marker density over the canonical text."""

import re
from dataclasses import dataclass

from .identity import canonicalize

LEGAL_MARKERS = [
    "terms of service", "terms of use", "terms and conditions", "privacy policy",
    "user agreement", "these terms", "this agreement", "acceptance of terms",
    "personal data", "personal information", "intellectual property", "liability",
    "warranty", "warranties", "indemnif", "arbitrat", "governing law", "jurisdiction",
    "termination", "terminate", "third party", "third parties", "consent", "disclaim",
    "license", "licence", "you agree", "we reserve the right", "applicable law",
    "dispute", "refund", "subscription", "confidential",
]
_MARKER_RE = re.compile("|".join(re.escape(m) for m in LEGAL_MARKERS))


@dataclass
class PlausibilityResult:
    ok: bool
    words: int
    density: float  # marker hits per 1000 words


def check_plausibility(text: str, min_words: int, min_density: float) -> PlausibilityResult:
    canonical = canonicalize(text)
    words = len(canonical.split())
    if words < min_words:
        return PlausibilityResult(False, words, 0.0)
    hits = len(_MARKER_RE.findall(canonical))
    density = hits * 1000.0 / words
    return PlausibilityResult(density >= min_density, words, density)
