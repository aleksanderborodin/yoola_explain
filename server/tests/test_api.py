"""End-to-end API behavior over the real app and pipeline, with a deterministic
fake provider. Every economic/trust claim of Design v4 gets a test here."""

import re

from conftest import (
    RECIPE_TEXT,
    SAMPLE_TOS,
    FakeProvider,
    fetch_by_url,
    fetch_failing,
    fetch_returning,
    html_page,
)

URL = "https://example.com/terms"

# A second, genuinely different legal document (no arbitration section).
OTHER_TOS = re.sub(r"14\..*?15\.", "15.", SAMPLE_TOS, flags=re.DOTALL).replace(
    "Example Company", "Other Corp"
)


def post(client, url=URL, language="en", content=None):
    body = {"url": url, "language": language}
    if content is not None:
        body["client_content"] = content
    return client.post("/v1/summary", json=body)


# ------------------------------------------------------------ the economic core


def test_same_url_generates_exactly_once(make_client):
    provider = FakeProvider()
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        first = post(client)
        assert first.status_code == 200
        body = first.json()
        assert body["source"] == "generated"
        assert body["source_verified"] is True
        assert body["grade"] in "ABCDE"

        again = post(client)
        assert again.status_code == 200
        assert again.json()["source"] == "cache"
        assert provider.generate_calls == 1  # the whole thesis

        got = client.get("/v1/summary", params={"url": URL})
        assert got.status_code == 200
        assert got.json()["source"] == "cache"


def test_two_urls_same_content_share_one_generation(make_client):
    provider = FakeProvider()
    page = html_page(SAMPLE_TOS)
    pages = {"https://example.com/terms": page, "https://example.de/agb": page}
    with make_client(provider, fetch_by_url(pages)) as client:
        assert post(client, "https://example.com/terms").status_code == 200
        assert post(client, "https://example.de/agb").status_code == 200
        assert provider.generate_calls == 1


def test_get_is_pure_read(make_client):
    provider = FakeProvider()
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        assert client.get("/v1/summary", params={"url": URL}).status_code == 404
        assert provider.generate_calls == 0  # GET never generates


# ------------------------------------------------------------ grounding & honesty


def test_every_present_category_quote_anchors_in_source(make_client):
    with make_client(FakeProvider(), fetch_returning(html_page(SAMPLE_TOS))) as client:
        body = post(client).json()
        present = [c for c in body["categories"] if c["status"] == "present"]
        assert {"arbitration", "unilateral_changes"} <= {c["id"] for c in present}
        for category in present:
            assert category["quotes"], f"{category['id']} has no anchored quote"
            for quote in category["quotes"]:
                assert quote["offset"] is not None
        assert body["disclaimer"]
        assert body["tldr"]


def test_unsupported_claims_marked_possible(make_client):
    provider = FakeProvider()
    provider.verify_result = False
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        body = post(client).json()
        present = [c for c in body["categories"] if c["status"] == "present"]
        assert present and all(c["confidence"] == "possible" for c in present)


def test_crosscheck_catches_omission_with_targeted_recheck(make_client):
    provider = FakeProvider()
    provider.omit = {"arbitration"}  # model "forgets" arbitration on the first pass
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        body = post(client).json()
        assert provider.generate_calls == 1  # NOT a second full generation
        assert provider.recheck_calls == 1  # targeted, context-only recheck instead
        arbitration = next(c for c in body["categories"] if c["id"] == "arbitration")
        assert arbitration["status"] == "present"


def test_persistent_omission_flagged_possible(make_client):
    provider = FakeProvider()
    provider.omit = {"arbitration"}
    provider.fix_on_notice = False  # stays wrong even after the notice
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        body = post(client).json()
        arbitration = next(c for c in body["categories"] if c["id"] == "arbitration")
        assert arbitration["status"] == "not_addressed"
        assert arbitration["confidence"] == "possible"  # honest uncertainty, not silence


# ------------------------------------------------------------ gates


def test_non_legal_content_rejected_422(make_client):
    provider = FakeProvider()
    with make_client(provider, fetch_returning(html_page(RECIPE_TEXT, "Recipes"))) as client:
        assert post(client, "https://example.com/blog").status_code == 422
        assert provider.generate_calls == 0


def test_oversized_document_rejected_413(make_client):
    with make_client(
        FakeProvider(), fetch_failing, content_max_chars=1000
    ) as client:
        response = post(client, content="terms " * 5000)
        assert response.status_code == 413


def test_bad_url_rejected_400(make_client):
    with make_client(FakeProvider(), fetch_failing) as client:
        assert post(client, "ftp://example.com/x").status_code == 400


