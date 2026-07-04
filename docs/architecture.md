# Architecture — the request pipeline

Spec: `Yoola_Design_v4.md` (§2 identity/caching, §3 pipeline). This page maps
the spec to code. The stage ORDER below is a contract: cheap and cacheable
before expensive, every gate before the one LLM call.

## POST /v1/summary — `pipeline.request_summary`

| # | Stage | Module | On failure |
|---|-------|--------|-----------|
| 1 | URL normalize (params sorted for cache-key stability) | `urltools.normalize_url` | 400 |
| 2 | URL cache (fresh per `url_ttl_days`) | `store.get_url_entry` | — (miss ⇒ continue) |
| 3 | Global fetch budget, then server fetch (SSRF-guarded, manual redirects, size-capped) | `store` + `fetch.fetch_page` | 503 (budget) / fallback to `client_content` (quarantined) or 502 |
| 4 | Extract main text, **in a worker thread** (never blocks the loop) | `asyncio.to_thread(extract_main_text)` | — |
| 5 | Size gate (`content_max_chars`) | pipeline | 413 |
| 6 | `doc_version` cache (hash of canonical text, alias-resolved) | `identity` + `store` | — (hit ⇒ serve; verified fetch upgrades quarantined entries) |
| 7 | Regex plausibility gate (legal-marker density) | `plausibility` | 422 |
| 8 | Near-dup: SimHash ≤ `simhash_max_distance` AND stored quotes re-anchor AND no new category keywords | `pipeline._near_duplicate` | — (pass ⇒ alias + serve; else continue) |
| 9 | Budgets: per-IP (fallback path costs 2×), then global | `pipeline._reserve_budget` + `store` | 429 / 202+Retry-After |
| 10 | LLM legal-check (cheap classifier) — gate before the expensive call | `provider.classify_legal` | 422 (failure ⇒ proceed) |
| 11 | ONE generation (checklist prompt) | `provider.generate_checklist` | 502 |
| 12 | Schema validation | `schema.LLMChecklist` | ProviderError ⇒ 502, never cached |
| 13 | Omission cross-check: keyword hits vs `not_addressed` ⇒ **targeted recheck** of only those categories using keyword-hit context windows; persistent mismatch ⇒ `confidence: possible` | `pipeline._crosscheck_mismatches` + `provider.recheck_categories` | — |
| 14 | Anchor quotes: server locates each quote, computes offsets; unlocatable ⇒ drop that quote | `anchor.locate_quote` | — |
| 15 | **Batched** verifier: one call for all present-category claims vs their anchored quotes | `provider.verify_claims` | disagreement/failure ⇒ `possible` |
| 16 | Grade (A–E from severity counts) | `schema.compute_grade` | — |
| 17 | Persist (`doc_versions` incl. extracted `content` + `summaries`; map URL only when source-verified — the promotion step) | `store` | — |
| 18 | Translate `explanation`/`tldr` if requested lang ≠ source lang; cache per language | `pipeline._translated_payload` | translation failure ⇒ serve source language |

## GET /v1/summary — `pipeline.read_cached`

Pure read: URL → alias-resolved `doc_version` → summary (+ cached translation
if present). Never fetches, never calls the LLM, never writes. A **disputed**
summary is still returned (with `disputed: true`) — reports warn, never deny.
This is the path that can later go behind a CDN.

## Detection registry — `GET /v1/registry`

Mapping `url_key → doc_version` (stage 17) *is* the registry: any user opening
that URL gets the cached summary. So other users can auto-detect pages the local
heuristic misses, the server publishes a digest of known verified URLs (truncated
hashes); the extension syncs it and checks the current URL locally — no per-visit
network call, so the "no browsing history" privacy line holds. Quarantined
(unverified) entries are excluded.

## Trust rules encoded above

- **Identity = server-observed content.** Client hashes are never accepted;
  `client_content` is used only when the server cannot fetch, is billed 2× the
  per-IP budget, marked `source_verified: false`, never URL-mapped, and served
  only on byte-identical resubmission until a later successful fetch upgrades it.
- **Confidence is earned:** `verified` = anchored quote + verifier agreement.
  Everything else is `possible`. High-stakes categories can never be `verified`
  without a located quote.
- **Near-dup never serves blind** (v4 C7): re-anchoring + keyword-set check
  first; any doubt ⇒ regenerate.
- **Reports dispute, never demote** (v4 A2): one vote per (doc, reporter-hash),
  per-IP capped; threshold ⇒ `disputed` flag (served with a warning) + review
  queue. Never removes a summary or forces paid work.
- **Extracted source text is stored** (`doc_versions.content`, reverses v4 C10):
  we already fetched it; keeping it avoids re-fetching for regeneration/diffing.
  Only public legal pages are ever fetched. Quotes stay short verbatim excerpts.

## Caching layers

- L1 — extension, `chrome.storage.local`, LRU 50 entries, re-POSTs entries
  older than 7 days so the server can revalidate.
- L2 — (roadmap) in-proc/Redis hot cache. Today SQLite is fast enough.
- L3 — SQLite (`store.py`), WAL, single process. System of record.

## The taxonomy (shared/taxonomy.json)

14 categories, 4 high-stakes (`arbitration`, `unilateral_changes`,
`auto_renewal`, `data_sale_sharing`). Each: `id`, `title`, `hint` (fed to the
prompt), `keywords` (regexes for the omission cross-check — keep high-precision:
a false keyword hit forces a wasted retry, a missed one weakens the injection
defense), `high_stakes`. The server embeds `title` in responses so the
extension needs no copy of this file.
