"""FastAPI app. Routes on the trust boundary (Design v4 §4):
GET /v1/summary (pure cache read), POST /v1/summary (lookup-then-generate),
POST /v1/report (feedback loop), GET /v1/registry (detection digest).
Plus /healthz and /metrics."""

import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from . import metrics
from .clientip import client_ip, reporter_hash
from .config import Settings
from .fetch import fetch_page
from .pipeline import Deps, Outcome, read_cached, request_summary
from .provider import LLMProvider, OpenAICompatProvider
from .schema import ReportRequest, SummaryRequest
from .store import Store
from .taxonomy import load_taxonomy

REGISTRY_HASH_LEN = 16  # hex chars of SHA-256(url_key) published in the digest


def create_app(
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    fetch_fn=None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.deps = Deps(
            store=Store(settings.db_path),
            provider=provider or OpenAICompatProvider(settings),
            settings=settings,
            taxonomy=load_taxonomy(settings.taxonomy_path),
            fetch_fn=fetch_fn or fetch_page,
        )
        yield
        app.state.deps.store.close()

    app = FastAPI(title="Yoola", lifespan=lifespan)
    # The extension reaches the API via host_permissions, not CORS, so it is
    # unaffected by this. The default (empty) blocks third-party websites from
    # driving the money-spending API from a visitor's browser (v4 abuse review).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def caller_ip(request: Request) -> str:
        peer = request.client.host if request.client else None
        return client_ip(peer, request.headers.get("x-forwarded-for"), settings.trusted_proxy_hops)

    def to_response(outcome: Outcome) -> Response:
        if outcome.status == 200 and outcome.payload is not None:
            return JSONResponse(outcome.payload.model_dump(mode="json"), status_code=200)
        headers = {}
        if outcome.retry_after is not None:
            headers["Retry-After"] = str(outcome.retry_after)
        return JSONResponse(
            {"detail": outcome.detail}, status_code=outcome.status, headers=headers
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/metrics")
    def metrics_endpoint():
        return PlainTextResponse(metrics.render_prometheus())

    @app.get("/v1/summary")
    def get_summary(request: Request, url: str, lang: str = "en"):
        return to_response(read_cached(request.app.state.deps, url, lang))

    @app.post("/v1/summary")
    async def post_summary(body: SummaryRequest, request: Request):
        outcome = await request_summary(
            request.app.state.deps, body.url, body.language, body.client_content, caller_ip(request)
        )
        return to_response(outcome)

    @app.post("/v1/report", status_code=204)
    def post_report(body: ReportRequest, request: Request):
        deps = request.app.state.deps
        ip = caller_ip(request)
        # Per-IP daily report cap so reporting cannot be used to flood or grief.
        if deps.store.increment_budget(f"report:{ip}") > deps.settings.ip_daily_report_budget:
            metrics.inc("rejected_report_budget")
            return Response(status_code=429)
        # One vote per (doc, reporter); at the distinct-IP threshold the summary
        # is marked disputed (a warning) — never removed, never auto-regenerated.
        distinct = deps.store.add_flag(
            body.doc_version, reporter_hash(ip, deps.settings.report_salt), body.category, body.reason
        )
        metrics.inc("flags")
        if distinct >= deps.settings.dispute_threshold:
            deps.store.set_disputed(body.doc_version)
            metrics.inc("disputed")
        return Response(status_code=204)

    @app.get("/v1/registry")
    def registry(request: Request):
        """Compact digest of known legal-page URLs. The extension checks the
        current URL against this locally, so it never phones home per page."""
        keys = request.app.state.deps.store.known_url_keys()
        digest = [
            hashlib.sha256(k.encode()).hexdigest()[:REGISTRY_HASH_LEN] for k in keys
        ]
        return {"hash_len": REGISTRY_HASH_LEN, "urls": digest}

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
