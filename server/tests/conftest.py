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


RUSSIAN_TOS = """
Политика конфиденциальности и пользовательское соглашение

1. Общие положения. Настоящие условия использования регулируют порядок доступа к сервису.
Используя сервис, вы соглашаетесь с настоящими условиями. Мы оставляем за собой право
изменять настоящее соглашение в любое время без предварительного уведомления.

2. Персональные данные. Оператор осуществляет обработку персональных данных пользователя,
включая имя, адрес электронной почты и данные об использовании сервиса. Обработка
персональных данных осуществляется с согласия пользователя. Персональные данные могут
передаваться третьим лицам в целях исполнения договора. Конфиденциальность данных
обеспечивается в соответствии с применимым законодательством.

3. Ответственность. Оператор не несет ответственность за косвенные убытки. Совокупная
ответственность оператора ограничена суммой, уплаченной пользователем за подписку.
Возврат средств не производится, за исключением случаев, предусмотренных
законодательством.

4. Интеллектуальная собственность. Все права на объекты интеллектуальной собственности
принадлежат оператору. Пользователь получает ограниченную лицензию на использование.

5. Расторжение. Оператор вправе прекратить доступ пользователя к сервису в случае
нарушения настоящих условий. Разрешение споров осуществляется в соответствии с
законодательством по месту нахождения оператора. Все споры подлежат рассмотрению в суде.
""" * 2


def make_pdf(lines: list[str]) -> bytes:
    """Minimal one-page PDF with a real text layer (Helvetica, latin-1 only) —
    enough for pypdf to extract; keeps the fixture dependency-free."""
    content = b"BT /F1 10 Tf 40 780 Td 14 TL " + b" ".join(
        b"(" + line.encode("latin-1").replace(b"(", b"[").replace(b")", b"]") + b") Tj T*"
        for line in lines
    ) + b" ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_at).encode() + b"\n%%EOF"
    )
    return out


def fetch_returning_pdf(pdf: bytes):
    async def fetch_fn(url: str, settings: Settings) -> FetchResult:
        return FetchResult(html="", final_url=url, pdf=pdf)

    return fetch_fn
