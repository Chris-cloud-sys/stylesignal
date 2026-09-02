"""Password reset — SPEC+, see docs/spec-deviations.md.

§8 requires auth but the spec text has no reset flow. What is built: a
short-lived (15 min), single-use, attempt-limited 6-digit code, requested
and confirmed by email rather than a clickable link, delivered through
``app.email.ConsoleEmailSender`` (logged, not actually emailed — no mail
provider is configured in dev).
"""
from datetime import datetime, timedelta, timezone

import pytest

# app.db binds its engine/SessionLocal to settings.database_url at import
# time, and conftest's _isolated_environment fixture (session-scoped,
# autouse) only points that at the test's temp DB — and force-reloads
# app.* — once fixture setup actually runs. Collection happens first, so a
# module-level `from app.db import ...` here would bind to the real dev
# database instead. Import app.db/app.models/app.security inside the one
# test that needs them so it happens after that fixture has run.


def register(client, email: str, password: str = "correct-horse-battery") -> None:
    response = client.post(
        "/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Test"},
    )
    assert response.status_code == 201, response.text


class CapturingEmailSender:
    """Test double — records the code instead of logging it."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_password_reset(self, to: str, code: str) -> None:
        self.sent.append((to, code))


@pytest.fixture()
def capturing_sender(monkeypatch):
    sender = CapturingEmailSender()
    monkeypatch.setattr("app.routers.auth.get_email_sender", lambda: sender)
    return sender


def _unique_email(tag: str) -> str:
    import uuid

    return "reset-{0}-{1}@example.com".format(tag, uuid.uuid4().hex[:8])


def test_request_for_unknown_email_returns_ok_and_sends_nothing(client, capturing_sender):
    response = client.post(
        "/v1/auth/password-reset/request", json={"email": _unique_email("ghost")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert capturing_sender.sent == []


def test_request_and_confirm_round_trip(client, capturing_sender):
    email = _unique_email("roundtrip")
    register(client, email, password="old-password-123")

    response = client.post("/v1/auth/password-reset/request", json={"email": email})
    assert response.status_code == 200, response.text
    assert len(capturing_sender.sent) == 1
    sent_to, code = capturing_sender.sent[0]
    assert sent_to == email

    response = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": code, "new_password": "new-password-456"},
    )
    assert response.status_code == 200, response.text

    # Old password no longer works, new one does.
    assert client.post(
        "/v1/auth/login", json={"email": email, "password": "old-password-123"}
    ).status_code == 401
    assert client.post(
        "/v1/auth/login", json={"email": email, "password": "new-password-456"}
    ).status_code == 200


def test_confirm_with_unknown_email_is_generic_invalid_code(client):
    response = client.post(
        "/v1/auth/password-reset/confirm",
        json={
            "email": _unique_email("nope"),
            "code": "123456",
            "new_password": "whatever-1234",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_code"


def test_wrong_code_is_rejected(client, capturing_sender):
    email = _unique_email("wrongcode")
    register(client, email)
    client.post("/v1/auth/password-reset/request", json={"email": email})
    _, real_code = capturing_sender.sent[0]
    wrong_code = "{0:06d}".format((int(real_code) + 1) % 1_000_000)

    response = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": wrong_code, "new_password": "whatever-1234"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_code"


def test_code_is_single_use(client, capturing_sender):
    email = _unique_email("singleuse")
    register(client, email)
    client.post("/v1/auth/password-reset/request", json={"email": email})
    _, code = capturing_sender.sent[0]

    first = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": code, "new_password": "first-new-pass1"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": code, "new_password": "second-new-pass"},
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "invalid_code"


def test_exceeding_attempts_locks_the_code_even_when_finally_correct(client, capturing_sender):
    email = _unique_email("lockout")
    register(client, email)
    client.post("/v1/auth/password-reset/request", json={"email": email})
    _, real_code = capturing_sender.sent[0]
    wrong_code = "{0:06d}".format((int(real_code) + 1) % 1_000_000)

    # 5 wrong attempts burns the attempt cap (PASSWORD_RESET_MAX_ATTEMPTS).
    for _ in range(5):
        response = client.post(
            "/v1/auth/password-reset/confirm",
            json={"email": email, "code": wrong_code, "new_password": "whatever-1234"},
        )
        assert response.status_code == 400

    # The *correct* code is now also rejected — the code itself is spent.
    response = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": real_code, "new_password": "whatever-1234"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_code"


def test_expired_code_is_rejected(client, capturing_sender):
    from app.db import SessionLocal
    from app.models import PasswordResetCode, User
    from app.security import hash_reset_code

    email = _unique_email("expired")
    register(client, email)
    client.post("/v1/auth/password-reset/request", json={"email": email})
    _, code = capturing_sender.sent[0]

    # Back-date the code past its TTL directly — nothing waits 15 real minutes.
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.email == email).one()
        reset_code = (
            session.query(PasswordResetCode)
            .filter(PasswordResetCode.user_id == user.id)
            .one()
        )
        assert reset_code.code_hash == hash_reset_code(code)
        reset_code.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
    finally:
        session.close()

    response = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": code, "new_password": "whatever-1234"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_code"


def test_successful_reset_burns_other_outstanding_codes(client, capturing_sender):
    email = _unique_email("burnall")
    register(client, email)

    client.post("/v1/auth/password-reset/request", json={"email": email})
    client.post("/v1/auth/password-reset/request", json={"email": email})
    assert len(capturing_sender.sent) == 2
    _, first_code = capturing_sender.sent[0]
    _, second_code = capturing_sender.sent[1]

    response = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": second_code, "new_password": "whatever-1234"},
    )
    assert response.status_code == 200, response.text

    # The first, still-unused code is also dead now.
    response = client.post(
        "/v1/auth/password-reset/confirm",
        json={"email": email, "code": first_code, "new_password": "another-pass12"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_code"
