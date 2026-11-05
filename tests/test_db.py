import os
import pytest
import tempfile
from app.db import (
    init_db,
    upsert_invoice,
    update_invoice_status,
    get_invoice_by_paypal_id,
    get_all_invoices,
    record_reminder,
    get_reminders_for_invoice,
    get_unpaid_invoices,
)

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_init_and_upsert_invoice(temp_db):
    inv = upsert_invoice(
        paypal_invoice_id="INV2-TEST-1234",
        client_email="sarah@example.com",
        description="Logo Design",
        amount=400.0,
        status="DRAFT",
        due_date="2026-12-01",
        db_path=temp_db,
    )
    assert inv["paypal_invoice_id"] == "INV2-TEST-1234"
    assert inv["status"] == "DRAFT"
    assert inv["amount"] == 400.0
    assert inv["reminder_count"] == 0

    # Upsert with new status
    updated = upsert_invoice(
        paypal_invoice_id="INV2-TEST-1234",
        client_email="sarah@example.com",
        description="Logo Design",
        amount=400.0,
        status="SENT",
        due_date="2026-12-01",
        db_path=temp_db,
    )
    assert updated["status"] == "SENT"


def test_update_status_and_paid_at(temp_db):
    upsert_invoice(
        paypal_invoice_id="INV2-ABC",
        client_email="john@example.com",
        description="Web Dev",
        amount=1200.0,
        status="SENT",
        db_path=temp_db,
    )
    res = update_invoice_status("INV2-ABC", status="PAID", paid_at="2026-11-05T12:00:00Z", db_path=temp_db)
    assert res["status"] == "PAID"
    assert res["paid_at"] == "2026-11-05T12:00:00Z"


def test_reminders_recording(temp_db):
    upsert_invoice(
        paypal_invoice_id="INV2-REMIND",
        client_email="client@example.com",
        description="Consulting",
        amount=500.0,
        status="SENT",
        db_path=temp_db,
    )
    rem1 = record_reminder("INV2-REMIND", "Reminder 1: Friendly ping", db_path=temp_db)
    assert rem1["invoice_id"] == "INV2-REMIND"
    assert rem1["message"] == "Reminder 1: Friendly ping"

    rem2 = record_reminder("INV2-REMIND", "Reminder 2: Second notice", db_path=temp_db)
    reminders = get_reminders_for_invoice("INV2-REMIND", db_path=temp_db)
    assert len(reminders) == 2

    inv = get_invoice_by_paypal_id("INV2-REMIND", db_path=temp_db)
    assert inv["reminder_count"] == 2


def test_get_unpaid_invoices(temp_db):
    upsert_invoice("INV-1", "a@test.com", "Task 1", 100, "SENT", db_path=temp_db)
    upsert_invoice("INV-2", "b@test.com", "Task 2", 200, "PAID", db_path=temp_db)
    upsert_invoice("INV-3", "c@test.com", "Task 3", 300, "UNPAID", db_path=temp_db)

    unpaid = get_unpaid_invoices(db_path=temp_db)
    ids = [i["paypal_invoice_id"] for i in unpaid]
    assert "INV-1" in ids
    assert "INV-3" in ids
    assert "INV-2" not in ids

