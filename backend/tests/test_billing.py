"""Native in-app purchase verification and Pro activation — SPEC+, native
IAP approved 2026-08-30 (see docs/spec-deviations.md #18).

Same precedent as tests/test_email.py: Apple/Google are exercised against
an httpx MockTransport, never a live call. Router tests monkeypatch
``app.billing``'s verify functions directly (the router looks them up as
``billing.verify_apple_purchase`` at call time, so patching the attribute on
the module object is enough — no need to touch the router's own names).
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest


# --- app.billing: Apple ------------------------------------------------------
def test_verify_apple_purchase_accepts_a_valid_receipt(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "apple_shared_secret", "shh")

    expires_ms = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == billing.APPLE_VERIFY_URL_PRODUCTION
        return httpx.Response(
            200,
            json={
                "status": 0,
                "latest_receipt_info": [
                    {
                        "original_transaction_id": "1000000123",
                        "expires_date_ms": str(expires_ms),
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = billing.verify_apple_purchase("base64-receipt", client=client)

    assert result.valid is True
    assert result.transaction_id == "1000000123"
    assert result.expires_at is not None and result.expires_at.year >= 2026


def test_verify_apple_purchase_retries_sandbox_url_on_21007(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "apple_shared_secret", "shh")
    calls = []
    expires_ms = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == billing.APPLE_VERIFY_URL_PRODUCTION:
            return httpx.Response(200, json={"status": billing.APPLE_STATUS_SANDBOX_RECEIPT})
        return httpx.Response(
            200,
            json={
                "status": 0,
                "latest_receipt_info": [
                    {"original_transaction_id": "sandbox-tx", "expires_date_ms": str(expires_ms)}
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = billing.verify_apple_purchase("sandbox-receipt", client=client)

    assert calls == [billing.APPLE_VERIFY_URL_PRODUCTION, billing.APPLE_VERIFY_URL_SANDBOX]
    assert result.valid is True
    assert result.transaction_id == "sandbox-tx"


def test_verify_apple_purchase_rejects_a_bad_status(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "apple_shared_secret", "shh")

    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": 21002}))
    )
    result = billing.verify_apple_purchase("malformed-receipt", client=client)

    assert result.valid is False
    assert result.raw_status == "21002"


def test_verify_apple_purchase_requires_shared_secret(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "apple_shared_secret", None)
    with pytest.raises(billing.BillingConfigError):
        billing.verify_apple_purchase("receipt")


# --- app.billing: Google ------------------------------------------------------
def test_verify_google_purchase_accepts_an_active_subscription(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "google_play_package_name", "com.stylesignal.app")
    monkeypatch.setattr(billing.settings, "google_play_service_account_json", "{}")

    expiry_ms = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer fake-token"
        assert "com.stylesignal.app" in str(request.url)
        return httpx.Response(
            200, json={"paymentState": 1, "expiryTimeMillis": str(expiry_ms), "orderId": "GPA.order-1"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = billing.verify_google_purchase(
        "stylesignal_pro_monthly", "purchase-token", client=client, access_token="fake-token"
    )

    assert result.valid is True
    assert result.transaction_id == "GPA.order-1"


def test_verify_google_purchase_rejects_an_expired_subscription(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "google_play_package_name", "com.stylesignal.app")
    monkeypatch.setattr(billing.settings, "google_play_service_account_json", "{}")

    expired_ms = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp() * 1000)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"paymentState": 1, "expiryTimeMillis": str(expired_ms)}
            )
        )
    )
    result = billing.verify_google_purchase(
        "stylesignal_pro_monthly", "purchase-token", client=client, access_token="fake-token"
    )

    assert result.valid is False


def test_verify_google_purchase_rejects_a_cancelled_subscription(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "google_play_package_name", "com.stylesignal.app")
    monkeypatch.setattr(billing.settings, "google_play_service_account_json", "{}")

    future_ms = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp() * 1000)
    # No paymentState at all is how Google represents a cancelled sub still
    # inside its paid-through window.
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"expiryTimeMillis": str(future_ms)})
        )
    )
    result = billing.verify_google_purchase(
        "stylesignal_pro_monthly", "purchase-token", client=client, access_token="fake-token"
    )

    assert result.valid is False


def test_verify_google_purchase_requires_config(monkeypatch):
    from app import billing

    monkeypatch.setattr(billing.settings, "google_play_package_name", None)
    monkeypatch.setattr(billing.settings, "google_play_service_account_json", None)
    with pytest.raises(billing.BillingConfigError):
        billing.verify_google_purchase("product", "token")


# --- app.quota: effective_plan ------------------------------------------------
def test_effective_plan_is_free_for_a_free_user():
    from app.models import User
    from app.quota import effective_plan

    user = User(plan="free", pro_expires_at=None, scans_used_this_month=0)
    assert effective_plan(user) == "free"


def test_effective_plan_is_pro_while_the_subscription_has_not_expired():
    from app.models import User
    from app.quota import effective_plan

    user = User(
        plan="pro",
        pro_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        scans_used_this_month=0,
    )
    assert effective_plan(user) == "pro"


def test_effective_plan_reverts_to_free_once_the_subscription_lapses():
    from app.models import User
    from app.quota import effective_plan

    user = User(
        plan="pro",
        pro_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        scans_used_this_month=0,
    )
    assert effective_plan(user) == "free"


def test_effective_plan_treats_no_expiry_as_pro_forever():
    """An admin/test override — `plan="pro"` set directly with no
    `pro_expires_at` — is not a real subscription and has no lapse date."""
    from app.models import User
    from app.quota import effective_plan

    user = User(plan="pro", pro_expires_at=None, scans_used_this_month=0)
    assert effective_plan(user) == "pro"


def test_monthly_allowance_and_is_degraded_follow_effective_plan(monkeypatch):
    from app.models import User
    from app import quota

    monkeypatch.setattr(quota.settings, "pro_soft_monthly_cap", 5)

    lapsed = User(
        plan="pro",
        pro_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        scans_used_this_month=10,
    )
    # Lapsed Pro reads as free: a hard allowance applies again, and the
    # Pro-only soft-degradation ceiling no longer does.
    assert quota.monthly_allowance(lapsed) == quota.settings.free_monthly_scans
    assert quota.is_degraded(lapsed) is False

    active = User(
        plan="pro",
        pro_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        scans_used_this_month=10,
    )
    assert quota.monthly_allowance(active) is None
    assert quota.is_degraded(active) is True


# --- Router: POST /v1/billing/verify-purchase ---------------------------------
def test_verify_purchase_activates_pro_on_a_valid_ios_purchase(auth_client, monkeypatch):
    from app import billing

    monkeypatch.setattr(
        billing,
        "verify_apple_purchase",
        lambda receipt_data, client=None: billing.VerificationResult(
            valid=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            transaction_id="tx-ios-1",
            raw_status="0",
        ),
    )

    response = auth_client.post(
        "/v1/billing/verify-purchase",
        json={"platform": "ios", "product_id": "stylesignal_pro_monthly", "receipt_data": "abc"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"] == "pro"
    assert body["monthly_allowance"] is None
    assert body["pro_expires_at"] is not None


def test_verify_purchase_activates_pro_on_a_valid_android_purchase(auth_client, monkeypatch):
    from app import billing

    monkeypatch.setattr(
        billing,
        "verify_google_purchase",
        lambda product_id, purchase_token, client=None, access_token=None: billing.VerificationResult(
            valid=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            transaction_id="tx-android-1",
            raw_status="1",
        ),
    )

    response = auth_client.post(
        "/v1/billing/verify-purchase",
        json={
            "platform": "android",
            "product_id": "stylesignal_pro_monthly",
            "purchase_token": "token-abc",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["plan"] == "pro"


def test_verify_purchase_rejects_an_invalid_purchase(auth_client, monkeypatch):
    from app import billing

    monkeypatch.setattr(
        billing,
        "verify_apple_purchase",
        lambda receipt_data, client=None: billing.VerificationResult(
            valid=False, expires_at=None, transaction_id=None, raw_status="21002"
        ),
    )

    response = auth_client.post(
        "/v1/billing/verify-purchase",
        json={"platform": "ios", "product_id": "stylesignal_pro_monthly", "receipt_data": "bad"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "purchase_not_valid"


def test_verify_purchase_rejects_an_unknown_platform(auth_client):
    response = auth_client.post(
        "/v1/billing/verify-purchase",
        json={"platform": "web", "product_id": "stylesignal_pro_monthly"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_platform"


def test_verify_purchase_surfaces_a_config_error_as_503(auth_client, monkeypatch):
    from app import billing

    def raise_config_error(receipt_data, client=None):
        raise billing.BillingConfigError("not configured")

    monkeypatch.setattr(billing, "verify_apple_purchase", raise_config_error)

    response = auth_client.post(
        "/v1/billing/verify-purchase",
        json={"platform": "ios", "product_id": "stylesignal_pro_monthly", "receipt_data": "abc"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "billing_not_configured"


def test_verify_purchase_rejects_a_transaction_already_claimed_by_someone_else(
    client, auth_client, monkeypatch
):
    from app import billing

    monkeypatch.setattr(
        billing,
        "verify_apple_purchase",
        lambda receipt_data, client=None: billing.VerificationResult(
            valid=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            transaction_id="shared-tx",
            raw_status="0",
        ),
    )

    first = auth_client.post(
        "/v1/billing/verify-purchase",
        json={"platform": "ios", "product_id": "stylesignal_pro_monthly", "receipt_data": "a"},
    )
    assert first.status_code == 200, first.text

    # A second, different account tries to redeem the same transaction id.
    register = client.post(
        "/v1/auth/register",
        json={
            "email": "second-user@example.com",
            "password": "correct-horse-battery",
            "display_name": "Second",
        },
    )
    assert register.status_code == 201, register.text
    client.headers.update({"Authorization": "Bearer {0}".format(register.json()["access_token"])})

    second = client.post(
        "/v1/billing/verify-purchase",
        json={"platform": "ios", "product_id": "stylesignal_pro_monthly", "receipt_data": "b"},
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "purchase_already_claimed"
