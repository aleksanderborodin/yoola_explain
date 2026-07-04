# Yoola — Design & Goals

**On-Demand AI Terms-of-Service Summarizer**

Version 3.0 · Self-Contained Implementation Spec · June 2026

> This document supersedes all prior versions. It is self-contained: a team should be able to build Yoola from this alone, including the corrections and mitigations that earlier drafts lacked.

---

## 0. Two principles to internalize first

Everything below follows from these. If a decision seems arbitrary, trace it back to one of them.

1. **The cache is the product; the LLM is the fallback.** The only operation that costs money is generating a *new* summary. Almost everything else is a cache read. Every decision exists to keep generation rare.
2. **Content is the only source of truth.** A summary is identified by a fingerprint of the document content — never by domain, URL, or any client-supplied value. The server computes the fingerprint itself, and trusts nothing the client asserts.

A third principle governs how we talk about the product:

3. **Honesty over magic.** Yoola surfaces the alarming parts of a legal document faster and shows you exactly where they are. It does not "read it so you don't have to." Correctness is *managed*, not *solved* — design and copy must reflect that.

---

## 1. Goals & non-goals

### Goals
- Give a user a short, structured, plain-language summary of any legal-agreement page — **alarming clauses first**, each traceable to the source text.
- Make the common case **instant, free to the user, and free to operate** (served from cache, often fully offline).
- Guarantee operating cost **can never exceed a known daily ceiling**, and that a single attacker **cannot deny the service to everyone** by draining that ceiling.
- Be **honest and legally defensible** about what summaries are and are not.

### Non-goals
- Not legal advice; never a replacement for reading the original.
- Not a general-purpose LLM proxy, summarizer, or translator.
- Does not collect browsing history — only the specific legal pages a user chooses to summarize.
- **No BYOK.** Exactly one inference path: the server's.
- v1 does **not** attempt extraction from iframes, shadow DOM, or authenticated/paywalled pages — it detects them but declines rather than extract garbage.

---

## 2. Trust model — read before anything else

This is where the subtle, expensive mistakes live.

### 2.1 Integrity ≠ correctness — two different problems

| Problem | Question | Solved by |
|---|---|---|
| **Integrity** | Did the summary arrive unmodified; is it the one we generated? | HTTPS (+ optional server signing) |
| **Correctness** | Is the summary actually *true to the source document*? | Grounding + agreement + feedback loop (§6) |

A fingerprint gives **neither**. It only tells you "this is the document I think it is." It says nothing about whether the summary is true. Never conflate them.

### 2.2 Content is the only identity
- The fingerprint is computed **server-side** from the bytes the client actually sent. Any client-supplied hash is ignored.
- `domain` and `url` are **descriptive labels only** — stored for display and source-linking, never used to decide legitimacy or to key the cache. Clients can lie about both; it does not matter.

### 2.3 Only the server writes summaries
- Clients submit **document content**. They never submit summaries.
- Only the server generates and writes summaries, and only after grounding-verification (§6).
- There is no user-authored write path into the shared cache. This closes cache poisoning at the source.

### 2.4 Registry trust is earned, not asserted (corrects a real hole)
The registry of "known legal pages" must not accept a page on one client's say-so — the plausibility gate is only keyword density and is trivially spoofable. Therefore:
- Registry entries are keyed by **content fingerprint**, not URL. A site can *claim* `evil.com/terms` is a ToS, but it cannot impersonate a *known* document.
- A page is promoted to the registry only after the **same fingerprint is seen from N independent sources** (distinct IP ranges), or after human review. Keyword-stuffed junk that nobody else visits is never promoted.

---

## 3. The LLM request model

One model, no alternatives: **centralized, cache-first.** The server holds the only provider key; every generation bills the operator; a single shared cache means one generation serves all users.

Every request resolves to one of:
1. **Cache hit** — a matching summary exists (client bundle, per-user cache, or server). Served directly, no LLM call. Free and effectively unlimited. **The vast majority of real traffic.**
2. **Cache miss** — a genuinely new or changed document. The server pays for **one** generation, gated by the budget controls in §8, then caches it so it's paid for at most once.

