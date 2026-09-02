"""SQLAlchemy models — spec §5.

Every v2 table is created in v1 (empty) so the v2 rollout in §9 needs no
destructive migration. Columns that are additive to the spec are marked
``SPEC+`` with the requirement that forced them.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# jsonb on Postgres, json on SQLite — §5 asks for jsonb.
JSONB = JSON().with_variant(postgresql.JSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# --- Enum value sets (kept as plain tuples; enforced at the Pydantic edge) ---
OUTFIT_STATUSES = ("pending", "processing", "complete", "failed")
FAILURE_REASONS = (
    "undecodable",
    "no_person",
    "no_garments_detected",
    "internal_error",
)
OCCASIONS = ("casual", "work", "formal", "evening", "athletic", "other")
GARMENT_CATEGORIES = (
    "top",
    "bottom",
    "outerwear",
    "dress",
    "footwear",
    "accessory",
    "headwear",
)
PATTERNS = ("solid", "stripe", "check", "floral", "graphic", "other")
RATING_DIMENSIONS = ("coherence", "occasion_fit", "color")
USER_PLANS = ("free", "pro")
TENANT_PLANS = ("api", "white_label")
MODEL_KINDS = ("preference_model", "feedback_engine")


class Tenant(Base):
    """§5.1 — v2+. Created empty in v1 so white-label needs no migration."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    brand_config: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    scan_limit_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    users: Mapped[List["User"]] = relationship(back_populates="tenant")


class User(Base):
    """§5.2."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="free")
    scans_used_this_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    is_stylist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # SPEC+ — §8 requires auth but §5.2 lists no credential column.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # SPEC+ — §5.2 says "reset by monthly cron". Storing the period the counter
    # belongs to makes the reset lazy and idempotent, so a missed cron run
    # cannot silently deny a user their quota.
    scans_period: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    # SPEC+ — §1 "earn-more-by-rating". Ratings accrue credit; credit converts
    # to bonus scans at STYLESIGNAL_RATINGS_PER_EARNED_SCAN.
    rating_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    earned_scans: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # SPEC+ — native IAP (docs/spec-deviations.md #18). `plan == "pro"` alone
    # isn't enough once a subscription can lapse — `pro_expires_at` is the
    # real source of truth; quota.effective_plan() is what reads it. NULL
    # means "no expiry" (an admin/test override, not a real subscription).
    pro_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    iap_platform: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    iap_product_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    iap_transaction_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    tenant: Mapped[Optional[Tenant]] = relationship(back_populates="users")
    outfits: Mapped[List["Outfit"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Outfit(Base):
    """§5.3."""

    __tablename__ = "outfits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    occasion: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    context_note: Mapped[Optional[str]] = mapped_column(String(280), nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    original_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SPEC+ — §8 "cache by image hash". Keyed with occasion at lookup time,
    # because the notes are occasion-dependent.
    image_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    # SPEC+ — §6.4 requires soft-delete.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    user: Mapped[User] = relationship(back_populates="outfits")
    garments: Mapped[List["Garment"]] = relationship(
        back_populates="outfit",
        cascade="all, delete-orphan",
        order_by="Garment.created_at",
    )
    feedback: Mapped[Optional["OutfitFeedback"]] = relationship(
        back_populates="outfit", cascade="all, delete-orphan", uselist=False
    )
    ratings: Mapped[List["Rating"]] = relationship(
        back_populates="outfit", cascade="all, delete-orphan"
    )

    # --- §5.7 key layout is derivable from the id; only original_key is stored
    @property
    def working_key(self) -> str:
        return "outfits/{0}/working.jpg".format(self.id)

    @property
    def thumb_key(self) -> str:
        return "outfits/{0}/thumb.jpg".format(self.id)

    @property
    def prefix(self) -> str:
        return "outfits/{0}/".format(self.id)


class Garment(Base):
    """§5.4. Populated sparsely in v1 (VLM-derived), richly in v2."""

    __tablename__ = "garments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    outfit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("outfits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    bbox: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    mask_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    colors: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    pattern: Mapped[str] = mapped_column(String(16), nullable=False, default="solid")
    formality: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    attributes: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # SPEC+ — deterministic ordering for garment_notes joins.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    outfit: Mapped[Outfit] = relationship(back_populates="garments")


class OutfitFeedback(Base):
    """§5.5. One-to-one with an outfit."""

    __tablename__ = "outfit_feedback"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    outfit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("outfits.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    overall_read: Mapped[str] = mapped_column(Text, nullable=False)
    color_note: Mapped[str] = mapped_column(Text, nullable=False)
    formality_note: Mapped[str] = mapped_column(Text, nullable=False)
    proportion_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    garment_notes: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    # SPEC+ — §7.7 glanceable result screen (v2 redesign). The long-form
    # fields above are unchanged; these are the always-visible headline.
    # verdict_phrase/verdict_subtitle/focal_point/quick_reads are VLM-authored
    # (or §7.6-fallback-authored); occasion_match/signal_clarity are computed
    # deterministically in app/worker/rules.py, never asked of the VLM — see
    # spec-deviations.md for why.
    verdict_phrase: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verdict_subtitle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    focal_point: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quick_reads: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    occasion_match: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    signal_clarity: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # Internal rule/model signals. Never surfaced raw (§7.3 forbids numeric
    # scores in user-facing output).
    signals: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    outfit: Mapped[Outfit] = relationship(back_populates="feedback")


class PasswordResetCode(Base):
    """SPEC+ — §8 requires auth but the spec text has no reset flow. A
    short-lived, single-use, attempt-limited 6-digit code, not a long opaque
    token — see docs/spec-deviations.md."""

    __tablename__ = "password_reset_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Wrong guesses against this one code — capped independently of the
    # per-email rate limit, since 6 digits is only 1e6 possibilities.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Rating(Base):
    """§5.6. Schema live in v1; endpoints activate in v2."""

    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint(
            "outfit_id", "rater_id", "dimension", name="uq_rating_outfit_rater_dim"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    outfit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("outfits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rater_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dimension: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    outfit: Mapped[Outfit] = relationship(back_populates="ratings")


class ModelVersion(Base):
    """§5.8. Registry for the preference model and feedback engine."""

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
