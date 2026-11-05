from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
import httpx
from app.paypal.client import PayPalAPIError, paypal_client


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
        return await _handle_response(resp, "create_draft_invoice")


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