def test_fetch_failure_without_fallback_502(make_client):
    with make_client(FakeProvider(), fetch_failing) as client:
        response = post(client)
        assert response.status_code == 502
        assert "client_content" in response.json()["detail"]


# ------------------------------------------------------------ budgets


def test_ip_budget_exhaustion_429(make_client):
    pages = {
        "https://a.com/terms": html_page(SAMPLE_TOS),
        "https://b.com/terms": html_page(OTHER_TOS),
    }
    with make_client(
        FakeProvider(), fetch_by_url(pages), ip_daily_miss_budget=1, simhash_max_distance=0
    ) as client:
        assert post(client, "https://a.com/terms").status_code == 200
        assert post(client, "https://b.com/terms").status_code == 429
        # cache hits remain unlimited after the budget is gone
        assert post(client, "https://a.com/terms").status_code == 200


def test_global_ceiling_degrades_to_202(make_client):
    with make_client(
        FakeProvider(), fetch_returning(html_page(SAMPLE_TOS)), global_daily_miss_budget=0
    ) as client:
        response = post(client)
        assert response.status_code == 202
        assert response.headers["Retry-After"]


# ------------------------------------------------------------ fallback quarantine


def test_client_content_fallback_is_quarantined(make_client):
    provider = FakeProvider()
    with make_client(provider, fetch_failing) as client:
        first = post(client, content=SAMPLE_TOS)
        assert first.status_code == 200
        assert first.json()["source_verified"] is False
        assert provider.generate_calls == 1

        # URL is never mapped for unverified content: GET stays a miss.
        assert client.get("/v1/summary", params={"url": URL}).status_code == 404

        # Byte-identical resubmission is served from cache, still unverified.
        again = post(client, content=SAMPLE_TOS)
        assert again.status_code == 200
        assert again.json()["source_verified"] is False
        assert provider.generate_calls == 1


def test_successful_fetch_upgrades_quarantined_entry(make_client):
    from yoola.extract import extract_main_text
    from yoola.fetch import FetchError

    provider = FakeProvider()
    # The fallback text must equal what extraction of the page yields, so the
    # doc_version matches when the site later unblocks: submit the extracted text.
    extracted = extract_main_text(html_page(SAMPLE_TOS), URL)
    blocked_pages = {}

    async def fetch_first_blocked(url, settings):
        if url in blocked_pages:
            return await fetch_by_url(blocked_pages)(url, settings)
        raise FetchError("blocked")

    with make_client(provider, fetch_first_blocked) as client:
        assert post(client, content=extracted).json()["source_verified"] is False
        blocked_pages[URL] = html_page(SAMPLE_TOS)  # site unblocks
        upgraded = post(client)
        assert upgraded.status_code == 200
        assert upgraded.json()["source_verified"] is True
        assert provider.generate_calls == 1  # same content: no second generation
        assert client.get("/v1/summary", params={"url": URL}).status_code == 200


# ------------------------------------------------------------ near-duplicates (C7)


def test_cosmetic_variant_reuses_summary(make_client):
    provider = FakeProvider()
    variant = SAMPLE_TOS.replace("May 15, 2025", "May 16, 2025")
    pages = {
        "https://example.com/terms": html_page(SAMPLE_TOS),
        "https://example.com/terms-v2": html_page(variant),
    }
    with make_client(provider, fetch_by_url(pages)) as client:
        assert post(client, "https://example.com/terms").status_code == 200
        assert post(client, "https://example.com/terms-v2").status_code == 200
        assert provider.generate_calls == 1  # cosmetic change never regenerates


def test_material_change_regenerates(make_client):
    provider = FakeProvider()
    # Same document, but the arbitration/class-action section is REMOVED:
    # keyword sets differ -> near-dup must NOT reuse (old summary would
    # assert clauses that no longer exist).
    pages = {
        "https://example.com/terms": html_page(OTHER_TOS),
        "https://example.com/terms-new": html_page(SAMPLE_TOS),
    }
    with make_client(provider, fetch_by_url(pages)) as client:
        assert post(client, "https://example.com/terms").status_code == 200
        assert post(client, "https://example.com/terms-new").status_code == 200
        assert provider.generate_calls == 2


# ------------------------------------------------------------ feedback loop


def report(client, doc_version, ip):
    # trusted_proxy_hops=1 in these tests, so X-Forwarded-For sets the reporter.
    return client.post(
        "/v1/report",
        json={"doc_version": doc_version, "reason": "wrong"},
        headers={"X-Forwarded-For": ip},
    )


