"""Main-content extraction, server-side only (Design v4 C1). HTML via
trafilatura; PDFs via pypdf (many legal documents ship as PDFs)."""

import io
import logging

import trafilatura
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def extract_main_text(html: str, url: str | None = None) -> str:
    text = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=True, favor_recall=True
    )
    if not text:
        text = trafilatura.html2txt(html) or ""
    return text.strip()


def extract_pdf_text(data: bytes) -> str:
    """Text of all pages; empty string when the PDF has no text layer (scans) —
    the plausibility gate then rejects it honestly. OCR is roadmap."""
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as e:  # corrupt/encrypted PDFs must not 500 the pipeline
        logger.warning("pdf extraction failed: %s", e)
        return ""
