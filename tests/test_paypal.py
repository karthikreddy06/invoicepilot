import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from app.paypal.client import PayPalClient, PayPalAPIError
from app.paypal.invoices import (
    create_draft_invoice,
    send_invoice,
    get_invoice,
    list_invoices,
    send_reminder,
    cancel_invoice,
)

@pytest.fixture
def mock_client():
    client = PayPalClient(client_id="test_id", secret="test_secret")
    client.get_access_token = AsyncMock(return_value="mock_access_token")
    client.get_headers = AsyncMock(return_value={
        "Authorization": "Bearer mock_access_token",
        "Content-Type": "application/json",
    })
    return client


@pytest.mark.asyncio
async def test_get_access_token():
    client = PayPalClient(client_id="id", secret="sec")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "token123", "expires_in": 3600}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        token = await client.get_access_token()
        assert token == "token123"


@pytest.mark.asyncio
async def test_get_access_token_failure():
    client = PayPalClient(client_id="id", secret="sec")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"error": "invalid_client"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(PayPalAPIError) as exc_info:
            await client.get_access_token()
        assert exc_info.value.status_code == 401
        assert "invalid_client" in str(exc_info.value.response_body)


@pytest.mark.asyncio
async def test_create_draft_invoice(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": "INV2-1234-5678", "status": "DRAFT"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await create_draft_invoice(
            client_email="sarah@example.com",
            description="Logo design",
            amount=400.0,
            client=mock_client,
        )
        assert res["id"] == "INV2-1234-5678"
        assert res["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_create_draft_invoice_extracts_id_from_href(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "rel": "self",
        "href": "https://api.sandbox.paypal.com/v2/invoicing/invoices/INV2-EXTRACT-9999",
        "method": "GET"
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await create_draft_invoice(
            client_email="sarah@example.com",
            description="Logo design",
            amount=400.0,
            client=mock_client,
        )
        assert res["id"] == "INV2-EXTRACT-9999"


@pytest.mark.asyncio
async def test_send_invoice(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 200
    mock_resp.content = b'{"href":"https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-1234"}'
    mock_resp.json.return_value = {"href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-1234"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await send_invoice("INV2-1234-5678", client=mock_client)
        assert "href" in res


@pytest.mark.asyncio
async def test_get_invoice(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "INV2-1234-5678", "status": "SENT"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await get_invoice("INV2-1234-5678", client=mock_client)
        assert res["id"] == "INV2-1234-5678"
        assert res["status"] == "SENT"


@pytest.mark.asyncio
async def test_list_invoices(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"total_items": 1, "items": [{"id": "INV2-1"}]}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await list_invoices(client=mock_client)
        assert res["total_items"] == 1


@pytest.mark.asyncio
async def test_send_reminder(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 204
    mock_resp.content = b""

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await send_reminder("INV2-1234-5678", client=mock_client)
        assert res["success"] is True


@pytest.mark.asyncio
async def test_cancel_invoice(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 204
    mock_resp.content = b""

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await cancel_invoice("INV2-1234-5678", client=mock_client)
        assert res["success"] is True


@pytest.mark.asyncio
async def test_paypal_error_handling(mock_client):
    mock_resp = MagicMock()
    mock_resp.is_error = True
    mock_resp.status_code = 404
    mock_resp.json.return_value = {"name": "RESOURCE_NOT_FOUND", "message": "Invoice not found"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with pytest.raises(PayPalAPIError) as exc_info:
            await get_invoice("INVALID_ID", client=mock_client)
        assert exc_info.value.status_code == 404
        assert "RESOURCE_NOT_FOUND" in str(exc_info.value.response_body)


@pytest.mark.asyncio
async def test_delete_draft_invoice(mock_client):
    from app.paypal.invoices import delete_draft_invoice

    mock_resp = MagicMock()
    mock_resp.status_code = 204

    with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
        mock_delete.return_value = mock_resp
        res = await delete_draft_invoice("INV2-DRAFT-123", client=mock_client)
        assert res is True
        mock_delete.assert_called_once()
        assert "INV2-DRAFT-123" in mock_delete.call_args[0][0]


@pytest.mark.asyncio
async def test_reconciliation_minimum_interval_and_force(mock_client, tmp_path):
    import time
    from app.db import init_db, upsert_invoice
    from app.paypal.invoices import reconcile_invoices_with_paypal, _last_reconciliation_time
    import app.paypal.invoices as inv_mod

    db_path = str(tmp_path / "test_reconcile.db")
    init_db(db_path)
    upsert_invoice("INV2-REC-1", "user@test.com", "Dev", 100.0, "SENT", db_path=db_path)

    # Reset last reconciliation time to 0
    inv_mod._last_reconciliation_time = 0.0

    mock_resp = MagicMock()
    mock_resp.is_error = False
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "INV2-REC-1", "status": "PAID", "payments": {}}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        # 1st call: should run and update
        res1 = await reconcile_invoices_with_paypal(force=False, client=mock_client, db_path=db_path)
        assert len(res1) == 1

        # 2nd call immediately: throttled by 15-second interval
        res2 = await reconcile_invoices_with_paypal(force=False, client=mock_client, db_path=db_path)
        assert len(res2) == 0

        # 3rd call with force=True (Sync button): bypasses interval
        upsert_invoice("INV2-REC-2", "user2@test.com", "Dev2", 200.0, "SENT", db_path=db_path)
        mock_resp.json.return_value = {"id": "INV2-REC-2", "status": "PAID", "payments": {}}
        res3 = await reconcile_invoices_with_paypal(force=True, client=mock_client, db_path=db_path)
        assert len(res3) == 1


@pytest.mark.asyncio
async def test_reconciliation_concurrency_and_skips_final(mock_client, tmp_path):
    from app.db import init_db, upsert_invoice, get_invoice_by_paypal_id
    from app.paypal.invoices import reconcile_invoices_with_paypal
    import app.paypal.invoices as inv_mod

    db_path = str(tmp_path / "test_concurrency.db")
    init_db(db_path)
    inv_mod._last_reconciliation_time = 0.0

    # Seed 6 invoices (SENT) + 1 already PAID + 1 CANCELLED
    for i in range(1, 7):
        upsert_invoice(f"INV-CONC-{i}", f"u{i}@test.com", f"Task {i}", 100.0 * i, "SENT", db_path=db_path)
    upsert_invoice("INV-FINAL-PAID", "paid@test.com", "Done", 50.0, "PAID", db_path=db_path)
    upsert_invoice("INV-FINAL-CANCELLED", "cancel@test.com", "Cancel", 50.0, "CANCELLED", db_path=db_path)

    async def mock_get_inv(url, headers):
        inv_id = url.split("/")[-1]
        resp = MagicMock()
        resp.is_error = False
        resp.status_code = 200
        resp.json.return_value = {"id": inv_id, "status": "PAID", "payments": {}}
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get_inv) as mock_get:
        updated = await reconcile_invoices_with_paypal(force=True, client=mock_client, db_path=db_path)
        # Should have updated the 6 SENT invoices to PAID
        assert len(updated) == 6
        # Final invoices should never have been queried on PayPal
        called_urls = [call.args[0] for call in mock_get.call_args_list]
        assert not any("INV-FINAL-PAID" in url for url in called_urls)
        assert not any("INV-FINAL-CANCELLED" in url for url in called_urls)


@pytest.mark.asyncio
async def test_reconciliation_503_warning(mock_client, tmp_path):
    from app.db import init_db, upsert_invoice
    from app.paypal.invoices import reconcile_invoices_with_paypal
    import app.paypal.invoices as inv_mod

    db_path = str(tmp_path / "test_503.db")
    init_db(db_path)
    inv_mod._last_reconciliation_time = 0.0

    upsert_invoice("INV-503", "user@test.com", "Task", 100.0, "SENT", db_path=db_path)

    mock_resp = MagicMock()
    mock_resp.is_error = True
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"
    mock_resp.json.side_effect = Exception("Not json")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        # Should not crash on 503, should log warning and return cleanly
        updated = await reconcile_invoices_with_paypal(force=True, client=mock_client, db_path=db_path)
        assert len(updated) == 0