def test_reports_mark_disputed_but_never_deny_or_regenerate(make_client):
    provider = FakeProvider()
    with make_client(
        provider,
        fetch_returning(html_page(SAMPLE_TOS)),
        dispute_threshold=3,
        trusted_proxy_hops=1,
    ) as client:
        doc_version = post(client).json()["doc_version"]
        for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
            assert report(client, doc_version, ip).status_code == 204

        # Still served — reporting adds a warning, never a 409 or a paid regen.
        got = client.get("/v1/summary", params={"url": URL})
        assert got.status_code == 200
        assert got.json()["disputed"] is True
        assert post(client).json()["disputed"] is True
        assert provider.generate_calls == 1  # no report-driven regeneration


def test_one_ip_cannot_cast_multiple_dispute_votes(make_client):
    provider = FakeProvider()
    with make_client(
        provider,
        fetch_returning(html_page(SAMPLE_TOS)),
        dispute_threshold=3,
        trusted_proxy_hops=1,
    ) as client:
        doc_version = post(client).json()["doc_version"]
        for _ in range(5):
            report(client, doc_version, "9.9.9.9")  # same reporter every time
        assert client.get("/v1/summary", params={"url": URL}).json()["disputed"] is False


def test_report_rate_limited_per_ip(make_client):
    provider = FakeProvider()
    with make_client(
        provider,
        fetch_returning(html_page(SAMPLE_TOS)),
        ip_daily_report_budget=2,
        trusted_proxy_hops=1,
    ) as client:
        doc_version = post(client).json()["doc_version"]
        assert report(client, doc_version, "5.5.5.5").status_code == 204
        assert report(client, doc_version, "5.5.5.5").status_code == 204
        assert report(client, doc_version, "5.5.5.5").status_code == 429


# ------------------------------------------------------------ registry (detection)


def test_registry_lists_verified_urls_only(make_client):
    import hashlib

    provider = FakeProvider()
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        assert client.get("/v1/registry").json()["urls"] == []  # empty at first
        post(client)  # server-fetched + generated -> promoted
        digest = client.get("/v1/registry").json()
        expected = hashlib.sha256(URL.encode()).hexdigest()[: digest["hash_len"]]
        assert expected in digest["urls"]


def test_client_fallback_not_in_registry(make_client):
    # Quarantined (unverified) entries must not surface for other users.
    provider = FakeProvider()
    with make_client(provider, fetch_failing) as client:
        assert post(client, content=SAMPLE_TOS).json()["source_verified"] is False
        assert client.get("/v1/registry").json()["urls"] == []
        assert client.get("/v1/directory").json()["entries"] == []


def test_directory_lists_verified_summaries(make_client):
    provider = FakeProvider()
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        post(client)
        entries = client.get("/v1/directory").json()["entries"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["url"] == URL
        assert entry["grade"] in "ABCDE"
        assert entry["alerts"] >= 1
        assert entry["tldr"]


# ------------------------------------------------------------ LLM legal-check gate


def test_llm_legal_check_rejects_non_legal(make_client):
    provider = FakeProvider()
    provider.legal_result = False  # LLM says "not a legal agreement"
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        assert post(client).status_code == 422
        assert provider.classify_calls == 1
        assert provider.generate_calls == 0  # gated before the expensive call


def test_llm_legal_check_can_be_disabled(make_client):
    provider = FakeProvider()
    provider.legal_result = False
    with make_client(
        provider, fetch_returning(html_page(SAMPLE_TOS)), llm_legal_check=False
    ) as client:
        assert post(client).status_code == 200
        assert provider.classify_calls == 0


# ------------------------------------------------------------ translation (C9)


def test_translation_on_demand_quotes_stay_source_language(make_client):
    provider = FakeProvider()
    with make_client(provider, fetch_returning(html_page(SAMPLE_TOS))) as client:
        body = post(client, language="ru").json()
        assert body["language"] == "ru"
        assert body["source"] == "translated"
        assert all(t.startswith("[ru]") for t in body["tldr"])
        present = [c for c in body["categories"] if c["status"] == "present"]
        assert all(c["explanation"].startswith("[ru]") for c in present)
        # quotes stay verbatim source language
        assert not any(
            q["text"].startswith("[ru]") for c in present for q in c["quotes"]
        )
        assert provider.translate_calls == 1

        post(client, language="ru")
        assert provider.translate_calls == 1  # cached per language
        assert provider.generate_calls == 1


def test_metrics_expose_hit_rate(make_client):
    with make_client(FakeProvider(), fetch_returning(html_page(SAMPLE_TOS))) as client:
        post(client)
        post(client)
        text = client.get("/metrics").text
        assert "yoola_generated 1" in text
        assert "yoola_cache_hit_post 1" in text
