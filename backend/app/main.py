from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .api import admin, advice, auth, generation, photos, projects
from .bootstrap import bootstrap
from .config import REPOSITORY_ROOT, get_settings
from .db import engine


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
LOGGER = logging.getLogger("sop.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    bootstrap()
    yield


app = FastAPI(
    title="SOP-IGS API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        LOGGER.exception("request failed id=%s path=%s", request_id, request.url.path)
        raise
    response.headers["X-Request-ID"] = request_id
    LOGGER.info(
        "request id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        round((time.perf_counter() - started) * 1000, 2),
    )
    return response


@app.get("/api/health/live")
def live() -> dict:
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready() -> JSONResponse:
    settings = get_settings()
    checks = {"database": False, "template": False, "storage": False}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = True
    except SQLAlchemyError as exc:
        LOGGER.warning("database readiness check failed: %s", exc)
    checks["template"] = (settings.template_dir / "master.docx").is_file()
    try:
        settings.data_root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(settings.data_root).free / (1024**3)
        checks["storage"] = free >= settings.minimum_free_disk_gb
    except OSError:
        free = 0
    status_code = 200 if all(checks.values()) else 503
    return JSONResponse({"status": "ok" if status_code == 200 else "degraded", "checks": checks, "free_disk_gb": round(free, 1)}, status_code=status_code)


app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(photos.router, prefix="/api")
app.include_router(advice.router, prefix="/api")
app.include_router(generation.router, prefix="/api")

frontend_dist = REPOSITORY_ROOT / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
