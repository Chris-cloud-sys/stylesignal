"""FastAPI application — spec §3, §4.2.

The gateway is thin: auth, validation, storage handoff, job enqueue and result
reads. It never runs model inference inline.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal, database_flavour, init_db
from .errors import install_error_handlers
from .jobs import get_queue, reset_queue
from .logging_conf import configure_logging
from .models import ModelVersion
from .routers import auth, billing, feed, media, outfits
from .schemas import HealthResponse

settings = get_settings()
logger = logging.getLogger("stylesignal")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging(json_output=settings.env != "dev")
    init_db()
    _register_feedback_engine_version()

    logger.info(
        "StyleSignal gateway ready",
        extra={
            "env": settings.env,
            "database": database_flavour(),
            "storage": settings.storage_backend,
            "queue": settings.queue_backend,
            "vlm_enabled": settings.vlm_enabled,
        },
    )
    if not settings.vlm_enabled:
        logger.warning(
            "VLM is not configured — every scan will use the templated "
            "fallback (§7.6). Set STYLESIGNAL_ANTHROPIC_API_KEY to enable it."
        )

    yield

    reset_queue()


def create_app() -> FastAPI:
    app = FastAPI(
        title="StyleSignal API",
        version="1.0.0",
        description=(
            "Descriptive style feedback. Output describes how an outfit reads; "
            "it never prescribes changes and never rates the wearer (§7)."
        ),
        lifespan=lifespan,
    )

    # The mobile client is native, so CORS matters only for browser tooling.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.env == "dev" else [],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_error_handlers(app)

    app.include_router(auth.router)
    app.include_router(outfits.router)
    app.include_router(feed.router)
    app.include_router(billing.router)
    if settings.storage_backend == "local":
        app.include_router(media.router)

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            env=settings.env,
            database=database_flavour(),
            storage=settings.storage_backend,
            queue=settings.queue_backend,
            vlm_enabled=settings.vlm_enabled,
            feedback_engine=settings.feedback_engine_version,
        )

    return app


def _register_feedback_engine_version() -> None:
    """Keep §5.8 in sync with the running engine version."""
    db = SessionLocal()
    try:
        existing = db.execute(
            select(ModelVersion).where(
                ModelVersion.kind == "feedback_engine",
                ModelVersion.version == settings.feedback_engine_version,
            )
        ).scalar_one_or_none()

        if existing is None:
            for row in db.execute(
                select(ModelVersion).where(ModelVersion.kind == "feedback_engine")
            ).scalars():
                row.is_active = False
            db.add(
                ModelVersion(
                    kind="feedback_engine",
                    version=settings.feedback_engine_version,
                    is_active=True,
                    meta={
                        "vlm_model": settings.vlm_model,
                        "vlm_effort": settings.vlm_effort,
                        "stages": "preprocess+vlm+rules+lint",
                    },
                )
            )
            db.commit()
        elif not existing.is_active:
            existing.is_active = True
            db.commit()
    finally:
        db.close()


app = create_app()
