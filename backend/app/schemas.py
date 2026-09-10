"""Request/response models — spec §6.

The outfit-result contract (§6.2) is stable from v1: v2 populates
``garments[]`` richly instead of sparsely, but the shape does not change.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import CAPTURE_MODES, OCCASIONS, RATING_DIMENSIONS


# --- Auth ------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str


class UpdateSettingsRequest(BaseModel):
    """PATCH /v1/auth/me — currently just the community-sharing default."""

    default_share_public: bool


class PasswordResetRequestRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=200)


class StatusResponse(BaseModel):
    status: str = "ok"


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class QuotaOut(BaseModel):
    plan: str
    scans_used_this_month: int
    monthly_allowance: Optional[int]
    earned_scans: int
    scans_remaining: Optional[int]
    rating_credits: int
    ratings_until_next_scan: int
    # SPEC+ — native IAP (docs/spec-deviations.md #18). Set only while
    # `plan == "pro"`; a lapsed subscription reports as free instead of a
    # past date — see quota.effective_plan().
    pro_expires_at: Optional[datetime] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    plan: str
    is_stylist: bool
    created_at: datetime
    default_share_public: bool


class MeResponse(BaseModel):
    user: UserOut
    quota: QuotaOut


# --- Outfits ---------------------------------------------------------------
class OutfitCreateResponse(BaseModel):
    outfit_id: uuid.UUID
    status: str


class RereadRequest(BaseModel):
    """Re-read the same photo under a different occasion (result-screen
    "change occasion" action). Costs a scan like any other read — see
    outfits.py's reread_outfit for why this can't be a free cache hit."""

    occasion: Optional[str] = None


class PresignedUploadResponse(BaseModel):
    """§6.1 Flow B."""

    outfit_id: uuid.UUID
    upload_url: str
    upload_method: str = "PUT"
    storage_key: str
    expires_in: int


class ColourOut(BaseModel):
    """§6.2 surfaces hex + weight; LAB stays internal to the engine."""

    hex: str
    weight: float


class GarmentOut(BaseModel):
    garment_id: uuid.UUID
    category: str
    colors: List[ColourOut] = Field(default_factory=list)
    pattern: str
    formality: float


class GarmentNoteOut(BaseModel):
    garment_id: Optional[uuid.UUID] = None
    note: str


class MeterOut(BaseModel):
    """§7.7 — a glanceable meter. Computed deterministically (app/worker/rules.py),
    never asked of the VLM; see spec-deviations.md for why."""

    level: str  # strong | partial | off
    score: float


class QuickReadOut(BaseModel):
    dimension: str
    text: str


class FullReadOut(BaseModel):
    """The pre-§7.7 long-form fields, unchanged — now collapsed behind
    "See full read" on the client rather than shown by default."""

    overall_read: str
    color_note: str
    formality_note: str
    proportion_note: Optional[str] = None
    garment_notes: List[GarmentNoteOut] = Field(default_factory=list)


class FeedbackOut(BaseModel):
    """§5.5 / §7.7. Zone 1+2 fields are top-level (always visible on the
    client); the pre-existing long-form fields live under ``full_read``
    (collapsed by default)."""

    verdict_phrase: str
    verdict_subtitle: str
    occasion_match: Optional[MeterOut] = None
    signal_clarity: Optional[MeterOut] = None
    palette: List[ColourOut] = Field(default_factory=list)
    focal_point: Optional[str] = None
    quick_reads: List[QuickReadOut] = Field(default_factory=list)
    elevate_suggestion: Optional[str] = None
    full_read: FullReadOut


class OutfitDetail(BaseModel):
    """§6.2. Fields absent for a given status are omitted, not nulled."""

    outfit_id: uuid.UUID
    status: str
    failure_reason: Optional[str] = None
    occasion: Optional[str] = None
    context_note: Optional[str] = None
    capture_mode: str = "worn"
    is_public: Optional[bool] = None
    thumb_url: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    garments: Optional[List[GarmentOut]] = None
    feedback: Optional[FeedbackOut] = None
    # SPEC+ — likes/favorites (docs/spec-deviations.md). Only meaningful once
    # public; omitted (not zeroed) for a private outfit so the client can
    # tell "never shared" apart from "shared, zero likes so far".
    like_count: Optional[int] = None
    # SPEC+ — wardrobe catalog. Only meaningful for capture_mode="item";
    # None for a worn scan (nothing to add), True/False once it is.
    in_wardrobe: Optional[bool] = None


class OutfitListItem(BaseModel):
    outfit_id: uuid.UUID
    status: str
    thumb_url: Optional[str] = None
    occasion: Optional[str] = None
    created_at: datetime
    like_count: Optional[int] = None


class OutfitListResponse(BaseModel):
    """§6.3."""

    items: List[OutfitListItem]
    cursor: Optional[str] = None


# --- Profiles / follow graph (SPEC+ — see docs/spec-deviations.md) ---------
class UserProfileOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    follower_count: int
    following_count: int
    outfit_count: int
    is_following: bool
    is_self: bool
    outfits: List[OutfitListItem]
    cursor: Optional[str] = None


class FollowResponse(BaseModel):
    user_id: uuid.UUID
    following: bool
    follower_count: int


# --- Personal signal history / style insights (SPEC+ — see
# docs/spec-deviations.md). Aggregated entirely from signals already
# computed per scan; no new cataloguing of what the caller owns.
class ColourInsight(BaseModel):
    hex: str
    scan_count: int


class InsightsOut(BaseModel):
    ready: bool
    scan_count: int
    minimum_scans: int
    average_formality_label: Optional[str] = None
    top_colours: List[ColourInsight] = Field(default_factory=list)
    occasion_match_strong_rate: Optional[float] = None
    signal_clarity_strong_rate: Optional[float] = None
    most_common_occasion: Optional[str] = None
    worn_count: int = 0
    item_count: int = 0


# --- Wardrobe catalog (SPEC+ — see docs/spec-deviations.md) ----------------
class WardrobeAddRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=120)


class WardrobeItemOut(BaseModel):
    item_id: uuid.UUID
    outfit_id: uuid.UUID
    category: str
    colors: List[ColourOut] = Field(default_factory=list)
    pattern: str
    formality: float
    note: Optional[str] = None
    thumb_url: Optional[str] = None
    created_at: datetime


class WardrobeListResponse(BaseModel):
    items: List[WardrobeItemOut]
    cursor: Optional[str] = None


# --- Community feed + ratings (§6.5) --------------------------------------
class FeedItem(BaseModel):
    outfit_id: uuid.UUID
    thumb_url: Optional[str] = None
    occasion: Optional[str] = None
    like_count: int = 0
    liked_by_me: bool = False
    favorited_by_me: bool = False
    owner_id: uuid.UUID
    owner_display_name: str


class FeedResponse(BaseModel):
    items: List[FeedItem]
    cursor: Optional[str] = None


class LikeResponse(BaseModel):
    outfit_id: uuid.UUID
    liked: bool
    like_count: int


class FavoriteResponse(BaseModel):
    outfit_id: uuid.UUID
    favorited: bool


class RatingRequest(BaseModel):
    dimension: str
    value: int = Field(ge=1, le=5)

    def validated_dimension(self) -> str:
        if self.dimension not in RATING_DIMENSIONS:
            raise ValueError(
                "dimension must be one of {0}".format(", ".join(RATING_DIMENSIONS))
            )
        return self.dimension


class RatingResponse(BaseModel):
    outfit_id: uuid.UUID
    dimension: str
    value: int
    scans_earned: int
    quota: QuotaOut


# --- Billing (SPEC+ — native IAP, docs/spec-deviations.md #18) -------------
class VerifyPurchaseRequest(BaseModel):
    platform: str  # "ios" | "android"
    product_id: str
    purchase_token: Optional[str] = None  # Android (Play Billing)
    receipt_data: Optional[str] = None  # iOS (App Store receipt, base64)


# --- Misc ------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    env: str
    database: str
    storage: str
    queue: str
    vlm_enabled: bool
    feedback_engine: str


def valid_occasion(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    if value not in OCCASIONS:
        raise ValueError(
            "occasion must be one of {0}".format(", ".join(OCCASIONS))
        )
    return value


def valid_capture_mode(value: Optional[str]) -> str:
    if value is None or value == "":
        return "worn"
    if value not in CAPTURE_MODES:
        raise ValueError(
            "capture_mode must be one of {0}".format(", ".join(CAPTURE_MODES))
        )
    return value


def signals_summary(signals: Dict[str, Any]) -> Dict[str, Any]:
    """A safe, non-numeric projection of internal signals for debug endpoints."""
    colour = signals.get("colour") or {}
    formality = signals.get("formality") or {}
    proportion = signals.get("proportion") or {}
    return {
        "harmony_class": colour.get("harmony_class"),
        "contrast_band": colour.get("contrast_band"),
        "formality_coherence": formality.get("coherence"),
        "proportion_flags": proportion.get("flags", []),
        "fallback_used": bool(signals.get("fallback_used")),
    }
