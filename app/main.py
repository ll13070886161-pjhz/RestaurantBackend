import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.api.routes import router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.models import Base
from app.db.session import engine


setup_logging(settings.log_level)
settings.ensure_dirs()
Base.metadata.create_all(bind=engine)


def _ensure_runtime_schema() -> None:
    # Lightweight runtime migration for environments without Alembic.
    with engine.begin() as conn:
        inspector = inspect(conn)
        columns = {c["name"] for c in inspector.get_columns("purchase_items")}
        if "consumption_type" not in columns:
            conn.execute(text("ALTER TABLE purchase_items ADD COLUMN consumption_type VARCHAR(20) NULL"))
        if "low_stock_alert_enabled" not in columns:
            conn.execute(text("ALTER TABLE purchase_items ADD COLUMN low_stock_alert_enabled BOOLEAN NOT NULL DEFAULT 0"))
        if "low_stock_threshold" not in columns:
            conn.execute(text("ALTER TABLE purchase_items ADD COLUMN low_stock_threshold NUMERIC(18, 6) NULL"))
        if "low_stock_last_notified_at" not in columns:
            conn.execute(text("ALTER TABLE purchase_items ADD COLUMN low_stock_last_notified_at DATETIME NULL"))
        indexes = {i["name"] for i in inspector.get_indexes("purchase_items")}
        if "ix_purchase_items_consumption_type" not in indexes:
            conn.execute(text("CREATE INDEX ix_purchase_items_consumption_type ON purchase_items (consumption_type)"))


_ensure_runtime_schema()

app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.mount("/", StaticFiles(directory="web", html=True), name="web")


@app.middleware("http")
async def log_request_metrics(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    start = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (perf_counter() - start) * 1000
        logger.exception(
            "request.failed method=%s path=%s request_id=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            request_id,
            elapsed_ms,
        )
        raise

    elapsed_ms = (perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request.done method=%s path=%s status_code=%s request_id=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        request_id,
        elapsed_ms,
    )
    return response
