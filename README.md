# InvoicePilot (PayPal App: PayChase AI)

> **PayPal AI Hackathon Entry** — Autonomous "Agentic Commerce" copilot for freelancers. Invoices clients via PayPal Sandbox through natural conversation, tracks payment statuses in real-time, and autonomously chases overdue payments with tone-escalating reminders.

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![PayPal](https://img.shields.io/badge/PayPal-Sandbox%20Invoicing%20v2-0070ba.svg)](https://developer.paypal.com)

![Dashboard](docs/screenshots/dashboard.png)

---

## ⚡ What Problem It Solves

Freelancers lose countless hours and thousands of dollars chasing late invoices. Manually logging into billing dashboards, calculating overdue days, drafting polite follow-ups, and sending awkward reminders is emotionally draining and takes time away from client work.

**InvoicePilot** turns invoicing into an autonomous, agentic workflow: a freelancer chats with an AI agent in plain English to bill a client. The agent creates and dispatches a real PayPal Sandbox invoice, watches its lifecycle via real-time webhooks, reconciles live status with PayPal, and autonomously chases unpaid invoices with polite, escalating reminders until paid.

---

## ✨ Features

- **Natural-Language Invoicing**: Bill clients conversationally (e.g., *"Invoice sarah@example.com $400 for logo design, due in 15 days"*).
- **Direct PayPal Invoicing API v2 Integration**: Calls official PayPal Sandbox endpoints for invoice creation, sending, reminders, cancellation, and deletion.
- **Autonomous Escalating Chaser**: Background worker (`scheduler.py`) evaluates unpaid invoices past due and dispatches up to 3 escalating reminders through PayPal:
  - **Reminder 1**: Friendly and appreciative check-in
  - **Reminder 2**: Firm, direct follow-up
  - **Reminder 3**: Urgent final notice (capped at 3 maximum)
- **Real-Time Webhook Ingestion & Two-Way Reconciliation**: Listens for PayPal webhooks (`INVOICING.INVOICE.PAID`, `.CANCELLED`, `.REFUNDED`) with signature verification. Periodic and on-demand reconciliation ensures the chaser **never** chases an invoice that PayPal reports as paid.
- **Live Two-Pane Dashboard**: Split-screen interface with a conversational AI agent on the left and a reactive real-time dashboard on the right (polling every 5s, with status badges, reminder counters, reminder history modal, and KPI summaries).
- **Safe Dev Simulation**: Includes a `"Simulate paid (demo)"` action clearly labeled with confirmation dialogs and badge indicators for local testing without spending sandbox funds.

---

## 💳 How It Uses PayPal

PayPal integration is central to the architecture, not decorative:

| Capability | PayPal Endpoint / Mechanism | Description & File |
|---|---|---|
| **OAuth 2.0 Auth** | `POST /v1/oauth2/token` | Client credentials grant; tokens cached with safety buffer in [`app/paypal/client.py`](app/paypal/client.py). |
| **Create Draft Invoice** | `POST /v2/invoicing/invoices` | Generates official PayPal draft invoice with itemized line items and payment terms ([`app/paypal/invoices.py`](app/paypal/invoices.py)). |
| **Send Invoice** | `POST /v2/invoicing/invoices/{id}/send` | Dispatches invoice to recipient email address directly through PayPal. |
| **Send Reminder** | `POST /v2/invoicing/invoices/{id}/remind` | Dispatches escalated reminder emails to the client via PayPal's native reminder engine. |
| **Cancel Invoice** | `POST /v2/invoicing/invoices/{id}/cancel` | Formally cancels unpaid invoices with a cancellation memo. |
| **Delete Draft Invoice** | `DELETE /v2/invoicing/invoices/{id}` | Automatically deletes draft invoices on PayPal if `/send` fails, preventing orphan drafts. |
| **Get Invoice Details** | `GET /v2/invoicing/invoices/{id}` | Fetches live payment status, transaction timestamps, and metadata for status reconciliation. |
| **List Invoices** | `GET /v2/invoicing/invoices` | Retrieves remote invoices list with pagination and date filters. |
| **Webhook Signature Verification** | `POST /v1/notifications/verify-webhook-signature` | Cryptographically validates PayPal transmission signatures before processing webhooks ([`app/paypal/webhooks.py`](app/paypal/webhooks.py)). |

### Webhook Events Handled:
- `INVOICING.INVOICE.PAID`: Records payment timestamp, marks status `PAID`, resets simulation flag, and halts auto-chaser.
- `INVOICING.INVOICE.CANCELLED`: Sets status `CANCELLED` and halts chaser.
- `INVOICING.INVOICE.REFUNDED`: Sets status `REFUNDED` and updates records.
- `INVOICING.INVOICE.CREATED` & `INVOICING.INVOICE.SENT`: Handled cleanly with log levels downgraded to `DEBUG`.

---

## 🤖 How It Uses AI

InvoicePilot utilizes an OpenAI-compatible function-calling loop with strict guardrails:

- **Configurable LLM Provider**: Connects to OpenAI, Groq, OpenRouter, Together, or local Ollama using standard `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` environment variables.
- **Available Agent Tools**:
  1. `create_and_send_invoice`: Creates PayPal draft, sends it, cleans up on failure, and stores in SQLite.
  2. `list_invoices`: Inspects local tracked invoices filtered by status (`SENT`, `PAID`, `DRAFT`, `CANCELLED`).
  3. `get_invoice_status`: Looks up individual invoice status and syncs latest PayPal state.
  4. `send_reminder`: Manually triggers a reminder via PayPal with custom notes.
  5. `cancel_invoice`: Cancels an existing invoice with a reason.
- **Strict Safety Rules**:
  - **$1,000 Confirmation Rule**: Invoices over $1,000 USD trigger an explicit human-in-the-loop confirmation step before sending.
  - **Required Details**: Must have `client_email`, `amount`, and `description`; never hallucinates or invents emails or amounts.
  - **Currency Lock**: Always uses `USD ($)`.
- **Deterministic Confirmation Safety-Net**: When an invoice is created, the confirmation reply shown to the user is formatted deterministically from the real PayPal API response (`invoice_id`, `client_email`, `amount`, `due_date`), preventing model hallucination or reasoning leakage.

---

## 🏛️ Architecture & Project Structure

```
                      +---------------------------------------+
                      |       Freelancer / Browser UI         |
                      |  (Split Chat + Live Invoicing Board)  |
                      +-------------------+-------------------+
                                          |
                         HTTP / Chat / REST API (FastAPI)
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| PayChase AI Backend                                                               |
|                                                                                   |
|  +---------------------------+                +--------------------------------+  |
|  |   OpenAI-Compatible Agent | <--- Tools --->|      PayPal Invoicing v2       |  |
|  |   - create_and_send       |                |  - POST /v2/invoicing/invoices |  |
|  |   - list_invoices         |                |  - POST /invoices/{id}/send    |  |
|  |   - get_invoice_status    |                |  - POST /invoices/{id}/remind  |  |
|  |   - send_reminder         |                |  - POST /invoices/{id}/cancel  |  |
|  |   - cancel_invoice        |                |  - DELETE /invoices/{id}       |  |
|  +-------------+-------------+                +--------------------------------+  |
|                |                                               |                  |
|                v                                               v                  |
|  +---------------------------+                +--------------------------------+  |
|  |      SQLite Database      | <------------- |   Autonomous Chaser Service    |  |
|  |   - invoices (status sync)|                |  - scheduler.py (asyncio loop) |  |
|  |   - reminders (audit log) |                |  - Tone escalation (1 -> 3)    |  |
|  +---------------------------+                |  - DEMO_MODE 1-minute overdue  |  |
|                ^                              +--------------------------------+  |
|                |                                                                  |
|                +----------- PayPal Webhooks (/webhooks/paypal) -------------------+  |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
                         +---------------------------------+
                         |     PayPal Sandbox Platform     |
                         |  (api-m.sandbox.paypal.com)     |
                         +---------------------------------+
```

### Project Directory Tree:

```
PayChase AI/
├── app/
│   ├── main.py              # FastAPI application, route handlers & dev security
│   ├── config.py            # Pydantic/dataclass environment settings
│   ├── db.py                # SQLite persistence, schema, migrations & queries
│   ├── schemas.py           # Pydantic request/response models
│   ├── scheduler.py         # Autonomous payment chaser & tone escalation
│   ├── agent/
│   │   ├── agent.py         # OpenAI tool-calling loop & deterministic safety reply
│   │   ├── tools.py         # Tool schemas & dispatch executors
│   │   └── prompts.py       # Agent persona, safety guardrails & constraints
│   └── paypal/
│       ├── client.py        # OAuth 2.0 token caching & API error handling
│       ├── invoices.py      # Invoicing v2 CRUD, remind, cancel, delete & sync
│       └── webhooks.py      # Signature verification & event handlers
├── static/
│   └── index.html           # Single-page UI: split chat & real-time dashboard
├── tests/
│   ├── test_agent.py        # LLM tool loop, safety net, reasoning filter tests
│   ├── test_api.py          # API endpoints, webhooks, rate limits, dev auth
│   ├── test_db.py           # Database CRUD, status updates & reminder logs
│   ├── test_paypal.py       # PayPal API client, reconciliation, draft cleanup
│   ├── test_scheduler.py    # Chaser tone escalation & demo mode overdue logic
│   └── test_integration.py  # End-to-end full workflow test
├── docs/
│   ├── screenshots/         # UI screenshots (.gitkeep)
│   ├── DEVPOST_DESCRIPTION.md
│   ├── DEVPOST_FIELDS.md
│   └── VIDEO_SCRIPT.md
├── render.yaml              # 1-click cloud deployment blueprint
├── requirements.txt         # Core dependencies
├── .env.example             # Documented template for environment variables
├── .gitignore               # Strict exclusion of secrets, DBs, and caches
├── LICENSE                  # MIT License
└── README.md                # Project documentation & judge walkthrough
```

---

## 🚀 Quick Start (Under 5 Minutes)

### 1. Prerequisites
- **Python 3.11+** installed
- A **PayPal Developer account**: [developer.paypal.com](https://developer.paypal.com/)
- An **OpenAI-compatible LLM key** (free key from [Groq](https://console.groq.com/) recommended)

### 2. Clone & Install
```bash
git clone https://github.com/your-username/PayChase-AI.git
cd PayChase-AI

# Create and activate virtual environment
python -m venv venv
# Linux / macOS: source venv/bin/activate
# Windows PowerShell: .\venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Open `.env` and fill in your keys:
```env
# PayPal Sandbox Credentials (from developer.paypal.com -> Dashboard -> Apps & Credentials)
PAYPAL_CLIENT_ID=your_paypal_client_id
PAYPAL_SECRET=your_paypal_secret
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=

# Free Groq LLM Example (or OpenAI / OpenRouter)
LLM_API_KEY=gsk_your_groq_api_key_here
LLM_MODEL=llama-3.3-70b-versatile
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_INCLUDE_REASONING=false
LLM_REASONING_EFFORT=low

# App Settings
DEMO_MODE=true
CHASER_INTERVAL_SECONDS=60
PORT=8000

# Security (Optional)
DEV_ADMIN_TOKEN=my_secret_admin_token
CHAT_RATE_LIMIT_PER_MINUTE=20
```

> **How to get PayPal Sandbox Credentials:**
> 1. Log into [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/).
> 2. Navigate to **Apps & Credentials** and ensure **Sandbox** mode is toggled.
> 3. Click **Create App**, select **Merchant** as the app type, and ensure **Invoicing** is enabled.
> 4. Copy the **Client ID** and **Secret** into your `.env`.

### 4. Run the Server
```bash
uvicorn app.main:app --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## 🧪 Testing the Full Flow (Judge Walkthrough)

### Step 1: Prepare Sandbox Accounts
1. In the PayPal Developer Dashboard under **Testing Tools -> Sandbox Accounts**, check your accounts.
2. Ensure you have:
   - A **Business (Merchant)** account (used for your app credentials).
   - A **Personal (Buyer)** account with a country set to **United States (US)**.
   > **Important PayPal Restriction Note:** PayPal blocks cross-border USD invoice payments to recipients in India. Ensure your sandbox buyer account is located in the **United States (US)** or another supported country.

### Step 2: Issue an Invoice via Chat
In the chat interface on the left, type:
> *"Invoice sb-buyer123@personal.example.com $400 for logo design, due in 15 days"*

1. The AI calls `create_and_send_invoice`.
2. A real PayPal invoice is created and sent in the Sandbox (`INV2-XXXX-XXXX-XXXX-XXXX`).
3. The dashboard on the right automatically updates with status `SENT`.

### Step 3: Observe Autonomous Escalating Chaser (`DEMO_MODE=true`)
1. In `DEMO_MODE=true`, invoices older than 60 seconds are considered overdue.
2. Wait 60 seconds (or click **"Run Chaser Now"** on the dashboard).
3. The chaser calls PayPal's `/remind` API with an escalated polite note.
4. The dashboard updates to show **⚡ 1 sent**. Click the reminder badge to inspect the timestamped audit log.
5. Further runs will send Reminder #2 (Firm) and Reminder #3 (Urgent), capped at 3 reminders.

### Step 4: Pay the Invoice & Watch the Dashboard Settle
1. Log into [sandbox.paypal.com](https://www.sandbox.paypal.com) using your US Personal Sandbox account.
2. View the invoice under **Activity** or via the email notification and click **Pay**.
3. Complete the payment with Sandbox balance or test card.
4. Return to your PayChase AI dashboard and click **"Sync with PayPal"** (or let the 15-second background reconciliation cycle run).
5. The invoice flips to `PAID` with a green `[PayPal Settled]` badge, and the chaser permanently stops sending reminders.

---

## 🪝 Webhooks Setup (Optional)

Webhooks deliver instant push notifications when an invoice is paid, cancelled, or refunded.

If running locally behind a router or firewall, use Cloudflare Tunnels (or ngrok):
```bash
cloudflared tunnel --url http://localhost:8000
```
1. Copy the public URL (e.g., `https://random-subdomain.trycloudflare.com`).
2. In PayPal Developer Dashboard -> **Apps & Credentials** -> select your App -> **Add Webhook**.
3. Set Webhook URL to: `https://<public-url>/webhooks/paypal`.
4. Check events:
   - `Invoicing invoice paid`
   - `Invoicing invoice cancelled`
   - `Invoicing invoice refunded`
5. Copy the generated **Webhook ID** into `.env` as `PAYPAL_WEBHOOK_ID`.

> **Note:** Webhooks are optional for testing. If you don't configure a public tunnel, the built-in **PayPal Reconciliation** engine (`GET /v2/invoicing/invoices/{id}`) and the **"Sync with PayPal"** dashboard button automatically poll and reconcile real payment status without needing an external tunnel.

---

## 📋 Environment Variables Reference

| Variable | Required | Default | Description |
|---|:---:|---|---|
| `PAYPAL_CLIENT_ID` | **Yes** | — | PayPal Sandbox REST App Client ID. |
| `PAYPAL_SECRET` | **Yes** | — | PayPal Sandbox REST App Secret. |
| `PAYPAL_BASE_URL` | No | `https://api-m.sandbox.paypal.com` | PayPal API base endpoint. |
| `PAYPAL_WEBHOOK_ID` | No | `""` | PayPal Webhook ID for cryptographic signature verification. |
| `LLM_API_KEY` | **Yes** | — | OpenAI or compatible API key (e.g. Groq, OpenRouter). |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model identifier (e.g. `llama-3.3-70b-versatile`). |
| `LLM_BASE_URL` | No | `None` (OpenAI) | Base URL for alternative providers (e.g. `https://api.groq.com/openai/v1`). |
| `LLM_INCLUDE_REASONING` | No | `false` | Instructs reasoning models to hide internal chain-of-thought tokens. |
| `LLM_REASONING_EFFORT` | No | `low` | Reasoning effort parameter for compatible reasoning models. |
| `DEMO_MODE` | No | `true` | When true, marks invoices overdue after 1 minute for demo testing. |
| `CHASER_INTERVAL_SECONDS` | No | `60` | Background scheduler interval in seconds. |
| `PORT` | No | `8000` | Port for the FastAPI HTTP server. |
| `DEV_ADMIN_TOKEN` | No | `None` | Secret token to authenticate dev endpoints when accessing remotely. |
| `CHAT_RATE_LIMIT_PER_MINUTE` | No | `20` | Maximum `/chat` requests allowed per client IP per minute. |

---

## ⚙️ Demo Mode & Local Simulation

- **`DEMO_MODE=true`**: Treats invoices as overdue after 1 minute (instead of the standard calendar due date) so judges can observe multi-step reminder chasing during a short 3-minute video without waiting days.
- **"Simulate paid (demo)" Button**: Marked with an amber `[Simulated (demo)]` badge. Requires explicit user confirmation (*"This only changes your local dashboard, not PayPal"*). If PayPal is later reconciled and reports the invoice as still unpaid, reconciliation immediately overwrites the simulated status with PayPal's real status.
- **"Reset DB" Button**: Clears all local database records and in-memory chat session history for a clean demo run.

---

## 🔒 Security & Guardrails

- **Dev Endpoints Protection**: `/dev/reset`, `/dev/simulate-paid`, and `/dev/trigger-chaser` are restricted to `localhost` (`127.0.0.1`) only. Remote calls require the `DEV_ADMIN_TOKEN` header, returning `403 Forbidden` otherwise.
- **Per-IP Rate Limiting**: `/chat` is guarded by an in-memory sliding window rate limiter (default: 20 rpm per IP) to prevent spam and denial of service.
- **Zero Secrets in Repository**: Secrets are strictly stored in `.env` (ignored by `.gitignore`).
- **Signature Verification**: PayPal webhooks are cryptographically validated against PayPal's public certificates.

---

## 🧪 Running the Automated Tests

The test suite contains **51 automated tests** covering unit, mocked PayPal API, and integration paths:

```bash
pytest -v
```

### Test Coverage Highlights:
- `tests/test_agent.py`: OpenAI function-calling dispatch, safety confirmation, draft cleanup on send failure, and reasoning text stripping.
- `tests/test_paypal.py`: OAuth token caching, draft creation, draft deletion, reminder dispatch, error body propagation, and reconciliation lock/throttling.
- `tests/test_db.py`: SQLite persistence, status transitions, reminder history logging, and simulated-payment handling.
- `tests/test_api.py`: FastAPI endpoints, rate limiting (20 rpm), dev endpoint security (403 on non-localhost), webhook payload variants, and log level filtering.
- `tests/test_scheduler.py`: Escalating reminder copy (Friendly -> Firm -> Urgent), overdue evaluation in demo vs standard mode, and chaser skipping paid invoices.
- `tests/test_integration.py`: Complete end-to-end lifecycle from conversational chat request to PayPal Sandbox invoice creation, chasing, and payment.

---

## 🔭 Limitations & Roadmap

- **Multi-Currency Support**: Currently USD only; roadmap includes EUR, GBP, CAD, and automatic currency conversion.
- **Multi-Tenant Freelancer Authentication**: Designed for a single freelancer; roadmap includes multi-user OAuth login with individual PayPal merchant credentials.
- **Multi-Channel Reminders**: Add SMS (Twilio) and WhatsApp Business notifications alongside PayPal native email reminders.
- **Dynamic Dispute Assistance**: AI analysis of buyer chargeback/dispute webhooks with automated evidence assembly.

---

## 📄 License

This project is licensed under the terms of the [MIT License](LICENSE).
