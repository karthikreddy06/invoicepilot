import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import (
    init_db,
    get_all_invoices,
    get_invoice_by_paypal_id,
    update_invoice_status,
    get_reminders_for_invoice,
    clear_all_data,
)
from app.schemas import ChatRequest, ChatResponse, HealthResponse
from app.agent.agent import run_agent
from app.paypal.client import paypal_client
from app.paypal.invoices import reconcile_invoices_with_paypal
from app.paypal.webhooks import verify_webhook_signature, handle_webhook_event
from app.scheduler import start_scheduler, stop_scheduler, run_chaser_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# State for rate-limiting automatic reconciliation on GET /invoices
_last_reconciliation_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database and start background reminder chaser
    logger.info("Initializing SQLite database...")
    init_db()
    logger.info("Starting background chaser scheduler...")
    start_scheduler()
    yield
    # Shutdown: gracefully stop scheduler
    logger.info("Stopping background scheduler...")
    stop_scheduler()


app = FastAPI(
    title="InvoicePilot / PayChase AI",
    description="Agentic Commerce assistant for freelancers: PayPal invoice creation, webhook tracking, and autonomous chasing.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_path = Path(__file__).resolve().parent.parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = static_path / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "PayChase AI API is running. UI not found in /static."}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health status and configuration readiness check."""
    paypal_ready = bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_SECRET)
    return HealthResponse(
        status="healthy",
        paypal_connected=paypal_ready,
        database="connected",
        demo_mode=settings.DEMO_MODE,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest):
    """
    Process freelancer's natural language request through the AI agent with PayPal tool calling.
    """
    reply, actions = await run_agent(
        session_id=payload.session_id,
        user_message=payload.message,
    )
    return ChatResponse(reply=reply, actions_taken=actions)


@app.get("/invoices")
async def list_invoices_endpoint(status: Optional[str] = None):
    """
    Retrieve all tracked invoices from SQLite, optionally filtered by status.
    Automatically reconciles active invoices with PayPal live status at most once every 10 seconds.
    """
    global _last_reconciliation_time
    now = time.time()
    if now - _last_reconciliation_time >= 10.0:
        _last_reconciliation_time = now
        try:
            await reconcile_invoices_with_paypal()
        except Exception as exc:
            logger.warning(f"Automatic reconciliation on GET /invoices failed: {exc}")

    invoices = get_all_invoices(status=status)
    return invoices


@app.post("/invoices/sync")
async def sync_invoices_endpoint():
    """
    Force immediate reconciliation of all active invoices with PayPal Sandbox status.
    """
    global _last_reconciliation_time
    _last_reconciliation_time = time.time()
    updated = await reconcile_invoices_with_paypal()
    return {
        "success": True,
        "reconciled_count": len(updated),
        "updated": updated,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/invoices/{invoice_id}")
async def get_single_invoice_endpoint(invoice_id: str):
    """
    Retrieve single invoice details and reminder history.
    """
    inv = get_invoice_by_paypal_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    reminders = get_reminders_for_invoice(invoice_id)
    return {"invoice": inv, "reminders": reminders}


@app.post("/webhooks/paypal")
async def paypal_webhook_endpoint(request: Request):
    """
    Receive and process PayPal webhook notifications.
    Verifies cryptographic signature using PayPal's verification API.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    headers = dict(request.headers)

    # Verify signature if webhook ID configured
    is_valid = await verify_webhook_signature(headers=headers, raw_body=body)
    if not is_valid:
        logger.warning("Rejected unverified PayPal webhook signature")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid PayPal webhook signature")

    result = handle_webhook_event(body)
    return {"status": "success", "result": result}


# ==============================================================================
# DEV / DEMO ENDPOINTS
# ==============================================================================

@app.post("/dev/simulate-paid/{invoice_id}")
async def simulate_paid_endpoint(invoice_id: str):
    """
    [DEV ONLY] Simulates client paying an invoice for local testing.
    Explicitly flags is_simulated=1 so it is marked clearly as local-only demo payment.
    """
    inv = get_invoice_by_paypal_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found in database.")

    now_iso = datetime.now(timezone.utc).isoformat()
    updated = update_invoice_status(invoice_id, status="PAID", paid_at=now_iso, is_simulated=1)

    return {
        "dev_mode": True,
        "warning": "DEV ONLY ENDPOINT - NOT FOR PRODUCTION",
        "invoice_id": invoice_id,
        "status": "PAID",
        "is_simulated": True,
        "paid_at": now_iso,
        "invoice": updated,
    }


@app.post("/dev/reset")
async def dev_reset_endpoint():
    """
    [DEV ONLY] Clears all tracked invoices and reminders from the database for a clean demo run.
    """
    res = clear_all_data()
    return {
        "dev_mode": True,
        "warning": "DEV ONLY ENDPOINT - NOT FOR PRODUCTION",
        "result": res,
    }


@app.post("/dev/trigger-chaser")
async def dev_trigger_chaser_endpoint():
    """
    [DEV ONLY] Immediately triggers the background chaser job without waiting for the 60s timer.
    """
    actions = await run_chaser_job()
    return {
        "dev_mode": True,
        "warning": "DEV ONLY ENDPOINT - NOT FOR PRODUCTION",
        "actions_taken": actions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

