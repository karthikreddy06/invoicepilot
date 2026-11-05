import json
import pytest
import os
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock
from openai import RateLimitError
import httpx
from app.db import init_db, upsert_invoice
from app.agent.tools import dispatch_tool
from app.agent.agent import run_agent, clear_session_history


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    monkeypatch.setattr("app.config.settings.DB_PATH", path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_tool_create_and_send_invoice(temp_db):
    with patch("app.agent.tools.create_draft_invoice", new_callable=AsyncMock) as mock_draft, \
         patch("app.agent.tools.send_invoice", new_callable=AsyncMock) as mock_send:
        mock_draft.return_value = {"id": "INV2-1111-2222", "status": "DRAFT"}
        mock_send.return_value = {"status": "SENT", "id": "INV2-1111-2222"}

        res = await dispatch_tool("create_and_send_invoice", {
            "client_email": "client@test.com",
            "description": "Web app development",
            "amount": 500.0,
            "due_date": "2026-11-20",
        })

        assert res["success"] is True
        assert res["invoice_id"] == "INV2-1111-2222"
        assert res["status"] == "SENT"
        assert res["amount"] == 500.0
        mock_draft.assert_called_once()
        mock_send.assert_called_once_with("INV2-1111-2222")


@pytest.mark.asyncio
async def test_tool_list_invoices(temp_db):
    upsert_invoice("INV-A", "a@test.com", "Design", 200.0, "SENT", db_path=temp_db)
    upsert_invoice("INV-B", "b@test.com", "Copywriting", 300.0, "PAID", db_path=temp_db)

    res = await dispatch_tool("list_invoices", {"status": "SENT"})
    assert res["total"] == 1
    assert res["invoices"][0]["paypal_invoice_id"] == "INV-A"


@pytest.mark.asyncio
async def test_tool_get_invoice_status(temp_db):
    upsert_invoice("INV-STATUS", "client@test.com", "SEO", 150.0, "SENT", db_path=temp_db)
    with patch("app.agent.tools.get_invoice", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"id": "INV-STATUS", "status": "PAID"}

        res = await dispatch_tool("get_invoice_status", {"invoice_id": "INV-STATUS"})
        assert res["found"] is True
        assert res["invoice"]["status"] == "PAID"


@pytest.mark.asyncio
async def test_tool_send_reminder(temp_db):
    upsert_invoice("INV-REMIND-1", "client@test.com", "Hosting", 80.0, "SENT", db_path=temp_db)
    with patch("app.agent.tools.pp_send_reminder", new_callable=AsyncMock) as mock_rem:
        mock_rem.return_value = {"success": True}

        res = await dispatch_tool("send_reminder", {
            "invoice_id": "INV-REMIND-1",
            "note": "Payment is overdue",
        })
        assert res["success"] is True
        assert res["invoice_id"] == "INV-REMIND-1"


@pytest.mark.asyncio
async def test_tool_cancel_invoice(temp_db):
    upsert_invoice("INV-CANCEL-1", "client@test.com", "Service", 99.0, "SENT", db_path=temp_db)
    with patch("app.agent.tools.pp_cancel_invoice", new_callable=AsyncMock) as mock_cancel:
        mock_cancel.return_value = {"success": True}

        res = await dispatch_tool("cancel_invoice", {
            "invoice_id": "INV-CANCEL-1",
            "reason": "Client cancelled agreement",
        })
        assert res["success"] is True
        assert res["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_agent_tool_loop(temp_db):
    clear_session_history("test_session")

    # Step 1: Mock OpenAI model response containing tool_calls
    tc = MagicMock()
    tc.id = "call_abc123"
    tc.function.name = "list_invoices"
    tc.function.arguments = json.dumps({"status": "SENT"})

    msg1 = MagicMock()
    msg1.content = None
    msg1.tool_calls = [tc]

    resp1 = MagicMock()
    choice1 = MagicMock()
    choice1.message = msg1
    resp1.choices = [choice1]

    # Step 2: Final response text
    msg2 = MagicMock()
    msg2.content = "You have 0 pending sent invoices."
    msg2.tool_calls = None

    resp2 = MagicMock()
    choice2 = MagicMock()
    choice2.message = msg2
    resp2.choices = [choice2]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

    reply, actions = await run_agent("test_session", "List all my sent invoices", client=mock_client)
    assert reply == "You have 0 pending sent invoices."
    assert len(actions) == 1
    assert actions[0]["tool"] == "list_invoices"


@pytest.mark.asyncio
async def test_agent_rate_limit_handling(temp_db):
    clear_session_history("test_rate_limit")

    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    rate_err = RateLimitError("Rate limit reached", response=resp, body=None)

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=rate_err)

    reply, actions = await run_agent("test_rate_limit", "Invoice test", client=mock_client)
    assert "rate limit reached" in reply.lower()
    assert actions == []
