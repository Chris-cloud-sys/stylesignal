"""Shared FastAPI dependencies."""
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from .db import get_db
from .errors import unauthorized
from .models import User
from .quota import roll_period
from .security import decode_token


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve ``Authorization: Bearer <jwt>`` to a user (§6, §8)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized("Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_token(token, expected_type="access")

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized("User no longer exists")

    # Lazy monthly quota reset (§5.2).
    roll_period(db, user)
    return user
