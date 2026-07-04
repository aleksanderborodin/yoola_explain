# Roadmap — deliberately deferred work

Design v4 Phase 4 items plus operational follow-ups. Nothing here blocks the
MVP; each entry says why it's safe to defer.

## Deploy (next up)

Target box: see `server.md` (gitignored). Plan: install uv, clone to
`/srv/yoola`, `server/.env` with the modelgate key, systemd unit
(`uv run uvicorn --factory yoola.app:create_app`, ONE worker — gotcha #6),
Caddy for TLS + reverse proxy, ufw 22/80/443. Before public exposure: SSH keys
+ disable password auth, unattended-upgrades, fail2ban. Then flip `API_BASE`
in `extension/background.js`.

## Server

- **Headless-browser fetch fallback** (Playwright pool) for JS-walled pages;
  today those fall back to quarantined client content, which is correct but
  second-class.
- **Freshness re-checks / staleness sweep**: URL TTL currently revalidates only
  when a client POSTs; a periodic job could re-fetch hot URLs and pre-diff.
- **Version-diff surface**: `doc_versions` already retains history and the
  checklist is diffable by construction — expose "what changed since you last
  accepted" (the roadmap's killer feature).
- **Corroboration counting for quarantined entries** (v4 C1): today an
  unverified entry is upgraded only by a later successful server fetch; an
  N-independent-submitters rule would upgrade fetch-blocked sites too. Needs a
  privacy-preserving submitter signal (salted IP hash), so deferred.
- **Redis L2 + Postgres** when SQLite/single-process stops being enough
  (SimHash scan in `find_near_duplicate` is linear — index it then too).
- **Edge caching of GET /v1/summary** (it is already pure); CDN in front.
- **PoW escalation** (v4 C6): designed but unbuilt, behind a feature flag, only
  if budget-exhaustion abuse is actually observed.
- **Lazy model-upgrade refresh** (v4 §2): `model_version` is stored not keyed;
  the capped background regeneration on model change isn't implemented yet.
- **Translation budget**: `translate` calls are cheap and not gated by the
  per-IP miss budget today; add a separate cheap-op budget if abused.
- **Server-side negative cache for 422 verdicts**: a URL judged
  not-a-legal-agreement is remembered per-browser (extension `notLegal`), but
  each NEW user still costs a fetch + `classify_legal`. A TTL'd server-side
  `url_key → not_legal` record would cut that repeat spend.

## Extension

- `API_BASE` as an options-page setting; Firefox (WebExtensions) port;
  text-fragment (`#:~:text=`) highlighting as a `window.find` fallback;
  proper Readability extraction if the fallback path ever matters.

## Testing

- CI (GitHub Actions): fast suite on every push, `-m llm` nightly.
- An injection corpus beyond the single planted-instruction test.
