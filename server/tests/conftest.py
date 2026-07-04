from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yoola import metrics
from yoola.app import create_app
from yoola.config import Settings
from yoola.fetch import FetchError, FetchResult
from yoola.provider import LLMProvider
from yoola.schema import LLMCategoryFinding, LLMChecklist
from yoola.taxonomy import keyword_hits

FIXTURES = Path(__file__).parent / "fixtures"
SERVER_DIR = Path(__file__).parents[1]
SAMPLE_TOS = (FIXTURES / "sample_tos.txt").read_text()

RECIPE_TEXT = " ".join(
    ["Preheat the oven and whisk the eggs with sugar until fluffy, then fold in the flour."] * 40
)


def make_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        db_path=str(tmp_path / "test.db"),
        llm_api_key="fake-key",
        ip_daily_miss_budget=100,
        global_daily_miss_budget=1000,
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def real_settings(tmp_path, **overrides) -> Settings:
    """Loads server/.env — used by the real-LLM integration tests."""
    return Settings(
        _env_file=str(SERVER_DIR / ".env"), db_path=str(tmp_path / "test.db"), **overrides
    )


def html_page(text: str, title: str = "Terms of Service") -> str:
    paragraphs = "\n".join(f"<p>{line}</p>" for line in text.splitlines() if line.strip())
    return f"<html><head><title>{title}</title></head><body><main>{paragraphs}</main></body></html>"


def fetch_returning(html: str):
    async def fetch_fn(url: str, settings: Settings) -> FetchResult:
        return FetchResult(html=html, final_url=url)

    return fetch_fn


def fetch_by_url(pages: dict[str, str]):
    async def fetch_fn(url: str, settings: Settings) -> FetchResult:
        if url not in pages:
            raise FetchError("unknown url in test")
        return FetchResult(html=pages[url], final_url=url)

    return fetch_fn


async def fetch_failing(url: str, settings: Settings) -> FetchResult:
    raise FetchError("blocked by site")


class FakeProvider(LLMProvider):
    """Deterministic provider: marks a category present iff its keywords hit the
    text, quoting the real surrounding text (so anchors genuinely locate)."""

    def __init__(self):
        self.classify_calls = 0
        self.generate_calls = 0
        self.recheck_calls = 0
        self.verify_calls = 0  # batched calls, not per-claim
        self.translate_calls = 0
        self.verify_result = True
        self.legal_result = True  # classify_legal verdict
        self.omit: set[str] = set()  # categories wrongly reported not_addressed on pass 1
        self.fix_on_notice = True  # whether the targeted recheck "fixes" the omission

    async def classify_legal(self, text):
        self.classify_calls += 1
        return self.legal_result

    async def generate_checklist(self, text, taxonomy):
        self.generate_calls += 1
        hits = keyword_hits(text, taxonomy)
        categories = []
        for category in taxonomy:
            if category.id in hits and category.id not in self.omit:
                categories.append(
                    LLMCategoryFinding(
                        id=category.id,
                        status="present",
                        severity="high" if category.high_stakes else "medium",
                        explanation=f"The document addresses: {category.title}.",
                        quotes=[_context_quote(text, hits[category.id][0])],
                    )
                )
            else:
                categories.append(LLMCategoryFinding(id=category.id, status="not_addressed"))
        checklist = LLMChecklist(
            source_language="en",
            categories=categories,
            tldr=["First key point.", "Second key point.", "Third key point."],
        )
        return checklist, "fake-model-1"

    async def recheck_categories(self, context_by_category, categories):
        self.recheck_calls += 1
        findings = []
        for category in categories:
            context = context_by_category.get(category.id, "")
            if self.fix_on_notice and context:
                quote = context.split(" … ")[0][:200]
                findings.append(
                    LLMCategoryFinding(
                        id=category.id,
                        status="present",
                        severity="high" if category.high_stakes else "medium",
                        explanation=f"The document addresses: {category.title}.",
                        quotes=[quote],
                    )
                )
            else:
                findings.append(LLMCategoryFinding(id=category.id, status="not_addressed"))
        return findings

    async def verify_claims(self, items):
        self.verify_calls += 1
        return {key: self.verify_result for key, _, _ in items}

    async def translate(self, strings, target_language):
        self.translate_calls += 1
        return [f"[{target_language}] {s}" for s in strings]


def _context_quote(text: str, snippet: str) -> str:
    index = text.lower().find(snippet.lower())
    if index == -1:
        index = 0
    start = max(0, index - 60)
    end = min(len(text), index + len(snippet) + 60)
    return text[start:end]


@pytest.fixture(autouse=True)
def clean_metrics():
    metrics.reset()
    yield


@pytest.fixture
def make_client(tmp_path):
    """Build a TestClient over the real app with injectable provider/fetch/settings."""

    def build(provider=None, fetch_fn=None, **settings_overrides) -> TestClient:
        settings = make_settings(tmp_path, **settings_overrides)
        app = create_app(settings, provider=provider or FakeProvider(), fetch_fn=fetch_fn)
        return TestClient(app)

    return build
