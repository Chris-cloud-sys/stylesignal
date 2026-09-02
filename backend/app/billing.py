"""Native in-app purchase verification — SPEC+, native IAP approved
2026-08-30 (see docs/spec-deviations.md #18).

Two stores, one shape: verify the receipt/token with Apple or Google, hand
back a normalized :class:`VerificationResult`. Neither function touches the
database or mutates a user — that's ``app.routers.billing``'s job, so the
plan-activation logic lives in exactly one place regardless of platform.

Same testing precedent as ``app.email``'s ``ResendEmailSender``: an
injectable ``httpx.Client`` so tests exercise the real request-building and
response-parsing logic against a ``MockTransport``, never a live call to
Apple or Google.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from .config import get_settings

logger = logging.getLogger("stylesignal.billing")

settings = get_settings()

APPLE_VERIFY_URL_PRODUCTION = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_VERIFY_URL_SANDBOX = "https://sandbox.itunes.apple.com/verifyReceipt"
# Apple's own documented flow: a sandbox receipt posted to the production
# endpoint comes back with this status and must be retried against sandbox.
APPLE_STATUS_SANDBOX_RECEIPT = 21007

GOOGLE_OAUTH_SCOPE = "https://www.googleapis.com/auth/androidpublisher"


class BillingConfigError(Exception):
    """Store credentials aren't configured — a deployment gap, not a bad request."""


@dataclass
class VerificationResult:
    valid: bool
    expires_at: Optional[datetime]
    transaction_id: Optional[str]
    raw_status: str


# --- Apple -------------------------------------------------------------------
def verify_apple_purchase(
    receipt_data: str,
    client: Optional[httpx.Client] = None,
) -> VerificationResult:
    if not settings.apple_shared_secret:
        raise BillingConfigError(
            "STYLESIGNAL_APPLE_SHARED_SECRET is not set — cannot verify App "
            "Store receipts."
        )
    http = client or httpx.Client()
    payload = {
        "receipt-data": receipt_data,
        "password": settings.apple_shared_secret,
        "exclude-old-transactions": True,
    }

    response = http.post(APPLE_VERIFY_URL_PRODUCTION, json=payload, timeout=15.0)
    body = response.json()
    if body.get("status") == APPLE_STATUS_SANDBOX_RECEIPT:
        response = http.post(APPLE_VERIFY_URL_SANDBOX, json=payload, timeout=15.0)
        body = response.json()

    status = body.get("status")
    if status != 0:
        logger.info("Apple receipt verify rejected (status=%s)", status)
        return VerificationResult(False, None, None, str(status))

    latest = _latest_apple_transaction(body)
    if latest is None:
        return VerificationResult(False, None, None, "no_transactions")

    expires_ms = latest.get("expires_date_ms")
    expires_at = (
        datetime.fromtimestamp(int(expires_ms) / 1000, tz=timezone.utc)
        if expires_ms
        else None
    )
    return VerificationResult(
        valid=expires_at is not None and expires_at > datetime.now(timezone.utc),
        expires_at=expires_at,
        transaction_id=latest.get("original_transaction_id") or latest.get("transaction_id"),
        raw_status="0",
    )


def _latest_apple_transaction(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # `latest_receipt_info` (auto-renewable subscriptions) is already in
    # ascending order — the last entry is the most recent purchase/renewal.
    entries = body.get("latest_receipt_info") or body.get("receipt", {}).get("in_app") or []
    return entries[-1] if entries else None


# --- Google ------------------------------------------------------------------
def verify_google_purchase(
    product_id: str,
    purchase_token: str,
    client: Optional[httpx.Client] = None,
    access_token: Optional[str] = None,
) -> VerificationResult:
    """``access_token`` is normally fetched from the configured service
    account (see :func:`_google_access_token`) — the parameter exists so
    tests can inject a fake one instead of mocking the Google auth library.
    """
    if not settings.google_play_package_name or not settings.google_play_service_account_json:
        raise BillingConfigError(
            "Google Play billing isn't configured — set "
            "STYLESIGNAL_GOOGLE_PLAY_PACKAGE_NAME and "
            "STYLESIGNAL_GOOGLE_PLAY_SERVICE_ACCOUNT_JSON."
        )
    http = client or httpx.Client()
    token = access_token or _google_access_token()

    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/"
        "{0}/purchases/subscriptions/{1}/tokens/{2}".format(
            settings.google_play_package_name, product_id, purchase_token
        )
    )
    response = http.get(url, headers={"Authorization": "Bearer {0}".format(token)}, timeout=15.0)
    if response.status_code != 200:
        logger.error(
            "Play Developer API verify failed (%s): %s", response.status_code, response.text
        )
        return VerificationResult(False, None, None, str(response.status_code))

    body = response.json()
    expiry_ms = body.get("expiryTimeMillis")
    expires_at = (
        datetime.fromtimestamp(int(expiry_ms) / 1000, tz=timezone.utc) if expiry_ms else None
    )
    # paymentState: 0 = pending, 1 = received, 2 = free trial, 3 = deferred.
    # Cancelled/on-hold/paused subscriptions omit it or use other states —
    # only 1/2 mean "currently paid for".
    payment_state = body.get("paymentState")
    valid = (
        payment_state in (1, 2)
        and expires_at is not None
        and expires_at > datetime.now(timezone.utc)
    )
    return VerificationResult(
        valid=valid,
        expires_at=expires_at,
        transaction_id=body.get("orderId"),
        raw_status=str(payment_state),
    )


def _google_access_token() -> str:
    # Imported here, not at module load: google-auth is only needed once
    # Android billing is actually configured, and importing it eagerly would
    # make it a hard dependency for every deployment, including ones that
    # never touch billing.
    import google.auth.transport.requests
    from google.oauth2 import service_account

    info = json.loads(settings.google_play_service_account_json)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=[GOOGLE_OAUTH_SCOPE]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token
