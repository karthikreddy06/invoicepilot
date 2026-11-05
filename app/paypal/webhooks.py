import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx
from app.config import settings
from app.paypal.client import paypal_client
from app.db import update_invoice_status, get_invoice_by_paypal_id

logger = logging.getLogger(__name__)


async def verify_webhook_signature(
    headers: Dict[str, str],
    raw_body: Dict[str, Any],
    webhook_id: Optional[str] = None,
    client: Optional[Any] = None,
) -> bool:
    """
    Verify PayPal webhook signature using PayPal's /v1/notifications/verify-webhook-signature endpoint.
    """
    w_id = webhook_id or settings.PAYPAL_WEBHOOK_ID
    if not w_id:
        logger.warning("PAYPAL_WEBHOOK_ID is not configured; skipping cryptographic signature check in dev.")
        return True

    api_client = client or paypal_client
    token_headers = await api_client.get_headers()

    # PayPal header keys are case-insensitive
    h_lower = {k.lower(): v for k, v in headers.items()}

    verification_payload = {
        "auth_algo": h_lower.get("paypal-auth-algo", ""),
        "cert_url": h_lower.get("paypal-cert-url", ""),
        "transmission_id": h_lower.get("paypal-transmission-id", ""),
        "transmission_sig": h_lower.get("paypal-transmission-sig", ""),
        "transmission_time": h_lower.get("paypal-transmission-time", ""),
        "webhook_id": w_id,
        "webhook_event": raw_body,
    }

    url = f"{api_client.base_url}/v1/notifications/verify-webhook-signature"
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(url, json=verification_payload, headers=token_headers)
        if resp.status_code != 200:
            logger.error(f"PayPal signature verification failed ({resp.status_code}): {resp.text}")
            return False
        data = resp.json()
        return data.get("verification_status") == "SUCCESS"


def handle_webhook_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process verified webhook events:
    - INVOICING.INVOICE.PAID
    - INVOICING.INVOICE.CANCELLED
    - INVOICING.INVOICE.REFUNDED
    """
    event_type = event.get("event_type", "")
    resource = event.get("resource", {})
    invoice_id = resource.get("id")

    if not invoice_id:
        logger.warning(f"Webhook event {event_type} received without invoice resource ID.")
        return {"processed": False, "reason": "No invoice ID in resource"}

    logger.info(f"Processing webhook {event_type} for invoice {invoice_id}")

    if event_type == "INVOICING.INVOICE.PAID":
        # Extract payment date if available
        paid_at = datetime.now(timezone.utc).isoformat()
        payments = resource.get("payments", {})
        transactions = payments.get("transactions", [])
        if transactions and "payment_date" in transactions[0]:
            paid_at = transactions[0]["payment_date"]

        inv = update_invoice_status(invoice_id, status="PAID", paid_at=paid_at)
        return {"processed": True, "event_type": event_type, "invoice_id": invoice_id, "status": "PAID"}

    elif event_type == "INVOICING.INVOICE.CANCELLED":
        inv = update_invoice_status(invoice_id, status="CANCELLED")
        return {"processed": True, "event_type": event_type, "invoice_id": invoice_id, "status": "CANCELLED"}

    elif event_type == "INVOICING.INVOICE.REFUNDED":
        inv = update_invoice_status(invoice_id, status="REFUNDED")
        return {"processed": True, "event_type": event_type, "invoice_id": invoice_id, "status": "REFUNDED"}

    else:
        logger.info(f"Unhandled webhook event type: {event_type}")
        return {"processed": False, "event_type": event_type, "reason": "Event type ignored"}

