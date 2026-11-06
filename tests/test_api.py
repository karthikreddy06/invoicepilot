import logging
import os
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from app.main import app, reset_chat_rate_limiter
from app.db import init_db, upsert_invoice, get_invoice_by_paypal_id


@pytest.fixture
def client_with_db(monkeypatch):
    reset_chat_rate_limiter()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    monkeypatch.setattr("app.config.settings.DB_PATH", path)
    with TestClient(app) as client:
        yield client
    if os.path.exists(path):
        os.remove(path)


def test_serve_index_html(client_with_db):
    response = client_with_db.get("/")
    assert response.status_code == 200
    assert "InvoicePilot" in response.text
    assert "PayPal Sandbox" in response.text


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


def test_webhook_invoice_paid_nested_invoice_shape(client_with_db):
    # Tests realistic PayPal Invoicing v2 webhook where resource has invoice.id
    upsert_invoice(
        paypal_invoice_id="INV2-NESTED-1234",
        client_email="client@test.com",
        description="Branding",
        amount=750.0,
        status="SENT",
    )

    with patch("app.main.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = True

        webhook_payload = {
            "id": "WH-EVENT-NESTED-1",
            "event_type": "INVOICING.INVOICE.PAID",
            "resource": {
                "id": "NOTIF-PAYMENT-8888",
                "invoice": {
                    "id": "INV2-NESTED-1234",
                    "status": "PAID",
                    "payments": {
                        "transactions": [{"payment_date": "2026-11-05T18:30:00Z"}]
                    }
                }
            }
        }

        response = client_with_db.post("/webhooks/paypal", json=webhook_payload)
        assert response.status_code == 200

        inv = get_invoice_by_paypal_id("INV2-NESTED-1234")
        assert inv["status"] == "PAID"
        assert inv["paid_at"] == "2026-11-05T18:30:00Z"
        assert inv["is_simulated"] == 0


def test_webhook_invoice_paid_links_shape(client_with_db):
    # Tests PayPal webhook where invoice ID is inside resource links/href
    upsert_invoice(
        paypal_invoice_id="INV2-LINKS-5678",
        client_email="client@test.com",
        description="Copywriting",
        amount=320.0,
        status="SENT",
    )

    with patch("app.main.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = True

        webhook_payload = {
            "id": "WH-EVENT-LINKS-2",
            "event_type": "INVOICING.INVOICE.PAID",
            "resource": {
                "id": "TXN-9999",
                "links": [
                    {
                        "href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-LINKS-5678",
                        "rel": "invoice",
                        "method": "GET"
                    }
                ]
            }
        }

        response = client_with_db.post("/webhooks/paypal", json=webhook_payload)
        assert response.status_code == 200

        inv = get_invoice_by_paypal_id("INV2-LINKS-5678")
        assert inv["status"] == "PAID"
        assert inv["is_simulated"] == 0


def test_webhook_invoice_refunded(client_with_db):
    upsert_invoice(
        paypal_invoice_id="INV2-REFUND-1",
        client_email="client@test.com",
        description="Consulting",
        amount=450.0,
        status="PAID",
    )

    with patch("app.main.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = True

        webhook_payload = {
            "id": "WH-EVENT-REFUND-1",
            "event_type": "INVOICING.INVOICE.REFUNDED",
            "resource": {
                "invoice": {
                    "id": "INV2-REFUND-1"
                }
            }
        }

        response = client_with_db.post("/webhooks/paypal", json=webhook_payload)
        assert response.status_code == 200

        inv = get_invoice_by_paypal_id("INV2-REFUND-1")
        assert inv["status"] == "REFUNDED"


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
    assert data["is_simulated"] is True
    assert "DEV ONLY ENDPOINT" in data["warning"]

    inv = get_invoice_by_paypal_id("INV2-SIM-1")
    assert inv["status"] == "PAID"
    assert inv["is_simulated"] == 1


def test_dev_reset_endpoint(client_with_db):
    upsert_invoice("INV-RESET-1", "user@test.com", "Test", 100.0, "SENT")
    response = client_with_db.post("/dev/reset")
    assert response.status_code == 200
    data = response.json()
    assert data["dev_mode"] is True
    assert data["result"]["success"] is True

    # Confirm database is empty
    invoices = client_with_db.get("/invoices").json()
    assert len(invoices) == 0


def test_sync_with_paypal_endpoint(client_with_db):
    upsert_invoice(
        paypal_invoice_id="INV2-SYNC-1",
        client_email="client@test.com",
        description="Consulting",
        amount=500.0,
        status="SENT",
    )

    with patch("app.paypal.invoices.get_invoice", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "id": "INV2-SYNC-1",
            "status": "PAID",
            "payments": {
                "transactions": [{"payment_date": "2026-11-05T18:00:00Z"}]
            }
        }

        response = client_with_db.post("/invoices/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["reconciled_count"] == 1

        inv = get_invoice_by_paypal_id("INV2-SYNC-1")
        assert inv["status"] == "PAID"
        assert inv["paid_at"] == "2026-11-05T18:00:00Z"
        assert inv["is_simulated"] == 0


def test_chat_endpoint_rate_limit(client_with_db):
    """Confirm per-IP rate limiting allows 20 requests per minute and blocks the 21st."""
    reset_chat_rate_limiter()
    with patch("app.main.run_agent", new_callable=AsyncMock) as mock_agent:
        mock_agent.return_value = ("Ack", [])
        payload = {"session_id": "rate_test", "message": "hello"}
        headers_ip1 = {"X-Forwarded-For": "198.51.100.1"}

        # 20 requests succeed
        for i in range(20):
            res = client_with_db.post("/chat", json=payload, headers=headers_ip1)
            assert res.status_code == 200, f"Request {i+1} failed"

        # 21st request from same IP is rate limited
        res21 = client_with_db.post("/chat", json=payload, headers=headers_ip1)
        assert res21.status_code == 429
        assert "Rate limit exceeded" in res21.json()["detail"]
        assert res21.headers.get("retry-after") == "60"

        # A different IP is NOT blocked (per-IP rate limit)
        headers_ip2 = {"X-Forwarded-For": "198.51.100.2"}
        res_ip2 = client_with_db.post("/chat", json=payload, headers=headers_ip2)
        assert res_ip2.status_code == 200


def test_dev_endpoints_protected_from_external_ip_without_token(client_with_db):
    """Dev endpoints return 403 Forbidden when called from non-localhost without DEV_ADMIN_TOKEN."""
    external_headers = {"X-Forwarded-For": "203.0.113.195"}

    # /dev/reset
    res_reset = client_with_db.post("/dev/reset", headers=external_headers)
    assert res_reset.status_code == 403
    assert "Forbidden" in res_reset.json()["detail"]

    # /dev/simulate-paid/{id}
    res_sim = client_with_db.post("/dev/simulate-paid/INV-999", headers=external_headers)
    assert res_sim.status_code == 403
    assert "Forbidden" in res_sim.json()["detail"]

    # /dev/trigger-chaser
    res_chaser = client_with_db.post("/dev/trigger-chaser", headers=external_headers)
    assert res_chaser.status_code == 403
    assert "Forbidden" in res_chaser.json()["detail"]


def test_dev_endpoints_allowed_with_dev_admin_token(client_with_db, monkeypatch):
    """Dev endpoints return 200 when called with a valid DEV_ADMIN_TOKEN header from external IP."""
    monkeypatch.setattr("app.config.settings.DEV_ADMIN_TOKEN", "super-secret-admin-key")
    external_ip = {"X-Forwarded-For": "203.0.113.195"}

    # With correct X-Dev-Admin-Token
    headers_valid = {**external_ip, "X-Dev-Admin-Token": "super-secret-admin-key"}
    res_reset = client_with_db.post("/dev/reset", headers=headers_valid)
    assert res_reset.status_code == 200
    assert res_reset.json()["dev_mode"] is True

    # With Authorization: Bearer token
    headers_bearer = {**external_ip, "Authorization": "Bearer super-secret-admin-key"}
    res_chaser = client_with_db.post("/dev/trigger-chaser", headers=headers_bearer)
    assert res_chaser.status_code == 200

    # With invalid token
    headers_invalid = {**external_ip, "X-Dev-Admin-Token": "wrong-secret"}
    res_invalid = client_with_db.post("/dev/reset", headers=headers_invalid)
    assert res_invalid.status_code == 403


def test_webhook_invoice_created_and_sent_debug_log(client_with_db, caplog):
    """Verify that CREATED and SENT webhook events are logged at DEBUG level, not INFO or WARNING."""
    with patch("app.main.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = True

        with caplog.at_level(logging.DEBUG):
            # Test CREATED event
            res_created = client_with_db.post("/webhooks/paypal", json={
                "id": "WH-CREATED-1",
                "event_type": "INVOICING.INVOICE.CREATED",
                "resource": {"id": "INV2-NEW-1"}
            })
            assert res_created.status_code == 200
            assert res_created.json()["result"]["processed"] is False

            # Test SENT event
            res_sent = client_with_db.post("/webhooks/paypal", json={
                "id": "WH-SENT-1",
                "event_type": "INVOICING.INVOICE.SENT",
                "resource": {"id": "INV2-NEW-1"}
            })
            assert res_sent.status_code == 200
            assert res_sent.json()["result"]["processed"] is False

            # Verify log records: must be DEBUG level for "Unhandled webhook event type"
            unhandled_records = [
                rec for rec in caplog.records
                if "Unhandled webhook event type" in rec.message
            ]
            assert len(unhandled_records) >= 2
            for rec in unhandled_records:
                assert rec.levelno == logging.DEBUG
                assert rec.levelname == "DEBUG"

