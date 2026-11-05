import asyncio
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional
from app.config import settings
from app.db import (
    get_unpaid_invoices,
    get_reminder_count,
    get_reminders_for_invoice,
    record_reminder,
    update_invoice_status,
)
from app.paypal.invoices import send_reminder, get_invoice
from app.paypal.client import PayPalAPIError

logger = logging.getLogger(__name__)

# Control event for background task
_stop_event = asyncio.Event()
_scheduler_task: Optional[asyncio.Task] = None


def generate_escalated_reminder(
    reminder_number: int,
    invoice_id: str,
    amount: float,
    due_date: Optional[str] = None,
) -> Dict[str, str]:
    """
    Generate subject and escalating message tone based on reminder count (1-based).
    Reminder 1: Friendly
    Reminder 2: Direct / Firming
    Reminder 3: Urgent / Final notice
    """
    due_str = due_date or "the specified date"
    if reminder_number == 1:
        return {
            "subject": f"Friendly Reminder: Invoice {invoice_id} is due",
            "note": (
                f"Hi there! Just a gentle reminder that invoice {invoice_id} for ${amount:.2f} USD "
                f"was due on {due_str}. We appreciate your business—please let us know if you have any questions!"
            ),
        }
    elif reminder_number == 2:
        return {
            "subject": f"Second Notice: Overdue Invoice {invoice_id}",
            "note": (
                f"Hello, following up on our previous notice. Invoice {invoice_id} for ${amount:.2f} USD "
                f"is currently overdue. Please process payment at your earliest convenience to keep your account in good standing."
            ),
        }
    else:
        return {
            "subject": f"URGENT / FINAL NOTICE: Invoice {invoice_id} Payment Overdue",
            "note": (
                f"Important: Invoice {invoice_id} for ${amount:.2f} USD is now significantly past due. "
                f"This is our final payment notice. Please settle the outstanding balance immediately to avoid escalation."
            ),
        }


def is_invoice_overdue(inv: Dict[str, Any], demo_mode: bool = False) -> bool:
    """
    Determine if an invoice is overdue.
    In DEMO_MODE: overdue if created more than 60 seconds ago.
    In standard mode: overdue if due_date < current date.
    """
    now = datetime.now(timezone.utc)

    if demo_mode:
        try:
            created_at_str = inv.get("created_at", "")
            # Handle standard ISO strings
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            return (now - created_at).total_seconds() >= 60
        except Exception as e:
            logger.debug(f"Error parsing created_at: {e}")
            return False

    due_date_str = inv.get("due_date")
    if not due_date_str:
        return False

    try:
        due_d = date.fromisoformat(due_date_str[:10])
        return date.today() > due_d
    except Exception as e:
        logger.debug(f"Error parsing due_date: {e}")
        return False


async def run_chaser_job(demo_mode: Optional[bool] = None) -> List[Dict[str, Any]]:
    """
    Scan for unpaid overdue invoices and send escalating reminders (up to 3 max).
    """
    is_demo = settings.DEMO_MODE if demo_mode is None else demo_mode
    unpaid_invoices = get_unpaid_invoices()
    actions_taken: List[Dict[str, Any]] = []

    for inv in unpaid_invoices:
        invoice_id = inv["paypal_invoice_id"]
        status = inv.get("status", "").upper()

        if status not in ("SENT", "UNPAID", "PARTIALLY_PAID"):
            continue

        # Check if overdue
        if not is_invoice_overdue(inv, demo_mode=is_demo):
            continue

        # Check how many reminders have already been sent
        rem_count = get_reminder_count(invoice_id)
        if rem_count >= 3:
            logger.info(f"Invoice {invoice_id} has reached maximum 3 reminders. Skipping.")
            continue

        # Check throttle: in demo mode require at least 30s since last reminder; in prod 24h
        prior_reminders = get_reminders_for_invoice(invoice_id)
        if prior_reminders:
            last_rem = prior_reminders[-1]
            try:
                last_time = datetime.fromisoformat(last_rem["sent_at"].replace("Z", "+00:00"))
                min_interval = 30 if is_demo else 86400
                if (datetime.now(timezone.utc) - last_time).total_seconds() < min_interval:
                    continue
            except Exception:
                pass

        next_reminder_num = rem_count + 1
        reminder_content = generate_escalated_reminder(
            reminder_number=next_reminder_num,
            invoice_id=invoice_id,
            amount=inv["amount"],
            due_date=inv.get("due_date"),
        )

        logger.info(f"Chaser sending reminder #{next_reminder_num} for invoice {invoice_id} (Demo={is_demo})")

        try:
            # Send reminder through PayPal API
            await send_reminder(
                invoice_id=invoice_id,
                subject=reminder_content["subject"],
                note=reminder_content["note"],
            )

            # Record in DB
            full_msg = f"[{reminder_content['subject']}] {reminder_content['note']}"
            db_record = record_reminder(invoice_id, message=full_msg)

            actions_taken.append({
                "invoice_id": invoice_id,
                "reminder_number": next_reminder_num,
                "subject": reminder_content["subject"],
                "status": "SENT",
                "recorded": db_record,
            })
        except PayPalAPIError as err:
            logger.error(f"PayPal error while chasing invoice {invoice_id}: {err}")
            actions_taken.append({
                "invoice_id": invoice_id,
                "reminder_number": next_reminder_num,
                "status": "FAILED",
                "error": str(err),
            })
        except Exception as err:
            logger.error(f"Unexpected error while chasing invoice {invoice_id}: {err}")
            actions_taken.append({
                "invoice_id": invoice_id,
                "reminder_number": next_reminder_num,
                "status": "ERROR",
                "error": str(err),
            })

    return actions_taken


async def chaser_loop() -> None:
    """Continuous background loop executing every CHASER_INTERVAL_SECONDS."""
    logger.info(f"Payment chaser background service started (Interval: {settings.CHASER_INTERVAL_SECONDS}s, Demo: {settings.DEMO_MODE})")
    while not _stop_event.is_set():
        try:
            await run_chaser_job()
        except Exception as exc:
            logger.error(f"Exception in chaser background loop: {exc}")

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=float(settings.CHASER_INTERVAL_SECONDS))
        except asyncio.TimeoutError:
            pass


def start_scheduler() -> None:
    """Start the background chaser task."""
    global _scheduler_task, _stop_event
    _stop_event.clear()
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(chaser_loop())


def stop_scheduler() -> None:
    """Signal background chaser to stop."""
    global _stop_event
    _stop_event.set()
