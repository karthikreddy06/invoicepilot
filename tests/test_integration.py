import os
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, get_invoice_by_paypal_id, get_reminders_for_invoice
from app.scheduler import run_chaser_job


@pytest.fixture
def test_env(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    monkeypatch.setattr("app.config.settings.DB_PATH", path)
    monkeypatch.setattr("app.config.settings.DEMO_MODE", True)
    with TestClient(app) as client:
        yield client, path
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_end_to_end_flow(test_env):
    client, db_path = test_env

    # Step 1: Freelancer asks AI agent to invoice Sarah
    mock_tool_call = MagicMock()
    mock_tool_call.type = "tool_use"
    mock_tool_call.name = "create_and_send_invoice"
    mock_tool_call.id = "call_inv_1"
    mock_tool_call.input = {
        "client_email": "sarah@example.com",
        "description": "Logo design",
        "amount": 400.0,
        "due_date": "2026-11-20",
    }

    resp1 = MagicMock()
    resp1.content = [mock_tool_call]

    resp2 = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "I've created and sent invoice INV2-DEMO-999 to sarah@example.com for $400."
    resp2.content = [text_block]

    mock_llm = MagicMock()
    mock_llm.messages.create = AsyncMock(side_effect=[resp1, resp2])

    with patch("app.agent.agent.get_llm_client", return_value=mock_llm), \
         patch("app.agent.tools.create_draft_invoice", new_callable=AsyncMock) as mock_draft, \
         patch("app.agent.tools.send_invoice", new_callable=AsyncMock) as mock_send, \
         patch("app.scheduler.send_reminder", new_callable=AsyncMock) as mock_chase_send:

        mock_draft.return_value = {"id": "INV2-DEMO-999", "status": "DRAFT"}
        mock_send.return_value = {"status": "SENT", "id": "INV2-DEMO-999"}
        mock_chase_send.return_value = {"success": True}

        # 1. Chat request
        chat_resp = client.post("/chat", json={
            "session_id": "freelancer_session_1",
            "message": "Invoice sarah@example.com $400 for logo design, due in 15 days",
        })
        assert chat_resp.status_code == 200
        data = chat_resp.json()
        assert len(data["actions_taken"]) == 1
        assert data["actions_taken"][0]["tool"] == "create_and_send_invoice"

        # 2. Check DB
        inv = get_invoice_by_paypal_id("INV2-DEMO-999", db_path=db_path)
        assert inv is not None
        assert inv["status"] == "SENT"
        assert inv["amount"] == 400.0
        assert inv["reminder_count"] == 0

        # 3. Simulate overdue chasing
        from app.db import get_db_connection
        from datetime import datetime, timezone, timedelta
        with get_db_connection(db_path) as conn:
            old_time = (datetime.now(timezone.utc) - timedelta(seconds=75)).isoformat()
            conn.execute("UPDATE invoices SET created_at = ? WHERE paypal_invoice_id = ?", (old_time, "INV2-DEMO-999"))
            conn.commit()

        chase_actions = await run_chaser_job(demo_mode=True)
        assert len(chase_actions) == 1
        assert chase_actions[0]["invoice_id"] == "INV2-DEMO-999"
        assert chase_actions[0]["reminder_number"] == 1

        reminders = get_reminders_for_invoice("INV2-DEMO-999", db_path=db_path)
        assert len(reminders) == 1
        assert "Friendly" in reminders[0]["message"]

        # 4. Client pays invoice (simulate-paid endpoint)
        pay_resp = client.post("/dev/simulate-paid/INV2-DEMO-999")
        assert pay_resp.status_code == 200
        assert pay_resp.json()["status"] == "PAID"

        # 5. Subsequent chaser run should NOT chase the paid invoice
        chase_actions_after = await run_chaser_job(demo_mode=True)
        assert len(chase_actions_after) == 0
