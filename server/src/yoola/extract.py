"""Main-content extraction, server-side only (Design v4 C1)."""

import trafilatura


def extract_main_text(html: str, url: str | None = None) -> str:
    text = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=True, favor_recall=True
    )
    if not text:
        text = trafilatura.html2txt(html) or ""
    return text.strip()
