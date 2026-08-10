"""Application settings.

Every knob is env-overridable with the ``STYLESIGNAL_`` prefix. Defaults are
chosen so that ``uvicorn app.main:app`` works on a bare machine with no
Postgres, no Redis and no S3 — see ``docs/deployment.md`` for the production
swap.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STYLESIGNAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ------------------------------------------------------------
    env: str = "dev"
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30

    # --- Database --------------------------------------------------------
    database_url: str = "sqlite:///./var/stylesignal.db"

    # --- Object storage (§4.9, §5.7) -------------------------------------
    storage_backend: str = "local"  # local | s3
    local_storage_dir: str = "./var/objects"
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None
    s3_endpoint_url: Optional[str] = None
    s3_sse: str = "AES256"
    signed_url_ttl_seconds: int = 3600

    # --- Job queue (§4.2) ------------------------------------------------
    queue_backend: str = "inprocess"  # inprocess | arq
    redis_url: str = "redis://localhost:6379/0"
    inprocess_concurrency: int = 2

    # --- VLM (§7.5) ------------------------------------------------------
    anthropic_api_key: Optional[str] = None
    vlm_model: str = "claude-opus-5"
    vlm_effort: str = "medium"
    vlm_max_tokens: int = 8000
    vlm_max_lint_retries: int = 2
    vlm_timeout_seconds: float = 120.0
    vlm_disabled: bool = False

    # --- Quotas / cost control (§1, §8) ----------------------------------
    free_monthly_scans: int = 5
    scans_earned_per_rating: int = 1
    ratings_per_earned_scan: int = 3
    pro_soft_monthly_cap: int = 300
    max_upload_bytes: int = 12_000_000
    max_longest_edge: int = 1600
    thumb_longest_edge: int = 480

    # --- Community rating loop (§6.5) ------------------------------------
    # §9 defers the feed/rating endpoints to v2, so they ship built but off.
    # Flipping this on activates them and the §1 earn-by-rating free-tier hook.
    community_enabled: bool = False

    # --- Feedback engine version, stamped onto every row (§5.5) ----------
    feedback_engine_version: str = "v1.0.0"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def vlm_enabled(self) -> bool:
        return not self.vlm_disabled and bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
