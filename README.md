# Yoola

**On-demand AI terms-of-service summarizer.** A Chrome extension detects legal
pages (ToS, privacy policies, EULAs) and — only when you click — shows a
checklist-based summary: a letter grade, alarming clauses first, and every
claim anchored to a verbatim quote you can jump to in the page.

The backend is **URL-first and cache-first**: the server fetches the public
page itself, generates a summary **once** per document, and serves everyone
else from cache. The LLM is the fallback; the cache is the product.

## Quick start

```bash
# server
cd server && uv sync
cp env.example .env   # add your LLM gateway key
uv run uvicorn --factory yoola.app:create_app --port 8000

# extension: chrome://extensions → Developer mode → Load unpacked → extension/
```

Try it: visit any terms-of-service page, click the "📄 Terms detected" pill.

## Tests

```bash
cd server
uv run pytest -m "not llm" -q   # fast, offline (<1s)
uv run pytest -q                # + real-LLM integration tests (needs .env)
```

## Repo map

| Path | What |
|------|------|
| `server/` | FastAPI backend (Python 3.12, uv) — fetch, gates, generation, cache |
| `extension/` | Chrome MV3 extension (vanilla JS, no build step) |
| `shared/taxonomy.json` | The 14-clause checklist both sides are built around |
| `Yoola_Design_v4.md` | The design spec + the challenge record behind it |
| `AGENTS.md` / `docs/` | Contracts, architecture, API, gotchas, roadmap |

Not legal advice. Summaries are AI-generated and always carry a disclaimer and
per-claim confidence — verify against the original.
