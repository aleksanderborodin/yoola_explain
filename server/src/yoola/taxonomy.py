"""The clause-category checklist (Design v4 C3) and its regex prefilter.

The canonical taxonomy lives in shared/taxonomy.json. The keyword prefilter is
the non-LLM omission check (C2): if a category's keywords hit the text but the
model says "not_addressed", the pipeline retries and then degrades confidence.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache

MAX_HITS_PER_CATEGORY = 5


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    high_stakes: bool
    hint: str
    patterns: tuple[re.Pattern, ...]


@lru_cache(maxsize=4)
def load_taxonomy(path: str) -> tuple[Category, ...]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return tuple(
        Category(
            id=c["id"],
            title=c["title"],
            high_stakes=c["high_stakes"],
            hint=c["hint"],
            patterns=tuple(re.compile(k, re.IGNORECASE) for k in c["keywords"]),
        )
        for c in data["categories"]
    )


def keyword_hits(text: str, taxonomy: tuple[Category, ...]) -> dict[str, list[str]]:
    """Category id -> up to MAX_HITS_PER_CATEGORY distinct matched snippets."""
    hits: dict[str, list[str]] = {}
    for category in taxonomy:
        found: list[str] = []
        for pattern in category.patterns:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                if snippet not in found:
                    found.append(snippet)
                if len(found) >= MAX_HITS_PER_CATEGORY:
                    break
            if len(found) >= MAX_HITS_PER_CATEGORY:
                break
        if found:
            hits[category.id] = found
    return hits
