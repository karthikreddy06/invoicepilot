import os
import tempfile
from datetime import datetime, timezone, timedelta, date
from unittest.mock import AsyncMock, patch
import pytest
from app.db import init_db, upsert_invoice, get_invoice_by_paypal_id, get_reminders_for_invoice
from app.scheduler import (
    generate_escalated_reminder,
    is_invoice_overdue,
    run_chaser_job,
)


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    monkeypatch.setattr("app.config.settings.DB_PATH", path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_escalated_reminder_tones():
    r1 = generate_escalated_reminder(1, "INV-1", 400.0, "2026-11-01")
    assert "Friendly" in r1["subject"]
    assert "gentle reminder" in r1["note"].lower()

    r2 = generate_escalated_reminder(2, "INV-1", 400.0, "2026-11-01")
    assert "Second Notice" in r2["subject"]
    assert "following up" in r2["note"].lower()

    r3 = generate_escalated_reminder(3, "INV-1", 400.0, "2026-11-01")
    assert "URGENT / FINAL NOTICE" in r3["subject"]
    assert "final payment notice" in r3["note"].lower()


def test_is_invoice_overdue_demo_mode():
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=70)).isoformat()
    inv_old = {"created_at": old_time, "due_date": "2030-01-01"}
    assert is_invoice_overdue(inv_old, demo_mode=True) is True

    recent_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    inv_recent = {"created_at": recent_time, "due_date": "2030-01-01"}
    assert is_invoice_overdue(inv_recent, demo_mode=True) is False


def test_is_invoice_overdue_standard_mode():
    past_due = (date.today() - timedelta(days=2)).isoformat()
    inv_overdue = {"due_date": past_due}
    assert is_invoice_overdue(inv_overdue, demo_mode=False) is True

    future_due = (date.today() + timedelta(days=5)).isoformat()
    inv_future = {"due_date": future_due}
    assert is_invoice_overdue(inv_future, demo_mode=False) is False


@pytest.mark.asyncio
async def test_run_chaser_job_workflow(temp_db):
    old_created = (datetime.now(timezone.utc) - timedelta(seconds=80)).isoformat()
    upsert_invoice(
        paypal_invoice_id="INV-CHASE-1",
        client_email="chase@test.com",
        description="Branding",
        amount=750.0,
        status="SENT",
        created_at=old_created,
        db_path=temp_db,
    )

    with patch("app.scheduler.send_reminder", new_callable=AsyncMock) as mock_send, \
         patch("app.paypal.invoices.get_invoice", new_callable=AsyncMock) as mock_get_inv:
        mock_send.return_value = {"success": True}
        mock_get_inv.return_value = {"id": "INV-CHASE-1", "status": "SENT"}

        # 1st run: sends reminder #1
        actions1 = await run_chaser_job(demo_mode=True)
        assert len(actions1) == 1
        assert actions1[0]["reminder_number"] == 1
        assert actions1[0]["status"] == "SENT"

        reminders = get_reminders_for_invoice("INV-CHASE-1", db_path=temp_db)
        assert len(reminders) == 1
        assert "Friendly" in reminders[0]["message"]

        # 2nd run immediately: throttled because <30s
        actions2 = await run_chaser_job(demo_mode=True)
        assert len(actions2) == 0

        # Simulate time passing by manually modifying reminder sent_at
        from app.db import get_db_connection
        with get_db_connection(temp_db) as conn:
            old_rem_time = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
            conn.execute("UPDATE reminders SET sent_at = ?", (old_rem_time,))
            conn.commit()

        # 2nd run: sends reminder #2 (escalated)
        actions3 = await run_chaser_job(demo_mode=True)
        assert len(actions3) == 1
        assert actions3[0]["reminder_number"] == 2

        # Simulate time passing again
        with get_db_connection(temp_db) as conn:
            old_rem_time = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
            conn.execute("UPDATE reminders SET sent_at = ?", (old_rem_time,))
            conn.commit()

        # 3rd run: sends reminder #3 (final notice)
        actions4 = await run_chaser_job(demo_mode=True)
        assert len(actions4) == 1
        assert actions4[0]["reminder_number"] == 3

        # Simulate time passing again
        with get_db_connection(temp_db) as conn:
            old_rem_time = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
            conn.execute("UPDATE reminders SET sent_at = ?", (old_rem_time,))
            conn.commit()

        # 4th run: reached max 3 reminders, no more should be sent
        actions5 = await run_chaser_job(demo_mode=True)
        assert len(actions5) == 0


@pytest.mark.asyncio
async def test_chaser_reconciles_and_skips_paid_invoice(temp_db):
    old_created = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    upsert_invoice(
        paypal_invoice_id="INV-ALREADY-PAID",
        client_email="payer@test.com",
        description="SEO Work",
        amount=300.0,
        status="SENT",
        created_at=old_created,
        db_path=temp_db,
    )

    with patch("app.paypal.invoices.get_invoice", new_callable=AsyncMock) as mock_get_inv, \
         patch("app.scheduler.send_reminder", new_callable=AsyncMock) as mock_send:
        # PayPal says this invoice is actually PAID
        mock_get_inv.return_value = {
            "id": "INV-ALREADY-PAID",
            "status": "PAID",
            "payments": {"transactions": [{"payment_date": "2026-11-05T17:00:00Z"}]}
        }

        # Run chaser
        actions = await run_chaser_job(demo_mode=True, db_path=temp_db)

        # Confirm NO reminder was sent
        assert len(actions) == 0
        mock_send.assert_not_called()

        # Confirm DB status was reconciled to PAID
        inv = get_invoice_by_paypal_id("INV-ALREADY-PAID", db_path=temp_db)
        assert inv["status"] == "PAID"
        assert inv["paid_at"] == "2026-11-05T17:00:00Z"

