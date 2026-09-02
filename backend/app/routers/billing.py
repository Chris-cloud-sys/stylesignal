"""Native in-app purchase verification and Pro activation — SPEC+ (native
IAP approved 2026-08-30, see docs/spec-deviations.md #18).

One endpoint, two platforms: verify the receipt/token with the right store
(``app.billing``), then do the exact same plan mutation regardless of which
one it was. The store call is the only part that differs by platform.
"""
import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import billing
from ..db import get_db
from ..deps import get_current_user
from ..errors import APIError, bad_request
from ..models import User
from ..quota import quota_out
from ..schemas import QuotaOut, VerifyPurchaseRequest

router = APIRouter(tags=["billing"])
logger = logging.getLogger("stylesignal.billing")


@router.post(
    "/v1/billing/verify-purchase",
    response_model=QuotaOut,
    summary="Verify a native IAP purchase and activate Pro",
)
def verify_purchase(
    payload: VerifyPurchaseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuotaOut:
    try:
        if payload.platform == "ios":
            if not payload.receipt_data:
                raise bad_request(
                    "missing_receipt", "receipt_data is required for platform=ios."
                )
            result = billing.verify_apple_purchase(payload.receipt_data)
        elif payload.platform == "android":
            if not payload.purchase_token:
                raise bad_request(
                    "missing_purchase_token",
                    "purchase_token is required for platform=android.",
                )
            result = billing.verify_google_purchase(payload.product_id, payload.purchase_token)
        else:
            raise bad_request(
                "invalid_platform", "platform must be 'ios' or 'android'."
            )
    except billing.BillingConfigError as exc:
        raise APIError(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_not_configured", str(exc))

    if not result.valid:
        raise bad_request(
            "purchase_not_valid",
            "That purchase could not be verified as an active subscription.",
            {"store_status": result.raw_status},
        )

    # Basic replay protection: a store transaction id can only ever activate
    # the one account it was actually purchased from.
    if result.transaction_id:
        claimed_by = db.execute(
            select(User).where(
                User.iap_transaction_id == result.transaction_id,
                User.id != user.id,
            )
        ).scalar_one_or_none()
        if claimed_by is not None:
            raise bad_request(
                "purchase_already_claimed",
                "This purchase is already linked to a different account.",
            )

    user.plan = "pro"
    user.pro_expires_at = result.expires_at
    user.iap_platform = payload.platform
    user.iap_product_id = payload.product_id
    user.iap_transaction_id = result.transaction_id
    db.commit()

    logger.info(
        "Activated Pro for user %s via %s (expires %s)",
        user.id,
        payload.platform,
        result.expires_at,
    )
    return quota_out(user)
