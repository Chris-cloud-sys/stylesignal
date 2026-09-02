"""Outbound email — spec §8 needs an auth-adjacent delivery channel the spec
text doesn't define (password reset). Same shape as storage/jobs/ratelimit:
a real interface behind a factory function, so a router never talks to a
concrete implementation directly, and ``STYLESIGNAL_EMAIL_BACKEND`` picks
which one — console (dev default) or resend (real delivery).
"""
import logging
from typing import Optional, Protocol

import httpx

from .config import get_settings

logger = logging.getLogger("stylesignal.email")

settings = get_settings()

RESEND_API_URL = "https://api.resend.com/emails"


class EmailSender(Protocol):
    def send_password_reset(self, to: str, code: str) -> None: ...


class ConsoleEmailSender:
    """Local dev default — logs the code instead of emailing it."""

    def send_password_reset(self, to: str, code: str) -> None:
        logger.info("Password reset code for %s: %s", to, code)


class ResendEmailSender:
    """Real delivery via the Resend API (https://resend.com).

    ``onboarding@resend.dev`` (the default ``STYLESIGNAL_EMAIL_FROM``) is
    Resend's own sandbox sender — it works with no domain setup, but Resend
    restricts it to delivering only to the account's own verified email.
    Point ``STYLESIGNAL_EMAIL_FROM`` at a verified sending domain before
    this needs to reach real users.
    """

    def __init__(
        self,
        api_key: str,
        from_address: str,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._api_key = api_key
        self._from = from_address
        # Injectable so tests can swap in a MockTransport instead of a real
        # one — see tests/test_email.py.
        self._client = client or httpx.Client()

    def send_password_reset(self, to: str, code: str) -> None:
        response = self._client.post(
            RESEND_API_URL,
            headers={"Authorization": "Bearer {0}".format(self._api_key)},
            json={
                "from": self._from,
                "to": [to],
                "subject": "Your StyleSignal password reset code",
                "text": (
                    "Your StyleSignal password reset code is {0}.\n\n"
                    "It expires in 15 minutes. If you didn't request this, "
                    "you can ignore this email.".format(code)
                ),
            },
            timeout=10.0,
        )
        if response.status_code >= 400:
            # Never let an email-provider outage surface to the caller as a
            # 500 — the code is already persisted, so the request already
            # succeeded from the user's point of view. Log and move on.
            logger.error(
                "Resend send failed (%s): %s", response.status_code, response.text
            )


def get_email_sender() -> EmailSender:
    if settings.email_backend == "resend":
        if not settings.resend_api_key:
            logger.error(
                "STYLESIGNAL_EMAIL_BACKEND=resend but no "
                "STYLESIGNAL_RESEND_API_KEY is set — falling back to console."
            )
            return ConsoleEmailSender()
        return ResendEmailSender(settings.resend_api_key, settings.email_from)
    return ConsoleEmailSender()
