import logging
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional
import httpx
from app.paypal.client import PayPalAPIError, paypal_client

logger = logging.getLogger(__name__)


async def _handle_response(response: httpx.Response, action_name: str) -> Any:
    """Helper to parse response or raise a descriptive PayPalAPIError."""
    if response.is_error:
        try:
            err_body = response.json()
        except Exception:
            err_body = response.text
        raise PayPalAPIError(
            status_code=response.status_code,
            response_body=err_body,
            message=f"PayPal error during {action_name} ({response.status_code}): {err_body}",
        )
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


async def create_draft_invoice(
    client_email: str,
    description: str,
    amount: float,
    due_date: Optional[str] = None,
    note: Optional[str] = None,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Create a draft invoice in PayPal sandbox (POST /v2/invoicing/invoices).

    :param client_email: The payer's email address.
    :param description: Description of goods/services provided.
    :param amount: Total amount in USD.
    :param due_date: ISO date string 'YYYY-MM-DD' or None. If None, defaults to 15 days ahead.
    :param note: Optional merchant note.
    """
    api_client = client or paypal_client
    headers = await api_client.get_headers()
    today_str = date.today().isoformat()

    if not due_date:
        due_date = (date.today() + timedelta(days=15)).isoformat()

    payload = {
        "detail": {
            "currency_code": "USD",
            "invoice_date": today_str,
            "payment_term": {
                "term_type": "DUE_ON_DATE_SPECIFIED",
                "due_date": due_date,
            },
            "note": note or f"Invoice for {description}",
        },
        "primary_recipients": [
            {
                "billing_info": {
                    "email_address": client_email,
                }
            }
        ],
        "items": [
            {
                "name": description[:250],
                "quantity": "1",
                "unit_amount": {
                    "currency_code": "USD",
                    "value": f"{amount:.2f}",
                },
            }
        ],
    }

    url = f"{api_client.base_url}/v2/invoicing/invoices"
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
        data = await _handle_response(resp, "create_draft_invoice")
        # PayPal returns {"rel": "self", "href": "https://api.sandbox.paypal.com/v2/invoicing/invoices/INV2-...", "method": "GET"}
        # If "id" is not already present, extract from the end of href:
        if isinstance(data, dict):
            if "id" not in data and "href" in data:
                data["id"] = data["href"].rstrip("/").split("/")[-1]
        return data


async def send_invoice(
    invoice_id: str,
    send_to_recipient: bool = True,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Send an existing draft invoice to the recipient (POST /v2/invoicing/invoices/{id}/send).
    """
    api_client = client or paypal_client
    headers = await api_client.get_headers()
    url = f"{api_client.base_url}/v2/invoicing/invoices/{invoice_id}/send"
    payload = {"send_to_recipient": send_to_recipient}

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
        result = await _handle_response(resp, f"send_invoice({invoice_id})")
        if not result:
            result = {"status": "SENT", "id": invoice_id}
        return result


async def get_invoice(
    invoice_id: str,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Retrieve invoice details by ID (GET /v2/invoicing/invoices/{id}).
    """
    api_client = client or paypal_client
    headers = await api_client.get_headers()
    url = f"{api_client.base_url}/v2/invoicing/invoices/{invoice_id}"

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(url, headers=headers)
        return await _handle_response(resp, f"get_invoice({invoice_id})")


async def list_invoices(
    page: int = 1,
    page_size: int = 20,
    total_required: bool = True,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    List invoices from PayPal sandbox (GET /v2/invoicing/invoices).
    """
    api_client = client or paypal_client
    headers = await api_client.get_headers()
    url = f"{api_client.base_url}/v2/invoicing/invoices"
    params = {
        "page": page,
        "page_size": page_size,
        "total_required": str(total_required).lower(),
    }

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(url, params=params, headers=headers)
        return await _handle_response(resp, "list_invoices")


async def send_reminder(
    invoice_id: str,
    subject: Optional[str] = None,
    note: Optional[str] = None,
    send_to_recipient: bool = True,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Send a reminder for an unpaid invoice (POST /v2/invoicing/invoices/{id}/remind).
    """
    api_client = client or paypal_client
    headers = await api_client.get_headers()
    url = f"{api_client.base_url}/v2/invoicing/invoices/{invoice_id}/remind"
    payload = {
        "subject": subject or "Friendly Reminder: Invoice Payment Due",
        "note": note or "This is a reminder regarding your pending invoice payment.",
        "send_to_recipient": send_to_recipient,
    }

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
        result = await _handle_response(resp, f"send_reminder({invoice_id})")
        return result or {"success": True, "invoice_id": invoice_id, "message": "Reminder sent successfully"}


async def cancel_invoice(
    invoice_id: str,
    subject: Optional[str] = None,
    note: Optional[str] = None,
    send_to_recipient: bool = True,
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Cancel an existing invoice (POST /v2/invoicing/invoices/{id}/cancel).
    """
    api_client = client or paypal_client
    headers = await api_client.get_headers()
    url = f"{api_client.base_url}/v2/invoicing/invoices/{invoice_id}/cancel"
    payload = {
        "subject": subject or "Invoice Cancellation Notice",
        "note": note or "This invoice has been cancelled.",
        "send_to_recipient": send_to_recipient,
    }

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
        result = await _handle_response(resp, f"cancel_invoice({invoice_id})")
        return result or {"success": True, "invoice_id": invoice_id, "message": "Invoice cancelled successfully"}


async def reconcile_invoices_with_paypal(
    client: Optional[Any] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Reconciles all non-final local invoices with live PayPal Sandbox status.
    Calls GET /v2/invoicing/invoices/{id} for each invoice and syncs any status changes into SQLite.
    """
    from app.db import get_non_final_invoices, update_invoice_status

    non_final = get_non_final_invoices(db_path=db_path)
    updated_records = []

    for inv in non_final:
        inv_id = inv["paypal_invoice_id"]
        try:
            remote_data = await get_invoice(inv_id, client=client)
            remote_status = remote_data.get("status")

            if not remote_status:
                continue

            mapped_status = "PAID" if remote_status in ("PAID", "MARKED_AS_PAID") else remote_status

            if mapped_status != inv.get("status"):
                paid_at = None
                if mapped_status == "PAID":
                    payments = remote_data.get("payments", {})
                    transactions = payments.get("transactions", [])
                    if transactions and "payment_date" in transactions[0]:
                        paid_at = transactions[0]["payment_date"]
                    else:
                        paid_at = datetime.now(timezone.utc).isoformat()

                updated = update_invoice_status(
                    paypal_invoice_id=inv_id,
                    status=mapped_status,
                    paid_at=paid_at,
                    is_simulated=0,
                    db_path=db_path,
                )
                if updated:
                    logger.info(f"Reconciled invoice {inv_id}: {inv.get('status')} -> {mapped_status}")
                    updated_records.append(updated)
        except Exception as exc:
            logger.warning(f"Could not reconcile invoice {inv_id} with PayPal: {exc}")

    return updated_records

