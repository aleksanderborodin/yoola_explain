"""Pydantic contracts: raw LLM output, the stored artifact, the API payload.

The stored artifact (SummaryDoc) is language-of-source; quotes are always
verbatim source language and never translated (Design v4 C9). Only
`explanation`/`tldr` strings get translated per language on demand.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["high", "medium", "low"]
Status = Literal["present", "not_addressed"]
Confidence = Literal["verified", "possible"]

SCHEMA_VERSION = 1


class LLMCategoryFinding(BaseModel):
    id: str
    status: Status
    severity: Severity | None = None
    explanation: str | None = None
    quotes: list[str] = Field(default_factory=list)


class LLMChecklist(BaseModel):
    """What the generator model must return; validated before anything else runs."""

    source_language: str = "en"  # BCP-47, reported by the model
    categories: list[LLMCategoryFinding]
    tldr: list[str] = Field(min_length=1, max_length=6)


class Quote(BaseModel):
    text: str
    offset: int | None = None  # server-computed offset into the extracted text (C4)


class CategoryFinding(BaseModel):
    id: str
    title: str
    status: Status
    severity: Severity | None = None
    explanation: str | None = None
    quotes: list[Quote] = Field(default_factory=list)
    confidence: Confidence | None = None  # None when not_addressed


class SummaryDoc(BaseModel):
    """The stored, language-of-source artifact (system of record)."""

    schema_version: int = SCHEMA_VERSION
    doc_version: str
    source_language: str
    grade: Literal["A", "B", "C", "D", "E"]
    categories: list[CategoryFinding]
    tldr: list[str]
    model_version: str
    generated_at: datetime


class SummaryResponse(SummaryDoc):
    url: str | None = None
    language: str
    source: Literal["cache", "generated", "translated"]
    source_verified: bool
    disclaimer: str


class SummaryRequest(BaseModel):
    url: str
    language: str = "en"
    client_content: str | None = None  # fallback path only (C1)


class ReportRequest(BaseModel):
    doc_version: str
    category: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


def compute_grade(categories: list[CategoryFinding]) -> Literal["A", "B", "C", "D", "E"]:
    high = sum(1 for c in categories if c.status == "present" and c.severity == "high")
    medium = sum(1 for c in categories if c.status == "present" and c.severity == "medium")
    if high >= 3:
        return "E"
    if high == 2:
        return "D"
    if high == 1 or medium >= 3:
        return "C"
    if medium >= 1:
        return "B"
    return "A"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
