# Extension (Chrome MV3, vanilla JS — no build step)

Principle: **auto-detect, never auto-summarize.** Nothing leaves the page until
the user acts (detection tab, popup, or right-click). `background.js` is the only
file that touches the network.

## Triggers (three ways in)

1. **Detection tab** — appears bottom-right when the page is detected (see below).
   On a consent page it reads *Check the terms first?* and summarizes the
   **linked** documents in place (a picker appears when there are several).
2. **Popup — the site dossier.** Clicking the icon lists ALL agreements for
   the current site: documents Yoola has already graded for this host (via
   `GET /v1/directory?host=`, instant, with grade stamps) merged with legal
   links found on the current page. Candidates are deduplicated against the
   graded entries by **where the link leads** (normalized URL, compared
   scheme/www-insensitively) and each is checked against the registry digest —
   a registry hit renders as "✓ Already summarized — opens instantly" (e.g. a
   link to another site's terms), the rest as "? not analyzed yet". Any row
   opens the panel in-page; the panel header then shows **← back to the list**
   (the popup passes its dossier along via `list`). "Summarize this page
   instead" covers the rest.
3. **Right-click** — *Summarize this page with Yoola* on the page, or
   *Summarize linked document with Yoola* on a Terms/Privacy **link** — the
   linked doc is summarized without navigating (the server fetches by URL, so
   being on the page is never required).

## Detection (four signals, cheapest first, none phones home per page)

`detect.js#yoolaDetect()` returns `{kind, links}` with kind
`"heuristic" | "registry" | "links"`, or `null`:
1. cheap local gate (URL path / title regex);
2. marker-density scan (only if #1 passes);
3. **registry membership** — the extension normalizes the current URL, hashes
   it, and checks it against a locally-cached digest of known verified URLs
   (`GET /v1/registry`, synced every few hours by the worker). This is how a
   page one user added via right-click lights up ("Summary available") for
   everyone else even when the heuristic would miss it — with no per-visit
   network call, so the "no browsing history" line holds.
4. **consent context** (`kind: "links"`) — a signup/checkout moment (password
   field, or an "I agree…" checkbox naming terms) that links to legal documents
   (`yoolaFindLegalLinks`, ≤4). Each link is stamped `known` via the same
   registry normalize-and-hash check applied to its **target** URL
   (`yoolaMarkKnown`) so the picker can say "already summarized — opens
   instantly". (A link that reaches a known document only through a redirect
   won't match the digest — the server's alias map still resolves it from
   cache on click.) This closes the registration-page gap: the user reviews
   the terms without leaving the form, and the picker stays one "←" away in
   the panel header after choosing a document. In this remote mode, quote
   buttons become *read at source ↗* and deep-link into the original via a
   `#:~:text=` fragment instead of highlighting the current page.

## Files

- `manifest.json` — MV3. Content scripts on `<all_urls>`; permissions:
  `storage`, `activeTab`, `contextMenus`, `alarms`, `scripting`. Host
  permissions: the API origins + `<all_urls>` (required for
  `scripting.executeScript` self-heal and the background-tab reader; adds no
  install warning beyond the one the content scripts already trigger).
- `detect.js` — detection, URL normalization (mirrors the server), registry
  lookup, and the crude `<main>/<article>/body` fallback extractor
  (`yoolaExtractText`, used ONLY for the server-fetch-failed path).
- `content.js` — the detection tab + the shadow-DOM "dossier" panel: the
  **verdict stamp** (A–E seal, the signature element), alerts-first cards,
  in-brief bullets, collapsible full checklist, disputed/unverified warnings,
  per-clause "report wrong", quote highlighting. Styled to match the website:
  warm paper, ink type, colored stamp seals (one visual system across product).
- `background.js` — service worker. Per request: L1 → `GET /v1/summary` →
  `POST /v1/summary` (→ on 502, content retries with `clientContent`: the
  current page's text, or — for a linked document the server can't fetch —
  `extractViaTab`, which opens the URL in a background tab, lets the user's
  own browser render past the bot wall, pulls the text, and closes the tab).
  Owns the L1 LRU cache, the badge, the right-click menu, and `syncRegistry()`.
  `API_BASE` constant at the top (dev: `127.0.0.1:8000`).
- `popup/` — the site dossier (see Triggers #2), dossier-styled.

## Message contract (content ⇄ background)

| type | direction | payload | reply |
|------|-----------|---------|-------|
| `detected` | content → bg | — | sets tab badge |
| `summarize` | content → bg | `{url, language, clientContent?}` | `{ok, payload, fromL1?}` \| `{ok:false, needClientContent:true}` \| `{ok:false, detail}` |
| `report` | content → bg | `{docVersion, category}` | `{ok}` |
| `summarize-current` | bg → content (via `sendToContent`) | — | panel for the current page |
| `summarize-url` | bg → content (via `sendToContent`) | `{url, label?, list?}` | panel for the linked document; local mode auto-detected when the URL is the current page; `list` (>1 items) enables the header's ← back-to-list |
| `extract-remote` | content → bg | `{url}` | `{ok, content?}` — background-tab read of a document the server can't fetch; feeds the quarantined `client_content` path |
| `popup-open-url` | popup → bg | `{tabId, url, label, list?}` | bg delivers `summarize-url` (injecting if needed) |
| `site-agreements` | popup → bg | `{host}` | `{entries}` from `GET /v1/directory?host=` |
| `page-links` | popup → bg | `{tabId}` | `{links}` via content `get-legal-links` |
| `get-legal-links` | bg → content | — | `{links}` from `yoolaFindLegalLinks()`, each stamped `known` against the registry digest |
| `popup-summarize` | popup → bg | `{tabId}` | `{ok}` — bg delivers `summarize-current`, injecting the content script first if the tab predates the last extension reload (`scripting` permission); `ok:false` only on genuinely uninjectable pages |

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
(server-side fetch is the primary path — now with browser-like headers — and
the background-tab reader covers most bot-walled pages, so this rarely
matters); no Firefox port yet. Chrome's PDF viewer blocks content scripts
entirely, so on a directly-opened PDF the pill/panel cannot appear and the
popup explains the right-click-the-link route (the server itself summarizes
PDFs fine); the same limit means `extractViaTab` cannot read a bot-walled PDF.
