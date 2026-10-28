import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import auth, conversations, documents, resources
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging, trace_id_var
from app.db.session import SessionLocal, engine
from app.services.embeddings import get_embeddings
from app.services.evaluation import ensure_sample_dataset
from app.services.jobs import recover_stuck_work
from app.services.worker import worker_loop

logger = logging.getLogger(__name__)
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    async with engine.begin() as connection:
        await connection.execute(text("SELECT 1"))
    await recover_stuck_work()
    async with SessionLocal() as session:
        async with session.begin():
            await ensure_sample_dataset(session)
    stop_event = asyncio.Event()
    worker = None
    if settings.resolved_worker_mode == "embedded":
        worker = asyncio.create_task(worker_loop(stop_event))
        logger.info("embedded worker started", extra={"component": "worker"})
    yield
    stop_event.set()
    if worker is not None:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
    await engine.dispose()


def create_app() -> FastAPI:
    docs_url = None if settings.environment == "production" else "/docs"
    app = FastAPI(title="ContextAI API", version="1.0.0", lifespan=lifespan, docs_url=docs_url, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def protect_and_trace(request: Request, call_next):
        trace_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        trace_id_var.set(trace_id)
        if request.method in UNSAFE and request.url.path.startswith("/api/"):
            if request.headers.get("x-requested-with") != "contextai":
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "csrf_failed",
                            "message": "Missing required client header.",
                            "trace_id": trace_id,
                        }
                    },
                )
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled request error", extra={"component": "api", "error_category": "unhandled"})
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error", "message": "Something went wrong.", "trace_id": trace_id}},
            )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request",
            extra={
                "component": "api",
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        response.headers["X-Request-ID"] = trace_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError):
        headers = {"Retry-After": "60"} if exc.status_code == 429 else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "trace_id": trace_id_var.get()}},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request: Request, exc: RequestValidationError):
        details = [
            {"loc": [str(item) for item in error.get("loc", [])], "msg": error.get("msg"), "type": error.get("type")}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request is invalid.",
                    "details": details,
                    "trace_id": trace_id_var.get(),
                }
            },
        )

    @app.get("/health")
    async def health():
        embedding = get_embeddings().status()
        return {
            "status": "ok",
            "service": "contextai-api",
            "embedding_provider": embedding["provider"],
            "embedding_warning": embedding["warning"],
            "llm_configured": settings.llm_configured,
        }

    @app.get("/ready")
    async def ready():
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "ready"}

    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(conversations.router, prefix=api_prefix)
    app.include_router(documents.router, prefix=api_prefix)
    app.include_router(resources.router, prefix=api_prefix)
    return app


app = create_app()
