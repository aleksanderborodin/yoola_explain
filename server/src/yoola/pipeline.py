"""The request pipeline (Design v4 §3).

Primary path: URL -> cache -> server fetch -> gates -> one generation -> cache.
Fallback path: client-submitted content, quarantined (url never mapped, entry
marked source_verified=0, served only on byte-identical content).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from . import metrics
from .anchor import locate_quote
from .config import DISCLAIMER, Settings
from .extract import extract_main_text
from .fetch import FetchError, FetchResult
from .identity import doc_version as compute_doc_version
from .identity import simhash64
from .plausibility import check_plausibility
from .provider import LLMProvider, ProviderError
from .schema import (
    CategoryFinding,
    LLMCategoryFinding,
    LLMChecklist,
    Quote,
    SummaryDoc,
    SummaryResponse,
    compute_grade,
    utcnow,
)
from .store import Store
from .taxonomy import Category, keyword_hits
from .urltools import UrlError, normalize_url

logger = logging.getLogger(__name__)

FetchFn = Callable[[str, Settings], Awaitable[FetchResult]]


@dataclass
class Deps:
    store: Store
    provider: LLMProvider
    settings: Settings
    taxonomy: tuple[Category, ...]
    fetch_fn: FetchFn  # injectable for tests


@dataclass
class Outcome:
    status: int
    payload: SummaryResponse | None = None
    detail: str | None = None
    retry_after: int | None = None


# ---------------------------------------------------------------- reads


def read_cached(deps: Deps, raw_url: str, language: str) -> Outcome:
    """GET path: pure cache read, never fetches, never calls the LLM."""
    try:
        url_key = normalize_url(raw_url)
    except UrlError as e:
        return Outcome(400, detail=str(e))
    entry = deps.store.get_url_entry(url_key)
    if entry is None:
        metrics.inc("cache_miss_get")
        return Outcome(404, detail="no cached summary for this URL")
    doc_ver = deps.store.resolve_doc_version(entry["doc_version"])
    doc = deps.store.get_summary(doc_ver)
    if doc is None:
        metrics.inc("cache_miss_get")
        return Outcome(404, detail="no cached summary for this URL")
    metrics.inc("cache_hit_get")
    # A disputed summary is still served (with a warning flag) — reports never
    # deny service or force a paid regeneration (docs/architecture.md).
    payload = _respond(deps, doc, url_key, language, source="cache")
    return Outcome(200, payload=payload)


# ---------------------------------------------------------------- the POST path


async def request_summary(
    deps: Deps, raw_url: str, language: str, client_content: str | None, ip: str
) -> Outcome:
    try:
        url_key = normalize_url(raw_url)
    except UrlError as e:
        return Outcome(400, detail=str(e))

    entry = deps.store.get_url_entry(url_key)
    if entry is not None and deps.store.url_entry_fresh(entry, deps.settings.url_ttl_days):
        doc = deps.store.get_summary(deps.store.resolve_doc_version(entry["doc_version"]))
        if doc is not None:
            metrics.inc("cache_hit_post")
            return await _serve(deps, doc, url_key, language)

    # Miss (or stale): the server observes the content itself (v4 C1).
    try:
        if deps.store.increment_budget("fetch:global") > deps.settings.global_daily_fetch_budget:
            metrics.inc("rejected_fetch_budget")
            return Outcome(503, detail="fetch capacity reached for today, try again later")
        fetched = await deps.fetch_fn(url_key, deps.settings)
        # trafilatura is CPU-bound and synchronous — never run it on the event
        # loop, or one large page stalls every other request (docs/gotchas.md).
        text = await asyncio.to_thread(extract_main_text, fetched.html, fetched.final_url)
        source_verified = True
        final_url = fetched.final_url
        metrics.inc("fetch_ok")
    except (FetchError, UrlError) as e:
        metrics.inc("fetch_failed")
        if not client_content:
            return Outcome(
                502, detail=f"could not fetch the page ({e}); resubmit with client_content"
            )
        text = client_content
        source_verified = False
        final_url = None
        metrics.inc("fallback_client_content")

    if len(text) > deps.settings.content_max_chars:
        return Outcome(413, detail="document too large")

    doc_ver = deps.store.resolve_doc_version(compute_doc_version(text))
    existing = deps.store.get_summary(doc_ver)
    if existing is not None:
        metrics.inc("cache_hit_docversion")
        if source_verified:
            deps.store.mark_source_verified(doc_ver)
            deps.store.map_url(url_key, doc_ver, final_url)
        return await _serve(deps, existing, url_key, language)

    plausibility = check_plausibility(
        text, deps.settings.min_words, deps.settings.plausibility_min_density
    )
    if not plausibility.ok:
        metrics.inc("rejected_not_legal")
        return Outcome(422, detail="content does not look like a legal agreement")

    hits = keyword_hits(text, deps.taxonomy)
    simhash = simhash64(text)
    near = _near_duplicate(deps, simhash, text, hits)
    if near is not None:
        metrics.inc("cache_hit_neardup")
        deps.store.add_alias(doc_ver, near.doc_version)
        if source_verified:
            deps.store.map_url(url_key, near.doc_version, final_url)
        return await _serve(deps, near, url_key, language)

    budget = _reserve_budget(deps, ip, source_verified)
    if budget is not None:
        return budget

    # Cheap LLM gate before the expensive generation: confirm it really is a
    # legal agreement. This is what lets right-click requests on pages the
    # heuristic missed still be trusted enough to promote to the shared cache.
    if deps.settings.llm_legal_check:
        try:
            if not await deps.provider.classify_legal(text):
                metrics.inc("rejected_llm_not_legal")
                return Outcome(422, detail="this page does not look like a legal agreement")
        except ProviderError as e:
            logger.warning("legal-check failed, proceeding to generate: %s", e)

    try:
        doc = await _generate(deps, text, doc_ver, hits)
    except ProviderError as e:
        logger.error("generation failed for %s: %s", url_key, e)
        metrics.inc("generation_failed")
        return Outcome(502, detail="generation failed, try again later")

    deps.store.add_doc_version(
        doc_ver, simhash, len(text), doc.source_language, source_verified, hits, text
    )
    deps.store.save_summary(doc)
    if source_verified:
        # Promotion: mapping url_key -> doc_version is what makes this summary
        # visible to every other user who opens the same URL, including pages
        # the local heuristic never detects (registry, docs/extension.md).
        deps.store.map_url(url_key, doc_ver, final_url)
    metrics.inc("generated")
    return await _serve(deps, doc, url_key, language, source="generated")


def _near_duplicate(
    deps: Deps, simhash: int, text: str, hits: dict[str, list[str]]
) -> SummaryDoc | None:
    """Near-dup serves ONLY if the stored summary still anchors in the new text
    and the new text raises no category the old text didn't (v4 C7)."""
    found = deps.store.find_near_duplicate(simhash, deps.settings.simhash_max_distance)
    if found is None:
        return None
    candidate_version, old_hits = found
    if not set(hits) <= set(old_hits):
        return None
    doc = deps.store.get_summary(candidate_version)
    if doc is None:
        return None
    for category in doc.categories:
        for quote in category.quotes:
            if locate_quote(quote.text, text, deps.settings.anchor_min_score) is None:
                return None
    return doc


