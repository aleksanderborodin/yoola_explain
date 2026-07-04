# Gotchas — known traps & open risks

Fix one → delete it here. Discover one → add it, same session.

1. **Trailing slashes in URLs are load-bearing.** `normalize_url` must NOT
   strip them: sites 301 between slash variants and stripping caused infinite
   redirect ping-pong (Mozilla ToS was the repro). Slash twins converge via the
   content hash instead. Same reason redirect hops in `fetch.py` are followed
   as-is (only scheme + SSRF checked), never re-normalized.
2. **One `asyncio.run()` per httpx AsyncClient.** `OpenAICompatProvider` holds
   a pooled `AsyncClient`; reusing a provider across separate `asyncio.run()`
   loops (e.g. module-scoped pytest fixtures) dies with "Event loop is closed".
   Real-LLM test fixtures are function-scoped, and multi-call tests run all
   calls inside ONE coroutine.
3. **Near-dup aliasing works across tests sharing a DB.** With a module-scoped
   DB, the SimHash matcher (correctly) served one test's document from another
   test's summary — SAMPLE_TOS aliased to its injection-poisoned twin. LLM test
   `settings` are function-scoped (fresh DB per test). If you see a surprise
   `source: "cache"` in a test, suspect DB sharing before suspecting the code.
4. **modelgate model ids ≠ availability.** `/v1/models` lists models whose
   upstream is down (`qwen3-235b` listed but every call returned "Model not
   found on upstream provider"). Sanity-check a model with one real completion
   before switching config. Current model: `gemma-4-31b` (works, no think
   blocks). `_extract_json` already strips `<think>…</think>` for reasoning
   models.
5. **SSRF guard has a DNS TOCTOU window.** `assert_public_host` resolves and
   checks, then httpx re-resolves for the actual connection. A DNS-rebinding
   attacker could swap records between the two. Accepted for now (the fetch
   path only GETs public pages); a resolve-and-pin transport closes it
   (roadmap).
6. **`store.py` assumes a single process.** One SQLite connection + a lock;
   budgets/flags are not safe under multi-worker uvicorn. Run ONE worker until
   the Redis/Postgres step of the roadmap.
7. **Don't `pkill -f uvicorn` from a script whose own command line contains the
   pattern** — it kills the shell. Use `fuser -k 8000/tcp`.
8. **IDE "package not installed" hints** just mean the editor didn't select
   `server/.venv`; `uv run` is authoritative.
9. **`str.lower()` and anchor offsets.** Quote anchoring lowercases both sides
   and assumes length preservation. True for ~all real text, but a few Unicode
   codepoints expand under `lower()`; offsets would drift on such documents.
   Cosmetic risk only (offsets feed nothing security-relevant).
