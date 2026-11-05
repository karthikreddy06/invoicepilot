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

