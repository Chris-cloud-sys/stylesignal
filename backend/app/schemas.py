"""Request/response models — spec §6.

The outfit-result contract (§6.2) is stable from v1: v2 populates
``garments[]`` richly instead of sparsely, but the shape does not change.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import OCCASIONS, RATING_DIMENSIONS


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


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    plan: str
    is_stylist: bool
    created_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    quota: QuotaOut


# --- Outfits ---------------------------------------------------------------
class OutfitCreateResponse(BaseModel):
    outfit_id: uuid.UUID
    status: str


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


class FeedbackOut(BaseModel):
    overall_read: str
    color_note: str
    formality_note: str
    proportion_note: Optional[str] = None
    garment_notes: List[GarmentNoteOut] = Field(default_factory=list)


class OutfitDetail(BaseModel):
    """§6.2. Fields absent for a given status are omitted, not nulled."""

    outfit_id: uuid.UUID
    status: str
    failure_reason: Optional[str] = None
    occasion: Optional[str] = None
    context_note: Optional[str] = None
    is_public: Optional[bool] = None
    thumb_url: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    garments: Optional[List[GarmentOut]] = None
    feedback: Optional[FeedbackOut] = None


class OutfitListItem(BaseModel):
    outfit_id: uuid.UUID
    status: str
    thumb_url: Optional[str] = None
    occasion: Optional[str] = None
    created_at: datetime


class OutfitListResponse(BaseModel):
    """§6.3."""

    items: List[OutfitListItem]
    cursor: Optional[str] = None


# --- Community feed + ratings (§6.5) --------------------------------------
class FeedItem(BaseModel):
    outfit_id: uuid.UUID
    thumb_url: Optional[str] = None
    occasion: Optional[str] = None


class FeedResponse(BaseModel):
    items: List[FeedItem]
    cursor: Optional[str] = None


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