def _reserve_budget(deps: Deps, ip: str, source_verified: bool) -> Outcome | None:
    """Per-IP then global daily miss budgets (v4 §6). The unverified fallback
    path spends double per-IP budget — it is the easier path to abuse."""
    cost = 1 if source_verified else 2
    ip_count = deps.store.get_budget(f"ip:{ip}") + cost
    if ip_count > deps.settings.ip_daily_miss_budget:
        metrics.inc("rejected_ip_budget")
        return Outcome(429, detail="daily generation budget for this address exhausted")
    if deps.store.get_budget("global") >= deps.settings.global_daily_miss_budget:
        metrics.inc("rejected_global_budget")
        return Outcome(202, detail="global daily budget reached, queued", retry_after=3600)
    for _ in range(cost):
        deps.store.increment_budget(f"ip:{ip}")
    deps.store.increment_budget("global")
    return None


# ---------------------------------------------------------------- generation


CONTEXT_RADIUS = 300


async def _generate(
    deps: Deps, text: str, doc_ver: str, hits: dict[str, list[str]]
) -> SummaryDoc:
    checklist, model_version = await deps.provider.generate_checklist(text, deps.taxonomy)
    suspicious = _crosscheck_mismatches(checklist, hits)
    if suspicious:
        metrics.inc("crosscheck_retry")
        # Targeted re-check: send only the keyword-hit context for the suspected
        # categories, not the whole document again (v4 C2, far cheaper).
        windows = {cid: _context_windows(text, hits[cid]) for cid in suspicious}
        subset = tuple(c for c in deps.taxonomy if c.id in suspicious)
        try:
            rechecked = await deps.provider.recheck_categories(windows, subset)
            _merge_findings(checklist, rechecked)
        except ProviderError as e:
            logger.warning("recheck failed, keeping first pass: %s", e)
        if _crosscheck_mismatches(checklist, hits):
            metrics.inc("crosscheck_mismatch")

    findings = await _build_findings(deps, checklist, text, _crosscheck_mismatches(checklist, hits))
    return SummaryDoc(
        doc_version=doc_ver,
        source_language=checklist.source_language,
        grade=compute_grade(findings),
        categories=findings,
        tldr=checklist.tldr,
        model_version=model_version,
        generated_at=utcnow(),
    )


def _crosscheck_mismatches(checklist: LLMChecklist, hits: dict[str, list[str]]) -> set[str]:
    reported = {c.id: c.status for c in checklist.categories}
    return {
        cat_id for cat_id in hits if reported.get(cat_id, "not_addressed") == "not_addressed"
    }


def _context_windows(text: str, snippets: list[str]) -> str:
    """Concatenate ±CONTEXT_RADIUS-char windows around each keyword hit, so the
    recheck sees the real surrounding text without resending the whole document."""
    lowered = text.lower()
    spans: list[tuple[int, int]] = []
    for snippet in snippets:
        idx = lowered.find(snippet.lower())
        if idx == -1:
            continue
        spans.append((max(0, idx - CONTEXT_RADIUS), min(len(text), idx + len(snippet) + CONTEXT_RADIUS)))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return " … ".join(text[start:end] for start, end in merged)


