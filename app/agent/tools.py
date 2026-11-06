from datetime import date, timedelta
from typing import Any, Dict, List, Optional
import logging
from app.db import (
    upsert_invoice,
    update_invoice_status,
    get_invoice_by_paypal_id,
    get_all_invoices,
    record_reminder,
)
from app.paypal.invoices import (
    create_draft_invoice,
    send_invoice,
    get_invoice,
    send_reminder as pp_send_reminder,
    cancel_invoice as pp_cancel_invoice,
    delete_draft_invoice,
)

logger = logging.getLogger(__name__)

# OpenAI-compatible Function Calling Tools Schema
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "create_and_send_invoice",
            "description": "Create a new PayPal draft invoice and immediately send it to the client. Also stores the invoice in the local database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_email": {
                        "type": "string",
                        "description": "The recipient's email address.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the services or goods delivered.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Total amount in USD.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date in YYYY-MM-DD format. Defaults to 15 days from now if omitted.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional message or payment note to the client.",
                    },
                },
                "required": ["client_email", "description", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_invoices",
            "description": "List existing invoices from the database, optionally filtered by status (e.g. SENT, PAID, DRAFT, CANCELLED).",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by invoice status: DRAFT, SENT, PAID, CANCELLED, or leave empty for all.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_invoice_status",
            "description": "Fetch the latest status and details of a specific invoice by PayPal invoice ID, syncing with PayPal sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The PayPal invoice ID (e.g. INV2-XXXX-XXXX-XXXX-XXXX).",
                    },
                },
                "required": ["invoice_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_reminder",
            "description": "Send a formal payment reminder to the client for an outstanding invoice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The PayPal invoice ID.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Custom reminder text or note to accompany the email reminder.",
                    },
                },
                "required": ["invoice_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_invoice",
            "description": "Cancel an existing invoice on PayPal and mark it as CANCELLED in the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The PayPal invoice ID to cancel.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for cancellation.",
                    },
                },
                "required": ["invoice_id"],
            },
        },
    },
]


async def tool_create_and_send_invoice(
    client_email: str,
    description: str,
    amount: float,
    due_date: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    if not due_date:
        due_date = (date.today() + timedelta(days=15)).isoformat()

    # Step 1: Create draft invoice on PayPal
    draft = await create_draft_invoice(
        client_email=client_email,
        description=description,
        amount=amount,
        due_date=due_date,
        note=note,
    )
    invoice_id = draft.get("id")
    if not invoice_id and "href" in draft:
        invoice_id = draft["href"].rstrip("/").split("/")[-1]
        draft["id"] = invoice_id

    if not invoice_id:
        raise ValueError(f"PayPal did not return an invoice ID: {draft}")

    # Step 2: Send invoice (with automatic cleanup of orphan draft if sending fails)
    try:
        await send_invoice(invoice_id)
    except Exception as send_err:
        logger.error(
            f"Failed to send draft invoice {invoice_id}: {send_err}. Deleting draft to prevent orphan."
        )
        try:
            await delete_draft_invoice(invoice_id)
        except Exception as del_err:
            logger.warning(f"Could not delete orphan draft invoice {invoice_id}: {del_err}")
        raise send_err

    # Step 3: Record in local database (only stored if send succeeded)
    record = upsert_invoice(
        paypal_invoice_id=invoice_id,
        client_email=client_email,
        description=description,
        amount=amount,
        status="SENT",
        due_date=due_date,
    )

    return {
        "success": True,
        "invoice_id": invoice_id,
        "client_email": client_email,
        "amount": amount,
        "description": description,
        "status": "SENT",
        "due_date": due_date,
        "message": f"Successfully created and sent PayPal invoice {invoice_id} for ${amount:.2f} USD to {client_email}.",
    }


async def tool_list_invoices(status: Optional[str] = None) -> Dict[str, Any]:
    invoices = get_all_invoices(status=status)
    return {
        "total": len(invoices),
        "filter_status": status or "ALL",
        "invoices": invoices,
    }


async def tool_get_invoice_status(invoice_id: str) -> Dict[str, Any]:
    local_inv = get_invoice_by_paypal_id(invoice_id)
    # Check PayPal for latest status
    try:
        remote_inv = await get_invoice(invoice_id)
        remote_status = remote_inv.get("status")
        if remote_status and local_inv and local_inv.get("status") != remote_status:
            paid_at = None
            if remote_status == "PAID":
                payments = remote_inv.get("payments", {})
                transactions = payments.get("transactions", [])
                if transactions:
                    paid_at = transactions[0].get("payment_date")
            local_inv = update_invoice_status(invoice_id, status=remote_status, paid_at=paid_at)
        elif not local_inv and remote_status:
            # Sync remote invoice into local DB
            detail = remote_inv.get("detail", {})
            amount_info = remote_inv.get("amount", {})
            val = float(amount_info.get("value", 0.0))
            recipients = remote_inv.get("primary_recipients", [{}])
            email = recipients[0].get("billing_info", {}).get("email_address", "unknown@example.com")
            desc = "Synced from PayPal"
            items = remote_inv.get("items", [])
            if items:
                desc = items[0].get("name", desc)
            due_d = detail.get("payment_term", {}).get("due_date")
            local_inv = upsert_invoice(
                paypal_invoice_id=invoice_id,
                client_email=email,
                description=desc,
                amount=val,
                status=remote_status,
                due_date=due_d,
            )
    except Exception as exc:
        logger.warning(f"Could not refresh invoice from PayPal: {exc}")

    if not local_inv:
        return {"found": False, "invoice_id": invoice_id, "message": "Invoice not found"}
    return {"found": True, "invoice": local_inv}


async def tool_send_reminder(invoice_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    rem_text = note or "Friendly reminder that payment for this invoice is due."
    await pp_send_reminder(invoice_id, note=rem_text)
    record = record_reminder(invoice_id, rem_text)
    return {
        "success": True,
        "invoice_id": invoice_id,
        "reminder": record,
        "message": f"Payment reminder sent for invoice {invoice_id}.",
    }


async def tool_cancel_invoice(invoice_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    await pp_cancel_invoice(invoice_id, note=reason)
    updated = update_invoice_status(invoice_id, "CANCELLED")
    return {
        "success": True,
        "invoice_id": invoice_id,
        "status": "CANCELLED",
        "message": f"Invoice {invoice_id} has been cancelled.",
    }


TOOL_HANDLERS = {
    "create_and_send_invoice": tool_create_and_send_invoice,
    "list_invoices": tool_list_invoices,
    "get_invoice_status": tool_get_invoice_status,
    "send_reminder": tool_send_reminder,
    "cancel_invoice": tool_cancel_invoice,
}


async def dispatch_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(**args)
