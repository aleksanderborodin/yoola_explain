# AGENTS.md

> Single source of truth for agents working in this repo. `CLAUDE.md` is a
> symlink to this file (both at the repo root). The code is **two packages**:
> `server/src/yoola/` (FastAPI backend, Python) and `extension/` (Chrome MV3,
> vanilla JS). The shared clause taxonomy lives at `shared/taxonomy.json`.
> This file is a lean **index + contracts**; volatile status lives in
> `docs/gotchas.md` and `docs/roadmap.md`.

> **GOLDEN RULE — update docs in the same change, every time.** Whenever you
> change behavior, an API/message contract, the repo layout, or fix a known
> gotcha (`docs/gotchas.md`): update **this file** and the affected `docs/`
> page in the *same* change — never as a follow-up. A change that leaves a doc
> stale is incomplete. Before finishing any task, re-read the sections you
> touched and fix anything that no longer holds.

## Project

Yoola is an on-demand AI terms-of-service summarizer: a Chrome extension that
detects legal pages and, on user click, shows a **checklist-based, quote-grounded
summary** (alarming clauses first, letter grade, every claim traceable to source
text). The backend is **URL-first and cache-first**: the server fetches public
legal pages itself, generates a summary **once** per document via an
OpenAI-compatible LLM gateway, and serves everyone else from cache.

The spec is `Yoola_Design_v4.md` (Part I = why each decision beat its
alternatives; the `C1…C12` labels in code comments refer to its challenge record;
**Part IV = the v4.1 amendments** — `A1…A6` labels — which supersede earlier
sections: store fetched text, reports dispute-not-demote, trusted-proxy IP +
locked CORS, LLM legal-check, detection registry, batched/threaded efficiency).
`Yoola_Design_v3.md` is kept for history only — do not build from it.

Two invariants trump everything:
1. **The cache is the product; the LLM is the fallback.** Only a cache miss may
   cost money, and each document is paid for at most once.
2. **Server-observed content is the only identity.** URL → server fetch →
   content hash. Client-submitted anything is second-class and quarantined.

## Docs map + reading order

Read this file first, then follow the path for your task. Skim
`docs/gotchas.md` + `docs/roadmap.md` before any change.

- **Touch the request flow / caching / generation** → `docs/architecture.md`
  (pipeline stages + which module owns each gate) → `Yoola_Design_v4.md` §2–3.
- **Touch the API or the payload schema** → `docs/api.md` (endpoint + status-code
  contract) → `server/src/yoola/schema.py` (the Pydantic source of truth).
- **Touch the extension** → `docs/extension.md` (file roles + the
  content↔background message contract).
- **Add/change a clause category** → `shared/taxonomy.json` (id, title, hint,
  keywords, high_stakes) → keyword regexes feed the omission cross-check, so
  keep them high-precision → update `docs/architecture.md` category count and
  the tests in `server/tests/test_taxonomy.py`.
- **Deploy / hosting** → `server.md` (gitignored: SSH creds + box inventory) →
  `docs/roadmap.md` "Deploy" for the plan.
- **Understand scope / what's deliberately NOT built** → `Yoola_Design_v4.md`
  Part I + `docs/roadmap.md`.

## Environment

- Ubuntu; server managed with **uv** (`cd server && uv sync`). Python 3.12.
- Secrets live in `server/.env` (gitignored; template `server/env.example`).
  LLM gateway: **modelgate.ru** (OpenAI-compatible), single model
  `gemma-4-31b` for generation, verification, and translation.
- IDE "package not installed" hints usually mean the editor didn't select
  `server/.venv` — not a project error. `uv run python -m py_compile <file>`
  is the cheap syntax check.

## Repository Map

**`server/src/yoola/` — the backend** (one module per responsibility):

- `app.py` — FastAPI factory (`create_app(settings, provider, fetch_fn)` —
  everything injectable for tests), the 4 routes (`GET`/`POST /v1/summary`,
  `POST /v1/report`, `GET /v1/registry`) + `/healthz` + `/metrics`. CORS from
  settings; client IP via `clientip`.
- `clientip.py` — real client IP behind a trusted proxy (`X-Forwarded-For`) +
  salted reporter-hash for dedup. See gotcha #10.
- `pipeline.py` — **the heart**: `read_cached` (GET, pure read) and
  `request_summary` (POST: cache → fetch → gates → generate → cache). Order of
  stages is a contract; see `docs/architecture.md`.
- `config.py` — pydantic-settings; every knob (budgets, thresholds, models).
- `identity.py` — canonicalize / `doc_version` (SHA-256) / SimHash64.
- `urltools.py` — URL normalization (the cache key) + SSRF guard.
- `fetch.py` — server-side page fetch, manual redirects (SSRF check per hop),
  size cap. Headless fallback is roadmap.
- `extract.py` — trafilatura main-content extraction (server-side only).
- `plausibility.py` — legal-marker density gate (the non-LLM enforcement point).
- `taxonomy.py` — loads `shared/taxonomy.json`; `keyword_hits` = the regex
  prefilter that powers the omission cross-check.
- `schema.py` — all Pydantic contracts + `compute_grade` (A–E).
- `provider.py` — `LLMProvider` ABC + `OpenAICompatProvider` (retries,
  think-block stripping, response_format fallback). The ONLY door to inference.
  Ops: `classify_legal` (cheap gate), `generate_checklist`, `recheck_categories`
  (targeted, context-only), `verify_claims` (batched — one call), `translate`.
