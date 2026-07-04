"""Quote anchoring — the inversion of v3's offset grounding (Design v4 C4).

The model returns verbatim quotes; the *server* locates each one in the
extracted text with fuzzy matching and computes the offset itself. A quote
that does not locate above the threshold drops its point (never the summary).
"""

from rapidfuzz import fuzz


def locate_quote(quote: str, source: str, min_score: float) -> tuple[int, float] | None:
    """Return (offset_into_source, score) or None if the quote doesn't locate.

    Matching is case-insensitive; str.lower() is length-preserving for the
    overwhelming majority of text, so offsets remain valid in the original.
    """
    quote = quote.strip()
    if not quote or len(quote) < 8:
        return None
    alignment = fuzz.partial_ratio_alignment(quote.lower(), source.lower())
    if alignment is None or alignment.score < min_score:
        return None
    return alignment.dest_start, alignment.score
