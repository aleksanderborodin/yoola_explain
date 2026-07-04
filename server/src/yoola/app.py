"""FastAPI app. Three routes on the trust boundary (Design v4 §4):
GET /v1/summary (pure cache read), POST /v1/summary (lookup-then-generate),
POST /v1/report (feedback loop). Plus /healthz and /metrics."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from . import metrics
from .config import Settings
from .fetch import fetch_page
from .pipeline import Deps, Outcome, read_cached, request_summary
from .provider import LLMProvider, OpenAICompatProvider
from .schema import ReportRequest, SummaryRequest
from .store import Store
from .taxonomy import load_taxonomy


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
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
    )

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
        ip = request.client.host if request.client else "unknown"
        outcome = await request_summary(
            request.app.state.deps, body.url, body.language, body.client_content, ip
        )
        return to_response(outcome)

    @app.post("/v1/report", status_code=204)
    def post_report(body: ReportRequest, request: Request):
        deps = request.app.state.deps
        count = deps.store.add_flag(body.doc_version, body.category, body.reason)
        metrics.inc("flags")
        if count >= deps.settings.flag_demote_threshold:
            deps.store.demote_summary(body.doc_version)
            metrics.inc("demoted")
        return Response(status_code=204)

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
