import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx
from app.config import settings
from app.paypal.client import paypal_client
from app.db import update_invoice_status, get_invoice_by_paypal_id

logger = logging.getLogger(__name__)


def extract_invoice_id_from_resource(resource: Dict[str, Any]) -> Optional[str]:
    """
    Robustly extract the PayPal invoice ID from webhook resource:
    1. Check resource["invoice"]["id"]
    2. Check resource["id"] if it looks like an invoice ID (starts with INV2- or INV-)
    3. Parse from resource["links"] or resource["href"] (segment after /invoicing/invoices/)
    4. Fallback to resource["id"] if non-empty
    """
    if not isinstance(resource, dict):
        return None

    # 1. Check resource["invoice"]["id"]
    invoice_obj = resource.get("invoice")
    if isinstance(invoice_obj, dict) and invoice_obj.get("id"):
        return str(invoice_obj["id"]).strip()

    # 2. Check resource["id"] if it has standard invoice ID prefix
    res_id = resource.get("id")
    if res_id and isinstance(res_id, str) and (res_id.startswith("INV2-") or res_id.startswith("INV-")):
        return res_id.strip()

    # 3. Check links list or href string for /invoicing/invoices/{id}
    candidate_urls = []
    if "href" in resource and isinstance(resource["href"], str):
        candidate_urls.append(resource["href"])
    if "links" in resource and isinstance(resource["links"], list):
        for link in resource["links"]:
            if isinstance(link, dict) and link.get("href"):
                candidate_urls.append(link["href"])

    for url in candidate_urls:
        if "/invoicing/invoices/" in url:
            parts = url.split("/invoicing/invoices/")
            if len(parts) > 1:
                inv_seg = parts[1].split("?")[0].rstrip("/").split("/")[0]
                if inv_seg:
                    return inv_seg.strip()

    # 4. Fallback to resource["id"] if available
    if res_id and isinstance(res_id, str):
        return res_id.strip()

    return None


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


def handle_webhook_event(event: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Process verified webhook events:
    - INVOICING.INVOICE.PAID
    - INVOICING.INVOICE.CANCELLED
    - INVOICING.INVOICE.REFUNDED
    """
    event_type = event.get("event_type", "")
    resource = event.get("resource", {})

    # Log raw resource JSON for INVOICING.INVOICE.PAID (no secrets)
    if event_type == "INVOICING.INVOICE.PAID":
        try:
            logger.info("Raw webhook resource for INVOICING.INVOICE.PAID: %s", json.dumps(resource))
        except Exception:
            logger.info("Raw webhook resource for INVOICING.INVOICE.PAID: %s", resource)

    invoice_id = extract_invoice_id_from_resource(resource)

    if not invoice_id:
        if event_type in ("INVOICING.INVOICE.CREATED", "INVOICING.INVOICE.SENT") or event_type.endswith(".CREATED") or event_type.endswith(".SENT"):
            logger.debug(f"Unhandled webhook event type: {event_type}")
            return {"processed": False, "event_type": event_type, "reason": "Event type ignored"}
        logger.warning(f"Webhook event {event_type} received without invoice resource ID.")
        return {"processed": False, "reason": "No invoice ID in resource"}

    if event_type == "INVOICING.INVOICE.PAID":
        logger.info(f"Processing webhook {event_type} for invoice {invoice_id}")
        # Extract payment date if available from payments list
        paid_at = datetime.now(timezone.utc).isoformat()
        payments = resource.get("payments") or (resource.get("invoice", {}).get("payments") if isinstance(resource.get("invoice"), dict) else {})
        if isinstance(payments, dict):
            transactions = payments.get("transactions", [])
            if transactions and isinstance(transactions, list) and "payment_date" in transactions[0]:
                paid_at = transactions[0]["payment_date"]

        inv = update_invoice_status(invoice_id, status="PAID", paid_at=paid_at, is_simulated=0, db_path=db_path)
        return {"processed": True, "event_type": event_type, "invoice_id": invoice_id, "status": "PAID", "invoice": inv}

    elif event_type == "INVOICING.INVOICE.CANCELLED":
        logger.info(f"Processing webhook {event_type} for invoice {invoice_id}")
        inv = update_invoice_status(invoice_id, status="CANCELLED", is_simulated=0, db_path=db_path)
        return {"processed": True, "event_type": event_type, "invoice_id": invoice_id, "status": "CANCELLED", "invoice": inv}

    elif event_type == "INVOICING.INVOICE.REFUNDED":
        logger.info(f"Processing webhook {event_type} for invoice {invoice_id}")
        inv = update_invoice_status(invoice_id, status="REFUNDED", is_simulated=0, db_path=db_path)
        return {"processed": True, "event_type": event_type, "invoice_id": invoice_id, "status": "REFUNDED", "invoice": inv}

    elif event_type in ("INVOICING.INVOICE.CREATED", "INVOICING.INVOICE.SENT") or event_type.endswith(".CREATED") or event_type.endswith(".SENT"):
        logger.debug(f"Unhandled webhook event type: {event_type}")
        return {"processed": False, "event_type": event_type, "reason": "Event type ignored"}

    else:
        logger.info(f"Unhandled webhook event type: {event_type}")
        return {"processed": False, "event_type": event_type, "reason": "Event type ignored"}