- `anchor.py` — server-side fuzzy quote location (rapidfuzz); quotes in, offsets out.
- `store.py` — SQLite system of record (urls / doc_versions / aliases /
  summaries / translations / flags / budgets). Stores the extracted source text
  on `doc_versions.content` (v4 A1) so regeneration/diffing needs no re-fetch;
  `known_url_keys` powers the registry.
- `metrics.py` — in-proc counters → `/metrics` (hit rate is THE KPI).

**`server/tests/`** — `conftest.py` (FakeProvider + fetch fakes + client
factory), unit tests per module, `test_api.py` (every v4 economic/trust claim),
`test_llm_real.py` (marked `llm`: real modelgate calls incl. injection
resistance; auto-skip without key).

**`extension/`** — `manifest.json` (MV3), `detect.js` (cheap gates → density
scan; crude fallback extractor), `content.js` (pill + shadow-DOM panel + quote
highlight + report), `background.js` (service worker: the ONLY network caller;
GET-then-POST; L1 LRU cache in `chrome.storage.local`), `popup/`, `images/`.
Contract details: `docs/extension.md`.

**`shared/taxonomy.json`** — the 14 clause categories (4 high-stakes). Canonical;
the server reads it directly, the extension only renders what the server sends.

## Mental Model (one request)

```
user click
 └─ background.js: L1? → GET /v1/summary (pure read)? → POST /v1/summary
     └─ pipeline.request_summary:
         url cache (fresh?) → serve
         server FETCH (SSRF-guarded) → extract → hash
           └─ fetch fails → client_content fallback (quarantined, 2× budget)
         doc_version cache → serve      near-dup + re-anchor check → serve
         plausibility gate (422) → budgets (429 / 202+Retry-After)
         → LLM legal-check (422) → ONE generation → schema validate
         → omission cross-check (targeted recheck of flagged categories)
         → anchor quotes (drop unlocatable) → BATCHED verifier
         → grade → store (incl. content) → map url→doc (promotion) → serve
```

- Summaries are immutable per `doc_version`; a changed page is a new version.
- `confidence: "verified"` requires an anchored quote AND verifier agreement;
  anything less is `"possible"` — never silently asserted.
- Reports mark a summary `disputed` (served with a warning), never remove it or
  force paid regeneration (v4 A2).
- Translations: `explanation`/`tldr` strings only, cached per language; quotes
  stay verbatim source language, always.

## Design Rules

Keep the code small, explicit, and direct.

- Prefer readable straight-line code over clever abstractions; add a class or
  helper only when it has a real responsibility.
- Keep functions focused and under ~60 lines; signatures ≤ 4 params (bundle
  into `Deps`-style dataclasses when more is needed).
- Early returns over nesting; no hidden side effects between modules.
- A rule lives in the layer that owns it: gates in `pipeline.py`, shapes in
  `schema.py`, knobs in `config.py`, categories in `shared/taxonomy.json`.
- Every trust/economic behavior gets a test in `test_api.py` when added.
- Never log URL + content + a stable client id together (privacy claim, v4 §7).
- Only public legal pages are ever fetched/stored; never authenticated/private
  content (this is what makes storing `doc_versions.content` acceptable, v4 A1).

## Where To Put Changes

- New request-flow behavior → `pipeline.py` (and its stage order is part of the
  spec — update `docs/architecture.md`).
- New API fields → `schema.py` first, then producers/consumers.
- New settings → `config.py` with a sane default; document only if non-obvious.
- New clause category → `shared/taxonomy.json` + taxonomy tests; nothing else
  should need touching.
- Provider/gateway quirks → `provider.py` only.
- Extension UI → `content.js`; network/caching → `background.js`; detection →
  `detect.js`.

If ownership is unclear, pause and state the intended module before changing it.

## Verification

Use the narrowest check that proves the change.

- Fast suite (no network, <1s): `cd server && uv run pytest -m "not llm" -q`.
- Real-LLM integration (~2–4 min, needs `server/.env` + network):
  `uv run pytest -m llm -q`. Tests are isolated per-DB — see gotcha #3 before
  "fixing" a cross-test cache hit.
- Full: `uv run pytest -q`.
- Live smoke: `uv run uvicorn --factory yoola.app:create_app --port 8000`, then
  POST a real ToS URL (see `docs/api.md` examples); expect `generated` once,
  `cache` in ~10 ms after, counters at `/metrics`.
- Extension: `node --check extension/*.js` for syntax; then load
  `extension/` unpacked at `chrome://extensions` against the local server.

## Status, gotchas & roadmap

- **`docs/gotchas.md`** — known traps (redirect/trailing-slash interplay,
  event-loop reuse in async tests, near-dup aliasing across shared DBs,
  modelgate model availability, DNS TOCTOU). Fix one → delete it there.
- **`docs/roadmap.md`** — deliberately-deferred work (headless fetch fallback,
  Redis L2, edge caching, corroboration counting, ToS;DR seed import,
  version-diff UI, PoW escalation, deploy runbook for the hosting box).

## Running

- Server: `cd server && uv sync && uv run uvicorn --factory yoola.app:create_app --port 8000`.
  Config via `server/.env`; see `server/env.example`.
- Extension: `chrome://extensions` → Developer mode → Load unpacked →
  `extension/`. `API_BASE` in `background.js` points at `127.0.0.1:8000` for
  dev; switch it for the deployed origin (roadmap: make it an option).
- Hosting box (deploy target, nothing installed yet): see `server.md`
  (gitignored) for access + inventory.
