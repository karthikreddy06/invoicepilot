import pytest
import os
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, upsert_invoice, get_invoice_by_paypal_id


@pytest.fixture
def client_with_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    monkeypatch.setattr("app.config.settings.DB_PATH", path)
    with TestClient(app) as client:
        yield client
    if os.path.exists(path):
        os.remove(path)


def test_health_endpoint(client_with_db):
    response = client_with_db.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_list_invoices_endpoint(client_with_db):
    response = client_with_db.get("/invoices")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_chat_endpoint(client_with_db):
    with patch("app.main.run_agent", new_callable=AsyncMock) as mock_agent:
        mock_agent.return_value = ("I have created the invoice.", [{"tool": "create_and_send_invoice"}])
        payload = {"session_id": "test_session", "message": "Invoice bob@example.com $300 for UI design"}
        response = client_with_db.post("/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "I have created the invoice."
        assert len(data["actions_taken"]) == 1


def test_webhook_invoice_paid(client_with_db, monkeypatch):
    # Seed an invoice
    upsert_invoice(
        paypal_invoice_id="INV2-WEBHOOK-1",
        client_email="payer@test.com",
        description="Landing page",
        amount=600.0,
        status="SENT",
    )

    with patch("app.main.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = True

        webhook_payload = {
            "id": "WH-EVENT-123",
            "event_type": "INVOICING.INVOICE.PAID",
            "resource": {
                "id": "INV2-WEBHOOK-1",
                "payments": {
                    "transactions": [{"payment_date": "2026-11-05T10:00:00Z"}]
                }
            }
        }

        response = client_with_db.post("/webhooks/paypal", json=webhook_payload)
        assert response.status_code == 200

        inv = get_invoice_by_paypal_id("INV2-WEBHOOK-1")
        assert inv["status"] == "PAID"
        assert inv["paid_at"] == "2026-11-05T10:00:00Z"


def test_webhook_invoice_cancelled(client_with_db):
    upsert_invoice(
        paypal_invoice_id="INV2-CANCELLED-1",
        client_email="payer@test.com",
        description="SEO",
        amount=250.0,
        status="SENT",
    )

    with patch("app.main.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = True

        webhook_payload = {
            "id": "WH-EVENT-124",
            "event_type": "INVOICING.INVOICE.CANCELLED",
            "resource": {
                "id": "INV2-CANCELLED-1"
            }
        }

        response = client_with_db.post("/webhooks/paypal", json=webhook_payload)
        assert response.status_code == 200

        inv = get_invoice_by_paypal_id("INV2-CANCELLED-1")
        assert inv["status"] == "CANCELLED"


def test_dev_simulate_paid(client_with_db):
    upsert_invoice(
        paypal_invoice_id="INV2-SIM-1",
        client_email="sim@test.com",
        description="App Dev",
        amount=1000.0,
        status="SENT",
    )

    response = client_with_db.post("/dev/simulate-paid/INV2-SIM-1")
    assert response.status_code == 200
    data = response.json()
    assert data["dev_mode"] is True
    assert data["status"] == "PAID"
    assert "DEV ONLY ENDPOINT" in data["warning"]

    inv = get_invoice_by_paypal_id("INV2-SIM-1")
    assert inv["status"] == "PAID"
