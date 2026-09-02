"""Auth routes — spec §8.

Short-lived access token plus a refresh token, both JWT bearer.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..db import get_db
from ..deps import get_current_user
from ..email import get_email_sender
from ..errors import APIError, bad_request, unauthorized
from ..models import PasswordResetCode, User
from ..quota import current_period, quota_out
from ..schemas import (
    LoginRequest,
    MeResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestRequest,
    RefreshRequest,
    RegisterRequest,
    StatusResponse,
    TokenPair,
    UserOut,
)
from ..security import (
    create_token_pair,
    decode_token,
    generate_reset_code,
    hash_password,
    hash_reset_code,
    verify_password,
    verify_reset_code,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])

PASSWORD_RESET_CODE_TTL_MINUTES = 15
PASSWORD_RESET_MAX_ATTEMPTS = 5


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


# --- Password reset (SPEC+ — see docs/spec-deviations.md) ------------------
@router.post("/password-reset/request", response_model=StatusResponse)
def request_password_reset(
    payload: PasswordResetRequestRequest, db: Session = Depends(get_db)
) -> StatusResponse:
    email = payload.email.lower().strip()
    ratelimit.check("password-reset-request:{0}".format(email), limit=3, window_seconds=900)

    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()

    # Same response whether or not the account exists — an error here would
    # let a caller enumerate registered emails (§8 privacy).
    if user is not None:
        code = generate_reset_code()
        db.add(
            PasswordResetCode(
                user_id=user.id,
                code_hash=hash_reset_code(code),
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=PASSWORD_RESET_CODE_TTL_MINUTES),
            )
        )
        db.commit()
        get_email_sender().send_password_reset(user.email, code)

    return StatusResponse()


@router.post("/password-reset/confirm", response_model=StatusResponse)
def confirm_password_reset(
    payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)
) -> StatusResponse:
    email = payload.email.lower().strip()
    ratelimit.check("password-reset-confirm:{0}".format(email), limit=10, window_seconds=900)

    invalid = bad_request("invalid_code", "That code is invalid or has expired.")

    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    if user is None:
        raise invalid

    now = datetime.now(timezone.utc)
    pending = db.execute(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > now,
        )
        .order_by(PasswordResetCode.created_at.desc())
    ).scalars().all()

    matched = None
    for candidate in pending:
        if candidate.attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
            continue
        if verify_reset_code(payload.code, candidate.code_hash):
            matched = candidate
            break
        candidate.attempts += 1

    if matched is None:
        db.commit()  # persist incremented attempt counters even on failure
        raise invalid

    # Burn every other outstanding code for this user too, not just the one
    # that matched — a successful reset should leave nothing else usable.
    for candidate in pending:
        candidate.used_at = now

    user.password_hash = hash_password(payload.new_password)
    db.commit()

    return StatusResponse()
