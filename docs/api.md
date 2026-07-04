# API contract

Pydantic source of truth: `server/src/yoola/schema.py`. Base URL in dev:
`http://127.0.0.1:8000`.

## GET /v1/summary?url=…&lang=…

Pure cache read (no fetch, no LLM, no writes).

| Code | Meaning |
|------|---------|
| 200 | Cached summary (translated variant if cached for `lang`, else source language) |
| 404 | No cached summary — client may POST |
| 409 | Entry demoted by reports; a POST will regenerate |
| 400 | Bad URL |

## POST /v1/summary

```json
{ "url": "https://example.com/terms", "language": "es", "client_content": "…optional…" }
```

`client_content` is the fallback for pages the server cannot fetch — send it
only after a 502 asked for it.

| Code | Meaning |
|------|---------|
| 200 | Summary (from cache, freshly generated, or translated) |
| 202 | Global daily budget reached; `Retry-After` header set |
| 400 | Bad URL |
| 413 | Document too large |
| 422 | Not a legal agreement (plausibility gate) |
| 429 | Per-IP daily generation budget exhausted (cache reads still work) |
| 502 | Fetch failed (`detail` invites `client_content`) or generation failed |

### 200 payload (SummaryResponse)

```json
{
  "schema_version": 1,
  "doc_version": "sha256:…",
  "url": "https://…", "language": "ru", "source_language": "en",
  "source": "cache | generated | translated",
  "source_verified": true,
  "grade": "C",
  "categories": [
    { "id": "arbitration", "title": "Arbitration & class-action waiver",
      "status": "present | not_addressed",
      "severity": "high | medium | low | null",
      "explanation": "… (translated when language ≠ source_language)",
      "quotes": [ { "text": "verbatim source-language quote", "offset": 14231 } ],
      "confidence": "verified | possible | null" }
  ],
  "tldr": ["…3–5 bullets…"],
  "disclaimer": "AI-generated summary. Not legal advice. …",
  "model_version": "gemma-4-31b",
  "generated_at": "2026-07-04T…Z"
}
```

Invariants: quotes are always verbatim source language with server-computed
offsets into the extracted text; `confidence: null` only on `not_addressed`
(a `possible` there = the keyword cross-check disagreed with the model);
the `disclaimer` always rides in the payload.

## POST /v1/report → 204

```json
{ "doc_version": "sha256:…", "category": "arbitration", "reason": "optional, ≤1000 chars" }
```

At `flag_demote_threshold` (default 3) flags, the summary is demoted: GET
returns 409 and the next POST regenerates it (budget-gated).

## Ops

- `GET /healthz` → `{"ok": true}`.
- `GET /metrics` → Prometheus text; key counters: `yoola_generated`,
  `yoola_cache_hit_get/post/docversion/neardup`, `yoola_fetch_failed`,
  `yoola_quote_dropped`, `yoola_crosscheck_mismatch`, `yoola_rejected_*`.

## Example (live smoke)

```bash
curl -X POST localhost:8000/v1/summary -H 'Content-Type: application/json' \
  -d '{"url": "https://www.mozilla.org/en-US/about/legal/terms/mozilla/", "language": "en"}'
# first: "source": "generated" (~1 min); after: "source": "cache" (~10 ms)
```
