"""Application settings.

Every knob is env-overridable with the ``STYLESIGNAL_`` prefix. Defaults are
chosen so that ``uvicorn app.main:app`` works on a bare machine with no
Postgres, no Redis and no S3 — see ``docs/deployment.md`` for the production
swap.
"""
from functools import lru_cache
from typing import Any, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STYLESIGNAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def _strip_string_values(cls, data: Any) -> Any:
        """Defends against a real deploy bug: Render's environment-variable
        UI silently left a trailing newline on a pasted `DATABASE_URL`,
        which turned into a Postgres connection to database "stylesignal\n"
        — a working-looking value that fails at connect time, not at
        paste time. Every env-sourced string gets stripped the same way
        rather than special-casing one field, since the same UI quirk can
        hit any of them (a bucket name, an API key, ...).
        """
        if isinstance(data, dict):
            return {
                key: value.strip() if isinstance(value, str) else value
                for key, value in data.items()
            }
        return data

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
    # boto3/botocore defaults (60s connect, 60s read, up to 5 legacy-mode
    # retries on a retryable error) are generous enough that a transient R2
    # hiccup can silently retry for minutes without ever raising — the same
    # hidden-latency-multiplier shape as the Anthropic SDK's own default
    # max_retries (see vlm.py). storage.get() is the first call the pipeline
    # makes, before any VLM work starts, so this was a plausible unaccounted
    # contributor to outfits observed stuck at "processing" for 600s+ with no
    # exception ever recorded in debug_last_error.
    s3_connect_timeout_seconds: float = 10.0
    s3_read_timeout_seconds: float = 30.0
    s3_max_attempts: int = 2

    # --- Job queue (§4.2) ------------------------------------------------
    queue_backend: str = "inprocess"  # inprocess | arq
    redis_url: str = "redis://localhost:6379/0"
    inprocess_concurrency: int = 2
    # The inprocess queue isn't durable across a restart/deploy (see
    # docs/deployment.md) — a job running when the process is torn down
    # just vanishes, leaving its outfit stuck at pending/processing
    # forever with nothing to ever mark it failed. This is the read-time
    # backstop: comfortably above the worst case of vlm_timeout_seconds x
    # (1 + vlm_max_lint_retries) so a genuinely slow-but-alive scan is
    # never mistaken for an orphaned one.
    stale_processing_timeout_seconds: int = 480

    # --- Rate limiting (§8) ------------------------------------------------
    # inprocess under-counts across more than one gateway worker; point it at
    # redis (same STYLESIGNAL_REDIS_URL above) before running more than one.
    ratelimit_backend: str = "inprocess"  # inprocess | redis

    # --- VLM (§7.5) ------------------------------------------------------
    anthropic_api_key: Optional[str] = None
    vlm_model: str = "claude-opus-5"
    vlm_effort: str = "medium"
    vlm_max_tokens: int = 8000
    vlm_max_lint_retries: int = 2
    vlm_timeout_seconds: float = 120.0
    vlm_disabled: bool = False

    # --- Quotas / cost control (§1, §8) ----------------------------------
    # Raised 10 -> 50 for the device-testing pass around the §7.8/§7.9
    # redesign (2026-08-30) — a deliberately temporary bump, not a pricing
    # decision; see docs/spec-deviations.md #17. Drop it back down once
    # testing wraps.
    free_monthly_scans: int = 50
    scans_earned_per_rating: int = 1
    ratings_per_earned_scan: int = 3
    pro_soft_monthly_cap: int = 300
    max_upload_bytes: int = 12_000_000
    max_longest_edge: int = 1600
    thumb_longest_edge: int = 480

    # --- Outbound email (SPEC+ — password reset) --------------------------
    # console | resend. console just logs the code (see app/email.py);
    # resend sends a real email via the Resend API.
    email_backend: str = "console"
    resend_api_key: Optional[str] = None
    email_from: str = "StyleSignal <onboarding@resend.dev>"

    # --- Community rating loop (§6.5) ------------------------------------
    # §9 defers the feed/rating endpoints to v2, so they ship built but off.
    # Flipping this on activates them and the §1 earn-by-rating free-tier hook.
    community_enabled: bool = False

    # --- Native in-app purchases (SPEC+, approved 2026-08-30) -------------
    # See docs/spec-deviations.md #18. Both stores' real product IDs are set
    # here (not hardcoded in app.billing) so a sandbox vs. production
    # product can be swapped per environment without a code change.
    pro_monthly_price_usd: float = 4.99
    iap_product_id_ios: str = "stylesignal_pro_monthly"
    iap_product_id_android: str = "stylesignal_pro_monthly"
    # App Store Connect -> your app -> App Information -> App-Specific
    # Shared Secret. Needed to verify receipts via verifyReceipt.
    apple_shared_secret: Optional[str] = None
    # Play Console package name (e.g. "com.stylesignal.app") and a Google
    # Cloud service account's JSON key (the whole file's contents, as one
    # env value) with access to the Play Developer API for that app.
    google_play_package_name: Optional[str] = None
    google_play_service_account_json: Optional[str] = None

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
