"""NOWPayments.io USDT TRC20 payment integration."""

import hashlib
import hmac
import json
import logging
import time

import httpx

from config import NOWPAYMENTS_API_KEY, NOWPAYMENTS_IPN_SECRET

logger = logging.getLogger(__name__)

NOWPAYMENTS_BASE = "https://api.nowpayments.io/v1"


async def create_payment(telegram_id: int, price_usd: float = 19.0) -> dict | None:
    """Create a USDT TRC20 payment via NOWPayments API.

    Returns:
        {"payment_id": str, "pay_address": str, "pay_amount": float}
        or None on error.
    """
    payload = {
        "price_amount": price_usd,
        "price_currency": "usd",
        "pay_currency": "usdttrc20",
        "order_id": str(telegram_id),
        "order_description": "Macro Analyst Bot — 30-day subscription",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{NOWPAYMENTS_BASE}/payment",
                headers={
                    "x-api-key": NOWPAYMENTS_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "payment_id": str(data["payment_id"]),
                "pay_address": data["pay_address"],
                "pay_amount": float(data["pay_amount"]),
            }
    except httpx.HTTPStatusError as exc:
        logger.error(
            "NOWPayments API error for user %s: %s — %s",
            telegram_id, exc.response.status_code, exc.response.text,
        )
        return None
    except Exception as exc:
        logger.error("NOWPayments create_payment failed for user %s: %s", telegram_id, exc)
        return None


def verify_ipn_signature(raw_body: bytes, sig_header: str) -> bool:
    """Verify NOWPayments IPN HMAC-SHA512 signature.

    NOWPayments signs: HMAC-SHA512(json_sorted_alphabetically, ipn_secret)
    """
    if not NOWPAYMENTS_IPN_SECRET:
        logger.warning("NOWPAYMENTS_IPN_SECRET not set — skipping IPN verification")
        return True  # allow in development

    try:
        body_dict = json.loads(raw_body)
        sorted_body = json.dumps(body_dict, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(
            NOWPAYMENTS_IPN_SECRET.encode(),
            sorted_body.encode(),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header.lower())
    except Exception as exc:
        logger.error("IPN signature verification error: %s", exc)
        return False