> **Economic core:** the only operation that costs money is a cache miss. Every abuse defense targets that single path. A cache hit is a disk/memory read — abuse it freely, it costs nothing.

**Provider abstraction:** application code never calls a vendor directly. All inference goes through an internal `LLMProvider` interface (OpenRouter is the reference). Keeps the key server-side, allows model swap/load-balancing without code changes, leaves room for a self-hosted model later.

---

## 4. Fingerprinting & near-duplicate matching (the linchpin)

The cache hit rate lives or dies here. Two users on the same ToS page get **different** DOM text — A/B tests, injected banners, localized chrome, logged-in vs out, whitespace differences. Exact-hash keying would treat these as different documents and regenerate the "same" ToS dozens of times, quietly destroying the economics. Mitigation is a two-stage identity:

### 4.1 Canonical extraction (must be identical client & server)
1. Run the page through **Readability** (Mozilla's reader-mode library) to isolate the main legal content and drop nav, banners, cookie notices, and chrome.
2. Lowercase; collapse all whitespace runs to a single space; trim.
3. UTF-8, NFC Unicode normalization.
4. Ship this function as **one shared spec with a frozen test-vector suite**; client and server must pass the same vectors. *A mismatch here silently halves the hit rate — this is the highest-risk code in the project.*

### 4.2 Two-stage key: exact + near-duplicate
- **Exact key:** `SHA-256(canonical_text)`. Fast path for byte-identical content.
- **Near-duplicate key:** a **SimHash/MinHash** signature over canonical-text shingles. On an exact miss, the server checks for a stored summary whose signature is within a small Hamming/Jaccard distance. If found, **reuse it** (cosmetic differences shouldn't trigger generation). This both lifts the hit rate and makes misses *hard to force* — trivial content mutations still collide.

> Net effect: cosmetic variation maps to one summary; only a *substantively* different document triggers a paid generation.

---

## 5. Caching — every level

Four layers, fastest to slowest; a request stops at the first hit.

| Level | Location | Scope | Storage | Network? |
|---|---|---|---|---|
| **L0 — Bundle** | Extension (shipped) | Top popular agreements, baked into the build | Bundled JSON | No |
| **L1 — Per-user** | Extension (runtime) | Everything this user has viewed | `chrome.storage.local` | No |
| **L2 — Hot** | Backend | Most-requested entries, in memory | Redis (scale) / in-proc (MVP) | Server-internal |
| **L3 — Durable** | Backend | Every summary ever generated (system of record) | SQLite (MVP) / Postgres (scale) | Server-internal |

### 5.1 Key
```
exact_key = SHA-256(canonical_text)
simhash    = SimHash(canonical_text)        # near-dup fallback
language   = canonical artifact is English (see §7); others derived
```
- The **canonical stored artifact is the English structured summary.** Other languages are produced by **translating the short summary** (see §7), not by re-running extraction per language. This kills the "generate the same ToS 20× for 20 languages" cost blowup.
- `model_version` is a **field on the entry, not part of the key** (see §5.4).

### 5.2 L0 — baked-in bundle (offline popular set)
- Ship summaries for the **top tens-to-low-hundreds** of agreements (not thousands — download size matters).
- Entry: `{ exact_key, simhash, summary, recorded_hash, schema_version, domain, url }`.
- On a registry-known page: hash live canonical text, compare to `recorded_hash`. **Match** → render offline, zero cost. **Mismatch** → terms changed → normal cache miss → server. Refreshed on each extension release; need only be **correct-or-defer**, which the hash check guarantees.

### 5.3 L1 — per-user cache
- After any summary is shown, store it keyed by `exact_key`. Revisit → instant, offline. LRU eviction with a few-MB cap.

### 5.4 Invalidation, freshness, model upgrades
- Summaries are **immutable per key**. A changed agreement yields a new fingerprint → new entry; the old one stops being requested. Self-correcting; no complex invalidation.
- **Model upgrades do not wipe the cache.** `model_version` is stored, not keyed. On access, an entry generated by an old model is **served instantly** and **lazily regenerated in the background** — with a **capped refresh rate** so an upgrade never stampedes the whole popular set at once.

### 5.5 Why the hit rate is high
A handful of services account for most legal-page views. Once each popular agreement is summarized once (English) + cheaply translated on demand, nearly every future visit is an L0/L1/L2 hit. The long tail is bounded by §8. **Operator marginal cost trends toward zero as the user base grows.**

---

## 6. Correctness, grounding & the feedback loop

Fingerprinting secures *which document*; this secures *is the summary true*. With current models you cannot trust free-written summaries of legal text. Defenses, strongest first:

### 6.1 Offset-based grounding (corrects the brittle-substring flaw)
- For each **key point** and especially each **alert**, the model returns **character offsets into the exact text we sent it** (not the normalized text) plus the quoted span.
- The server verifies the span **exists at that offset in the original extracted text** (offsets can't be paraphrased away). Fuzzy token-overlap is the fallback check, not exact substring.
- **A failed anchor drops that single point** — it does *not* reject the whole summary. One bad quote must never force a full regeneration.

### 6.2 Two-pass agreement for high-stakes alerts
- Run **two cheap generations**; **cache only the alerts both passes agree on**. Disagreement → keep the point but mark it **"possible — verify."**
- High-stakes categories (arbitration / class-action waiver, auto-renewal, data sale, unilateral term changes) require a **verified anchor**, or they are downgraded to "possible — verify" rather than asserted.

### 6.3 Schema validation
- LLM output must match the schema (§7.3); malformed/incomplete output is rejected and never cached. Pydantic.

### 6.4 Constrain the task
- **Extractive**, not evaluative ("what does this document say about X", not "is this good"). Low temperature. Explicitly allow `"not addressed in this document"` — a model permitted to say "not present" hallucinates far less.

### 6.5 The user feedback loop (the part earlier drafts missed)
- Every summary has a **"report wrong"** control. A flagged entry is **auto-demoted** (stop serving) and queued for regeneration or human review.
- Flags feed a quality signal per entry; repeatedly-flagged documents get prioritized review. This is what turns correctness from a static disclaimer into a managed process.

### 6.6 Disclaimer in the data
- The not-legal-advice disclaimer is a **field in the response payload**, so it cannot be dropped in rendering.

---

## 7. Languages — generate once, translate cheap

- **Do not pre-generate every language.** Most languages get near-zero traffic for a given document.
- The **canonical artifact is the English structured summary** (the expensive full-document pass happens once).
- Other languages are produced **on first demand** by **translating the short structured summary** (~200 words), not by re-extracting the whole document. Cheap, fast, cached per language thereafter.
- Source anchors stay pointing at the original-language source text; translated points link back to the same spans.

---

## 8. Abuse prevention & budget robustness

Only the cache-miss path costs money, so only it is defended. The earlier design over-trusted per-client limits and risked self-DoS; this version fixes both.

### 8.1 Layers (most to least important)
1. **Near-duplicate caching (primary).** §4.2 — makes misses *hard to force*; trivial mutations still hit cache.
2. **Proof-of-work on the miss path, from day one (not held in reserve).** A lightweight client-side PoW token is required to *generate*. Imperceptible for one real summary; prohibitive at scale. This is the real defense against identity-rotation, because `client_id` is forgeable.
3. **Per-IP / per-subnet miss budget.** Cheap first filter; cache hits are unlimited and unmetered.
4. **Two separate budgets, not one (fixes self-DoS).** A small **per-IP daily miss budget** *and* a **global** daily ceiling. A single source cannot drain the whole day's budget and deny everyone else.
5. **Input size limit.** Reject/truncate above a few hundred KB. Kills the giant-payload cost attack.
6. **Plausibility gate (server-side).** Cheap legal-marker density check before any LLM call; non-legal content → `422`. Stops use as a free general-purpose LLM/translator.

### 8.2 Graceful degradation (not a hard wall)
When the **global** ceiling is reached: serve any cached/partial result; **queue** the miss; **prioritize first-seen documents over repeat requesters**; return `202` only as a last resort. "No surprise bill" and "still usable" are both first-class.

### 8.3 Note on `client_id`
`client_id` is used **only for UX continuity** (e.g. local state), **not** as a security control — it is trivially regenerated. Security rests on PoW + IP budgets + near-dup caching. The doc must not claim otherwise.

> **Net effect:** an attacker can at worst spend their per-IP budget; forcing global exhaustion requires real distributed resources *and* defeating PoW, and even then legitimate first-seen traffic is prioritized. Any generation they do force becomes a cached public good.

---

## 9. ToS detection — two gates

### 9.1 Gate 1 — client detection (UX filter, best-effort, local, zero network)
Decides whether to **show** the affordance:
- **Registry match (high confidence):** page fingerprint/domain is a known legal page → light up; also unlocks L0.
- **Heuristic fallback:** URL path patterns (`/terms`, `/privacy`, `/eula`, `/legal`, `/conditions`), title/`<h1>` keywords, legal-marker density above threshold, and a min/max length window.
- If neither passes, the icon stays dim. **Not a security boundary** — just keeps the button off recipe blogs.

### 9.2 Gate 2 — server plausibility (enforcement, load-bearing)
On click, the server **independently** runs the legal-marker check where the user can't bypass it. Non-legal content → `422`, no generation, no cost. This — not the client gate — is what actually prevents non-ToS summaries and "mark everything as a ToS" abuse.

### 9.3 The registry
- Server map keyed by **content fingerprint** (not URL): `fingerprint → { is_legal, recorded_hash, seen_sources, ... }`.
- Powers high-confidence detection + pre-identifies popular agreements.
- **Self-grows, but only on earned trust:** promotion requires the same fingerprint from **N independent sources** or human review (§2.4). `recorded_hash` is used only for **freshness**, never as an access check.

---

## 10. Extension UX

### 10.1 Behavior: auto-**detect**, never auto-**summarize**
Auto-summarizing every page would be a privacy disaster (constant content upload), a cost disaster (unrequested LLM calls), and a UX disaster (popups). Detect passively and locally; the **user** triggers. This one decision solves most privacy, cost, and abuse problems at once.

### 10.2 Requests the extension can make
Exactly one network request type: **`POST /v1/summary`** (lookup-then-generate, carrying a PoW token on the miss path). Everything else is local: detection, extraction + canonicalization, hashing, L0/L1 lookup, rendering. No direct-to-provider calls (no BYOK). The server is the only thing the extension talks to, and only on explicit user action.

### 10.3 The user's experience
1. Land on `example.com/terms`. Page loads normally; **nothing interrupts**.
2. Extension shows a quiet signal: toolbar badge or a small corner pill — "📄 Terms detected — summarize?"
3. User clicks (or ignores — optional).
4. Check L0 then L1 → hit renders the side panel in **well under a second, offline**.
5. Local miss → brief "Summarizing…" → server (solve PoW, POST).
6. Panel renders the structured summary.
7. Persistent quiet disclaimer: "AI summary — verify against the original."
8. Click any **alert** to jump to and highlight the exact source clause in the page.
9. A **"report wrong"** control is always available (§6.5). Close → result cached in L1.

### 10.4 Panel layout (priority order)
1. **⚠️ Alerts first** — auto-renewals, arbitration/class-action waivers, broad data-sharing, unilateral changes; sorted by severity; "possible — verify" flags shown honestly. The "should I worry?" answer.
2. **TL;DR** — 3–5 key bullets.
3. **What data they collect** — collapsible.
4. **Your rights** — collapsible.

Each point shows a "verify in page →" link. A subtle badge shows **cache/offline vs freshly generated** — every claim traces to text the user can see; nothing is a black box.

---

## 11. Backend API

One endpoint. **POST** with content in the body (GET-with-content would truncate on long docs).

### 11.1 `POST /v1/summary`
**Request**
```json
{
  "content":   "<full extracted text (pre-canonicalization quotes resolve against this)>",
  "language":  "Spanish",
  "domain":    "example.com",                 // label only, untrusted
  "url":       "https://example.com/terms",   // label only, untrusted
  "pow_token": "<proof-of-work, required on miss path>"
}
```
The server **recomputes** `exact_key` and `simhash` from `content`; ignores any client hash; never trusts `domain`/`url`.

**Success — 200**
```json
{
  "language_code": "es",
  "source": "cache" | "generated" | "translated",
  "schema_version": 1,
  "key_points": [
    { "text": "...", "source_quote": "...", "source_offset": 1234, "confidence": "verified|possible" }
  ],
  "data_collection_summary": "...",
  "user_rights_summary": "...",
  "alerts_and_warnings": [
    { "text": "...", "severity": "high|medium|low",
      "source_quote": "...", "source_offset": 5678, "confidence": "verified|possible" }
  ],
  "disclaimer": "AI-generated summary. Not legal advice. Verify against the original.",
  "model_version": "...",
  "generated_at": "2026-06-13T00:00:00Z"
}
```

**Status codes**

| Code | Meaning | Cause |
|---|---|---|
| `200` | Summary returned | Cache hit, translation, or fresh generation |
| `202` | Queued, retry later | Global ceiling reached (last-resort; cache hits still work) |
| `400` | Bad / missing PoW | Miss path without a valid proof-of-work token |
| `413` | Payload too large | Content over the size limit |
| `422` | Not a legal agreement | Failed server plausibility gate |
| `429` | Rate limited | Per-IP/subnet miss budget exceeded |

### 11.2 Schema (Pydantic, server-side)
```python
class Point(BaseModel):
    text: str
    source_quote: str
    source_offset: int | None
    confidence: Literal["verified", "possible"]

class Alert(Point):
    severity: Literal["high", "medium", "low"]

class Summary(BaseModel):
    language_code: str
    source: Literal["cache", "generated", "translated"]
    schema_version: int
    key_points: list[Point]
    data_collection_summary: str
    user_rights_summary: str
    alerts_and_warnings: list[Alert]
    disclaimer: str
    model_version: str
    generated_at: datetime
```

### 11.3 Server generation pipeline (on cache miss)
```
1.  recompute exact_key + simhash from content
2.  near-dup lookup (L2/L3 within distance threshold) -> reuse if found
3.  plausibility gate          -> 422 if not legal-shaped
4.  size check                 -> 413 if too large
5.  verify proof-of-work       -> 400 if missing/invalid
6.  per-IP miss budget         -> 429 if exceeded
7.  global ceiling             -> 202 (degrade gracefully) if reached
8.  LLM pass A + pass B (low temp, json schema, "may answer 'not present'")
9.  schema-validate            -> reject if invalid
10. ground each point at its offset in the ORIGINAL text;
    drop unverifiable points; keep only alerts both passes agree on
    (others -> confidence="possible")
11. write L3 + L2 (English canonical); update registry seen_sources/recorded_hash
12. if language != en: translate the short summary, cache per language
13. return 200
```

---

## 12. Data handling & privacy (claim matched to architecture)

Earlier drafts over-claimed. The architecture is changed so the claim is true:
- **Public content only.** Activates only on detected public legal pages; never authenticated/paywalled/private.
- **No per-user reading record.** Rate-limit signals (PoW, IP) travel on a path **decoupled from a stable user id**. The server does **not** log `url` + a stable id + content together; the URL is hashed/dropped after the plausibility check. There is no stable `client_id` sent alongside content.
- **No browsing history.** Only the specific legal text the user chooses to summarize is sent.
- **Minimal provider retention.** Provider configured for zero/minimal retention; submitted text isn't kept for training beyond serving the request.
- **No keys on the client.** The provider key lives only on the server.

---

## 13. Legal & compliance
- **Not legal advice.** Non-dismissible disclaimer in the payload; explicitly non-exhaustive; directs users to the original.
- **Accuracy & traceability.** Offset-grounding + two-pass agreement + "verify" flags + user "report wrong" loop (§6). Copy never claims certainty.
- **Copyright.** Summaries are transformative restatements, not reproductions. Yoola stores summaries, not copies of source agreements.
- **Liability posture.** Yoola's own terms disclaim accuracy warranties and limit liability, consistent with the framing.
- **Data protection (GDPR/CCPA).** Minimal-data design (public text, no stable per-user record, minimal retention) supports compliance; a published privacy policy states exactly what is processed, why, and for how long.

---

## 14. Technology stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python + FastAPI | Async suits LLM-bound work; Pydantic = free schema validation |
| Inference | Provider gateway (OpenRouter ref) behind `LLMProvider`; open-weight default | Key server-side; swap models freely |
| Hot cache | In-proc (MVP) → Redis (scale) | Sub-ms popular hits |
| Durable store | SQLite (MVP) → Postgres (scale) | System of record; one English generation per document |
| Near-dup index | SimHash/MinHash | Fuzzy cache hits; hard-to-force misses |
| Extraction | Mozilla Readability | Robust main-content isolation across messy real pages |
| Fingerprint | SHA-256 of canonical text | No review friction; same speed as MD5 |
| Client | Manifest V3 extension, JS | Extract + canonicalize locally so server gets clean input |

---

## 15. Build order

| Phase | Scope | Done when |
|---|---|---|
| **1 — Core backend** | FastAPI, `POST /v1/summary`, SQLite L3, provider gateway, **shared canonicalization + frozen test vectors**, schema validation, size + plausibility gates, server-side fingerprinting | A new ToS generates once (English) and serves from cache thereafter, with a working disclaimer |
| **2 — Extension core** | MV3: heuristic detection, Readability extraction + shared canonicalization, local hash, `POST`, side-panel render, L1 cache | Detect → click → summary; revisits hit L1 offline |
| **3 — Correctness** | Offset grounding, two-pass agreement, "verify" flags, **"report wrong" feedback loop**, "verify in page" UI | Every alert traces to verified source text; users can flag errors and demote bad entries |
| **4 — Budget & abuse** | Proof-of-work on miss path, per-IP + global dual budgets, graceful degradation, decoupled privacy path, metrics | Cost provably capped; a single source can't DoS everyone; privacy claim holds |
| **5 — Scale & reach** | Near-dup (SimHash) keying, registry with N-source promotion, L0 bundle, lazy model-upgrade refresh, on-demand cheap translation | Popular sites resolve offline; misses hard to force; languages cheap; model upgrades don't stampede |

---

## 16. Summary of decisions (and what each one fixes)

- **Centralized, cache-first; no BYOK.** One inference path.
- **Content is the only identity; server recomputes the fingerprint.** Domain/URL untrusted. → no cache confusion.
- **Only the server writes summaries.** → no cache poisoning.
- **Registry trust earned (N independent sources, fingerprint-keyed).** → fixes auto-registration poisoning.
- **Two-stage exact + near-duplicate key; Readability + frozen test vectors.** → fixes normalization fragility and makes misses hard to force.
- **English canonical artifact + cheap on-demand translation.** → fixes language cost multiplication.
- **`model_version` stored not keyed; lazy capped refresh.** → fixes cache-wipe-on-upgrade.
- **Offset grounding, drop-the-point on failure; two-pass agreement; "report wrong" loop.** → fixes brittle grounding and the missing correctness process.
- **PoW from day one; dual per-IP + global budgets; graceful degradation.** → fixes forgeable client_id and self-DoS.
- **Privacy path decoupled from stable id; URL not logged with content.** → makes the privacy claim true.
- **Auto-detect, never auto-summarize; one request type.** → privacy, cost, abuse at once.
- **Disclaimer + confidence flags ride in the data.** → honesty that can't be dropped in rendering.