def _merge_findings(checklist: LLMChecklist, rechecked: list[LLMCategoryFinding]) -> None:
    by_id = {c.id: c for c in rechecked}
    checklist.categories = [by_id.get(c.id, c) for c in checklist.categories]


async def _build_findings(
    deps: Deps, checklist: LLMChecklist, text: str, suspicious: set[str]
) -> list[CategoryFinding]:
    """Anchor quotes (v4 C4), then verify all claims in ONE batched call (C5)."""
    by_id = {c.id: c for c in checklist.categories}
    drafts: dict[str, CategoryFinding] = {}
    to_verify: list[tuple[str, str, list[str]]] = []
    for category in deps.taxonomy:
        raw = by_id.get(category.id)
        if raw is None or raw.status == "not_addressed":
            drafts[category.id] = CategoryFinding(
                id=category.id,
                title=category.title,
                status="not_addressed",
                confidence="possible" if category.id in suspicious else None,
            )
            continue
        located: list[Quote] = []
        for quote_text in raw.quotes[:3]:
            hit = locate_quote(quote_text, text, deps.settings.anchor_min_score)
            if hit is None:
                metrics.inc("quote_dropped")
            else:
                located.append(Quote(text=quote_text, offset=hit[0]))
        drafts[category.id] = CategoryFinding(
            id=category.id,
            title=category.title,
            status="present",
            severity=raw.severity or "medium",
            explanation=raw.explanation,
            quotes=located,
            confidence="possible",  # upgraded below only if anchored AND verified
        )
        if located and raw.explanation:
            to_verify.append((category.id, raw.explanation, [q.text for q in located]))

    verdict: dict[str, bool] = {}
    if to_verify:
        try:
            verdict = await deps.provider.verify_claims(to_verify)
        except ProviderError:
            metrics.inc("verifier_failed")
    for cat_id, supported in verdict.items():
        if supported:
            drafts[cat_id].confidence = "verified"
    return [drafts[c.id] for c in deps.taxonomy]


# ---------------------------------------------------------------- responses


async def _serve(
    deps: Deps, doc: SummaryDoc, url_key: str, language: str, source: str = "cache"
) -> Outcome:
    payload = _respond(deps, doc, url_key, language, source)
    if language and language != doc.source_language:
        translated = await _translated_payload(deps, doc, url_key, language, source)
        if translated is not None:
            payload = translated
    return Outcome(200, payload=payload)


def _respond(
    deps: Deps, doc: SummaryDoc, url_key: str, language: str, source: str
) -> SummaryResponse:
    row = deps.store.get_doc_version(doc.doc_version)
    verified = bool(row["source_verified"]) if row else False
    disputed = deps.store.is_disputed(doc.doc_version)
    cached = None
    if language and language != doc.source_language:
        cached = deps.store.get_translation(doc.doc_version, language)
    if cached is not None:
        return _apply_translation(doc, cached, url_key, language, verified, disputed)
    return SummaryResponse(
        **doc.model_dump(),
        url=url_key,
        language=doc.source_language,
        source=source,
        source_verified=verified,
        disputed=disputed,
        disclaimer=DISCLAIMER,
    )


async def _translated_payload(
    deps: Deps, doc: SummaryDoc, url_key: str, language: str, source: str
) -> SummaryResponse | None:
    """Translate explanations/tldr on demand — quotes stay source-language (v4 C9)."""
    row = deps.store.get_doc_version(doc.doc_version)
    verified = bool(row["source_verified"]) if row else False
    disputed = deps.store.is_disputed(doc.doc_version)
    strings = deps.store.get_translation(doc.doc_version, language)
    if strings is None:
        explained = [c for c in doc.categories if c.explanation]
        try:
            translated = await deps.provider.translate(
                doc.tldr + [c.explanation for c in explained], language
            )
        except ProviderError:
            metrics.inc("translation_failed")
            return None
        strings = {
            "tldr": translated[: len(doc.tldr)],
            "explanations": {
                c.id: t for c, t in zip(explained, translated[len(doc.tldr) :])
            },
        }
        deps.store.save_translation(doc.doc_version, language, strings)
        metrics.inc("translated")
    return _apply_translation(doc, strings, url_key, language, verified, disputed)


def _apply_translation(
    doc: SummaryDoc, strings: dict, url_key: str, language: str, verified: bool, disputed: bool
) -> SummaryResponse:
    categories = []
    for c in doc.categories:
        translated_explanation = strings.get("explanations", {}).get(c.id, c.explanation)
        categories.append(c.model_copy(update={"explanation": translated_explanation}))
    data = doc.model_dump()
    data.update(categories=[c.model_dump() for c in categories], tldr=strings.get("tldr", doc.tldr))
    return SummaryResponse(
        **data,
        url=url_key,
        language=language,
        source="translated",
        source_verified=verified,
        disputed=disputed,
        disclaimer=DISCLAIMER,
    )
