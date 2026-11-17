"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.api.routes import agents, alerts, auth, decisions, integrations, logic, overview, reports, simulations
from app.config import settings
from app.core.errors import TwinError
from app.db import init_db, session_scope
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.seed import bootstrap_demo_workflows, ensure_demo_environment
from app.workflows.checkpointer import checkpoint_is_durable, close_checkpointer, get_checkpointer
from app.workflows.runner import workflow_runner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("business_twin")

_bootstrap_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bootstrap_task
    await init_db()
    # Initialise the durable checkpoint saver at boot so health/status are accurate
    # and the first workflow does not pay the connection setup cost.
    await get_checkpointer()
    if settings.demo_mode:
        async with session_scope() as session:
            tenant, business = await ensure_demo_environment(session)
            logger.info("Demo environment ready: tenant=%s business=%s", tenant.slug, business.name)
        if settings.demo_auto_bootstrap:
            _bootstrap_task = asyncio.create_task(_run_bootstrap())
    start_scheduler()
    yield
    stop_scheduler()
    if _bootstrap_task and not _bootstrap_task.done():
        _bootstrap_task.cancel()
    await workflow_runner.shutdown()
    await close_checkpointer()


async def _run_bootstrap() -> None:
    try:
        result = await bootstrap_demo_workflows()
        logger.info("Demo workflow bootstrap: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Demo workflow bootstrap failed")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Autonomous multi-agent business intelligence, decision and simulation platform.",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rate_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        key = request.client.host if request.client else "unknown"
        now = time.time()
        window = _rate_windows[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.rate_limit_per_minute:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Request rate limit exceeded", "details": {}}},
                headers={"x-request-id": request_id},
            )
        window.append(now)
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["x-process-time-ms"] = str(round((time.perf_counter() - started) * 1000, 1))
    return response


@app.exception_handler(TwinError)
async def twin_error_handler(request: Request, exc: TwinError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "An unexpected server error occurred", "details": {}}},
    )


for router in (
    auth.router,
    overview.router,
    agents.router,
    alerts.router,
    decisions.router,
    simulations.router,
    logic.router,
    reports.router,
    integrations.router,
):
    app.include_router(router)


@app.get("/api/health", tags=["System"])
async def health() -> dict[str, Any]:
    database = "ok"
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        database = f"error: {type(exc).__name__}"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "database": database,
        "checkpointing": "durable" if checkpoint_is_durable() else "in-memory",
        "llm_provider": settings.llm_provider,
        "scheduler": settings.scheduler_enabled,
        "demo_mode": settings.demo_mode,
    }


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/", include_in_schema=False)
async def root():
    index = frontend_dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/api/docs",
        "message": "Frontend build not found. Run the Vite dev server or build frontend/dist.",
    }


if frontend_dist.exists():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Not found"}})
        candidate = frontend_dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
