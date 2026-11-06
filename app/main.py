from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
import secrets
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Request, HTTPException, status, Depends
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
from app.agent.agent import run_agent, clear_all_sessions
from app.paypal.client import paypal_client
from app.paypal.invoices import reconcile_invoices_with_paypal
from app.paypal.webhooks import verify_webhook_signature, handle_webhook_event
from app.scheduler import start_scheduler, stop_scheduler, run_chaser_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# FastAPI Application setup
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

docs_screenshots_path = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
if docs_screenshots_path.exists():
    app.mount("/docs/screenshots", StaticFiles(directory=str(docs_screenshots_path)), name="screenshots")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = static_path / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "PayChase AI API is running. UI not found in /static."}


@app.get("/welcome", include_in_schema=False)
async def serve_landing():
    landing_file = static_path / "landing.html"
    if landing_file.exists():
        return FileResponse(landing_file)
    return {"message": "InvoicePilot landing page not found in /static."}


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


# ------------------------------------------------------------------------------
# Rate Limiting for /chat
# ------------------------------------------------------------------------------
_chat_rate_limit_records: Dict[str, List[float]] = defaultdict(list)


def get_client_ip(request: Request) -> str:
    """Extract client IP, taking X-Forwarded-For into account when present."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def reset_chat_rate_limiter():
    """Reset rate limiter state (used in testing)."""
    _chat_rate_limit_records.clear()


async def check_chat_rate_limit(request: Request):
    """
    Enforce simple per-IP rate limiting on /chat (default: 20 requests per minute).
    Returns 429 Too Many Requests if rate is exceeded.
    """
    limit = getattr(settings, "CHAT_RATE_LIMIT_PER_MINUTE", 20)
    if limit <= 0:
        return

    client_ip = get_client_ip(request)
    now = time.time()
    window = 60.0

    # Prune timestamps older than 60 seconds
    timestamps = [t for t in _chat_rate_limit_records[client_ip] if now - t < window]
    if len(timestamps) >= limit:
        _chat_rate_limit_records[client_ip] = timestamps
        logger.warning(f"Rate limit exceeded on /chat for IP {client_ip} ({len(timestamps)}/{limit} rpm)")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: maximum {limit} requests per minute for /chat. Please try again later.",
            headers={"Retry-After": "60"},
        )

    timestamps.append(now)
    _chat_rate_limit_records[client_ip] = timestamps


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(check_chat_rate_limit)])
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
    Automatically reconciles active invoices with PayPal live status (shared lock, 15s interval).
    """
    try:
        await reconcile_invoices_with_paypal(force=False)
    except Exception as exc:
        logger.warning(f"Automatic reconciliation on GET /invoices failed: {exc}")

    invoices = get_all_invoices(status=status)
    return invoices


@app.post("/invoices/sync")
async def sync_invoices_endpoint():
    """
    Force immediate reconciliation of all active invoices with PayPal Sandbox status (bypasses 15s interval).
    """
    updated = await reconcile_invoices_with_paypal(force=True)
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

LOCALHOST_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_localhost_request(request: Request) -> bool:
    """Check if request originates from localhost, accounting for proxies."""
    client_host = request.client.host if request.client else None
    if client_host not in LOCALHOST_HOSTS:
        return False

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        forwarded_ip = forwarded.split(",")[0].strip()
        if forwarded_ip not in ("127.0.0.1", "::1", "localhost"):
            return False

    return True


async def verify_dev_access(request: Request):
    """
    Protect dev endpoints: /dev/reset and /dev/simulate-paid must only work for
    requests from localhost (127.0.0.1) or when a DEV_ADMIN_TOKEN env var is sent in a
    header, and return 403 otherwise.
    """
    if is_localhost_request(request):
        return True

    # Check for DEV_ADMIN_TOKEN in request headers
    dev_token = getattr(settings, "DEV_ADMIN_TOKEN", None)
    provided_token = (
        request.headers.get("x-dev-admin-token")
        or request.headers.get("dev-admin-token")
        or request.headers.get("dev_admin_token")
        or request.headers.get("x-admin-token")
    )
    if not provided_token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            provided_token = auth[7:].strip()
        elif auth and not auth.lower().startswith("basic "):
            provided_token = auth.strip()

    if dev_token and provided_token and secrets.compare_digest(provided_token.strip(), dev_token.strip()):
        return True

    client_str = request.client.host if request.client else "unknown"
    logger.warning(f"Forbidden access attempt to dev endpoint {request.url.path} from {client_str}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: dev endpoints only accessible from localhost (127.0.0.1) or with DEV_ADMIN_TOKEN header.",
    )


@app.post("/dev/simulate-paid/{invoice_id}", dependencies=[Depends(verify_dev_access)])
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


@app.post("/dev/reset", dependencies=[Depends(verify_dev_access)])
async def dev_reset_endpoint():
    """
    [DEV ONLY] Clears all tracked invoices and reminders from the database,
    and clears all in-memory chat sessions in the agent for a clean demo run.
    """
    res = clear_all_data()
    clear_all_sessions()
    reset_chat_rate_limiter()
    return {
        "dev_mode": True,
        "warning": "DEV ONLY ENDPOINT - NOT FOR PRODUCTION",
        "result": res,
        "chat_sessions_cleared": True,
    }


@app.post("/dev/trigger-chaser", dependencies=[Depends(verify_dev_access)])
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

