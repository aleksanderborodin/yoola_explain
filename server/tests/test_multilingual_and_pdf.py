"""Repros for the two real-world failures from production logs (2026-07-04):
a Russian privacy policy 422-ing on the English-only plausibility gate, and
PDF legal documents being rejected outright."""

from yoola.extract import extract_pdf_text
from yoola.plausibility import check_plausibility

from conftest import (
    RUSSIAN_TOS,
    SAMPLE_TOS,
    FakeProvider,
    fetch_failing,
    fetch_returning_pdf,
    make_pdf,
)


def test_russian_legal_text_passes_plausibility():
    result = check_plausibility(RUSSIAN_TOS, min_words=120, min_density=2.0)
    assert result.ok, f"density={result.density}, words={result.words}"


def test_russian_client_fallback_flow_works(make_client):
    # The tbank.ru repro: server fetch blocked -> extension sends the Russian
    # page text -> must generate, not 422.
    provider = FakeProvider()
    with make_client(provider, fetch_failing) as client:
        response = client.post(
            "/v1/summary",
            json={"url": "https://bank.example.ru/privacy/", "language": "ru",
                  "client_content": RUSSIAN_TOS},
        )
        assert response.status_code == 200, response.text
        assert response.json()["source_verified"] is False
        assert provider.generate_calls == 1


def test_pdf_text_extraction():
    lines = [line for line in SAMPLE_TOS.splitlines() if line.strip()]
    text = extract_pdf_text(make_pdf(lines))
    assert "binding arbitration" in text
    assert "LIMITATION OF LIABILITY" in text


def test_pdf_document_end_to_end(make_client):
    # The modelgate.ru repro: a ToS served as application/pdf must summarize.
    provider = FakeProvider()
    pdf = make_pdf([line for line in SAMPLE_TOS.splitlines() if line.strip()])
    with make_client(provider, fetch_returning_pdf(pdf)) as client:
        response = client.post(
            "/v1/summary", json={"url": "https://example.com/legal/terms.pdf", "language": "en"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source_verified"] is True  # server fetched the PDF itself
        present = {c["id"] for c in body["categories"] if c["status"] == "present"}
        assert "arbitration" in present
        # quotes anchor in the EXTRACTED pdf text
        arbitration = next(c for c in body["categories"] if c["id"] == "arbitration")
        assert arbitration["quotes"] and arbitration["quotes"][0]["offset"] is not None


def test_corrupt_pdf_rejected_not_crashed(make_client):
    provider = FakeProvider()
    with make_client(provider, fetch_returning_pdf(b"%PDF-1.4 garbage")) as client:
        response = client.post(
            "/v1/summary", json={"url": "https://example.com/broken.pdf", "language": "en"}
        )
        assert response.status_code == 422  # empty extraction -> plausibility gate
        assert provider.generate_calls == 0
