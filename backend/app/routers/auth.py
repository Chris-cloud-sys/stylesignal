"""Auth routes — spec §8.

Short-lived access token plus a refresh token, both JWT bearer.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..db import get_db
from ..deps import get_current_user
from ..errors import APIError, unauthorized
from ..models import User
from ..quota import current_period, quota_out
from ..schemas import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from ..security import (
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    ratelimit.check("register:{0}".format(payload.email.lower()), limit=5, window_seconds=3600)

    email = payload.email.lower().strip()
    existing = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise APIError(
            status.HTTP_409_CONFLICT,
            "email_taken",
            "An account with that email already exists.",
        )

    user = User(
        email=email,
        display_name=payload.display_name.strip() or email.split("@")[0],
        password_hash=hash_password(payload.password),
        plan="free",
        scans_period=current_period(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access, refresh, expires_in = create_token_pair(user.id)
    return TokenPair(
        access_token=access, refresh_token=refresh, expires_in=expires_in
    )


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    email = payload.email.lower().strip()
    ratelimit.check("login:{0}".format(email), limit=10, window_seconds=300)

    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()

    # Same message and roughly the same work either way — do not leak which
    # half was wrong.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise unauthorized("Email or password is incorrect")

    access, refresh, expires_in = create_token_pair(user.id)
    return TokenPair(
        access_token=access, refresh_token=refresh, expires_in=expires_in
    )


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(
    payload: RefreshRequest, db: Session = Depends(get_db)
) -> TokenPair:
    user_id = decode_token(payload.refresh_token, expected_type="refresh")
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized("User no longer exists")

    access, refresh, expires_in = create_token_pair(user.id)
    return TokenPair(
        access_token=access, refresh_token=refresh, expires_in=expires_in
    )


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user=UserOut.model_validate(user), quota=quota_out(user))
