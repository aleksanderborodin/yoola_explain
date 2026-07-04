# Extension (Chrome MV3, vanilla JS — no build step)

Principle: **auto-detect, never auto-summarize.** Nothing leaves the page until
the user clicks (pill, or popup button). `background.js` is the only file that
touches the network.

## Files

- `manifest.json` — MV3. Content scripts on `<all_urls>` (detection must see
  every page); host permissions only for the API origins.
- `detect.js` — detection + fallback extraction, loaded before `content.js`.
  Cheap gates first (URL path / title regex), the marker-density scan runs only
  when they pass — never heavy work on random pages. `yoolaExtractText()` is
  the crude `<main>/<article>/body` innerText extractor used ONLY for the
  server-fetch-failed fallback path.
- `content.js` — the pill ("Terms detected — summarize?"), the shadow-DOM side
  panel (grade, alerts-first cards, TL;DR, collapsible full checklist,
  disclaimer), per-category "report wrong", and quote highlighting.
- `background.js` — service worker. Flow per request: L1 → `GET /v1/summary` →
  `POST /v1/summary` (→ on 502, asks content for `clientContent` and retries).
  Owns the L1 LRU cache and the "ToS" badge. `API_BASE` constant at the top
  (dev: `127.0.0.1:8000`).
- `popup/` — manual "Summarize this page" for pages detection missed.

## Message contract (content ⇄ background)

| type | direction | payload | reply |
|------|-----------|---------|-------|
| `detected` | content → bg | — | sets tab badge |
| `summarize` | content → bg | `{url, language, clientContent?}` | `{ok, payload, fromL1?}` \| `{ok:false, needClientContent:true}` \| `{ok:false, detail}` |
| `report` | content → bg | `{docVersion, category}` | `{ok}` |
| `summarize-current` | popup/bg → content | — | triggers the panel |

## L1 cache

`chrome.storage.local`, keys `l1:<url>:<lang>`, LRU-capped at 50 entries.
Entries older than 7 days are treated as stale: the worker re-POSTs so the
server can revalidate (the server re-fetches, and an unchanged page costs
nothing). If the server is unreachable, a stale L1 entry is served rather than
nothing.

## Quote highlighting

Offsets are useless in the live DOM (v4 C4) — `content.js#highlight` searches
for the quote text itself via `window.find`, shrinking the needle
(full → 80 → 50 → 30 chars) until it matches. Failure is silent by design.

## Known limits (roadmap)

`API_BASE` should become an options-page setting; extraction fallback is crude
(server-side fetch is the primary path, so this rarely matters); no
Firefox port yet.
