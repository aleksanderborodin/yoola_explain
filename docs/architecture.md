# Architecture — the request pipeline

Spec: `Yoola_Design_v4.md` (§2 identity/caching, §3 pipeline). This page maps
the spec to code. The stage ORDER below is a contract: cheap and cacheable
before expensive, every gate before the one LLM call.

## POST /v1/summary — `pipeline.request_summary`

| # | Stage | Module | On failure |
|---|-------|--------|-----------|
| 1 | URL normalize | `urltools.normalize_url` | 400 |
| 2 | URL cache (fresh per `url_ttl_days`) | `store.get_url_entry` | — (miss ⇒ continue) |
| 3 | Server fetch, SSRF-guarded, manual redirects, size-capped | `fetch.fetch_page` | fallback to `client_content` (quarantined) or 502 |
| 4 | Extract main text | `extract.extract_main_text` (trafilatura) | — |
| 5 | Size gate (`content_max_chars`) | pipeline | 413 |
| 6 | `doc_version` cache (hash of canonical text, alias-resolved) | `identity` + `store` | — (hit ⇒ serve; verified fetch upgrades quarantined entries) |
| 7 | Plausibility gate (legal-marker density) | `plausibility` | 422 |
| 8 | Near-dup: SimHash ≤ `simhash_max_distance` AND stored quotes re-anchor AND no new category keywords | `pipeline._near_duplicate` | — (pass ⇒ alias + serve; else continue) |
| 9 | Budgets: per-IP (fallback path costs 2×), then global | `pipeline._reserve_budget` + `store` | 429 / 202+Retry-After |
| 10 | ONE generation (checklist prompt) | `provider.generate_checklist` | 502 |
| 11 | Schema validation | `schema.LLMChecklist` | ProviderError ⇒ 502, never cached |
| 12 | Anchor quotes: server locates each quote, computes offsets; unlocatable ⇒ drop that quote | `anchor.locate_quote` | — |
| 13 | Omission cross-check: keyword hits vs `not_addressed`; one retry with notice, persistent mismatch ⇒ that category `confidence: possible` | `pipeline._crosscheck_mismatches` | — |
| 14 | Verifier pass per present category (claim vs anchored quotes) | `provider.verify_claim` | disagreement/failure ⇒ `possible` |
| 15 | Grade (A–E from severity counts) | `schema.compute_grade` | — |
| 16 | Persist (`doc_versions` + `summaries`; map URL only when source-verified) | `store` | — |
| 17 | Translate `explanation`/`tldr` if requested lang ≠ source lang; cache per language | `pipeline._translated_payload` | translation failure ⇒ serve source language |

## GET /v1/summary — `pipeline.read_cached`

Pure read: URL → alias-resolved `doc_version` → summary (+ cached translation
if present). Never fetches, never calls the LLM, never writes. Demoted entry ⇒
409. This is the path that can later go behind a CDN.

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
- **No full source text at rest** (v4 C10): hashes, SimHash, keyword map, and
  short quotes only.

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
