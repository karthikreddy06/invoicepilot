# InvoicePilot (PayPal App: PayChase AI)

> **PayPal AI Hackathon Entry** — Autonomous "Agentic Commerce" copilot for freelancers. Invoices clients via PayPal Sandbox through natural conversation, tracks payment statuses in real-time, and autonomously chases overdue payments with tone-escalating reminders.

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![PayPal](https://img.shields.io/badge/PayPal-Sandbox%20Invoicing%20v2-0070ba.svg)](https://developer.paypal.com)

---

## ⚡ What It Does

Freelancers lose countless hours manually drafting invoices, checking bank balances, and sending awkward payment reminders. 

**InvoicePilot** transforms invoice management into an autonomous conversational flow:
1. **Natural Language Invoicing**: Tell the agent *"Invoice sarah@example.com $400 for logo design, due in 15 days"*.
2. **Real PayPal Invoicing v2 Execution**: The AI agent drafts and sends a real PayPal invoice through PayPal Sandbox (`https://api-m.sandbox.paypal.com`).
3. **Live Two-Pane Dashboard**: Real-time split-screen UI displaying conversational AI on the left and a reactive invoice tracker on the right (auto-refreshed every 5s).
4. **Autonomous Overdue Payment Chaser**: A background engine (`scheduler.py`) identifies unpaid overdue invoices and sends automated PayPal reminders with escalating tones:
   - **Reminder 1**: Friendly & appreciative
   - **Reminder 2**: Direct & firm follow-up
   - **Reminder 3**: Urgent & final notice (capped at 3 max)
5. **Real-time Webhook Sync & Dev Mode**: Ingests PayPal webhooks (`INVOICING.INVOICE.PAID`, `CANCELLED`, `REFUNDED`) with signature verification. Includes a `DEMO_MODE` flag (overdue after 60s) for rapid 3-minute video demonstrations and judge evaluation.

---

## 🏛️ Architecture Overview

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
|  |   - get_status            |                |  - POST /invoices/{id}/remind  |  |
|  |   - send_reminder         |                |  - POST /invoices/{id}/cancel  |  |
|  |   - cancel_invoice        |                +--------------------------------+  |
|  +-------------+-------------+                                 |                  |
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

---

## 🚀 Quickstart (Run from scratch in under 5 minutes)

### 1. Prerequisites
- **Python 3.11+** installed
- A **PayPal Developer Sandbox** account ([developer.paypal.com](https://developer.paypal.com/))
- An **Anthropic API key** (or compatible LLM provider)

### 2. Clone and Install Dependencies
```bash
git clone https://github.com/your-username/PayChase-AI.git
cd PayChase-AI

# Create virtual environment (optional but recommended)
python -m venv venv
# Linux/macOS: source venv/bin/activate
# Windows: .\venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Configure Secrets (.env)
Copy the example environment file:
```bash
cp .env.example .env
```

Open `.env` and configure your credentials:
```env
# PayPal Sandbox Credentials (from developer.paypal.com -> Dashboard -> Apps & Credentials)
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_SECRET=your_sandbox_secret
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=your_optional_webhook_id

# LLM Credentials (OpenAI-compatible: OpenAI, Groq, OpenRouter, Together, Ollama)
LLM_API_KEY=your_llm_api_key
LLM_MODEL=gpt-4o-mini
# LLM_BASE_URL=https://api.openai.com/v1
# Free / Alternative Providers:
# LLM_BASE_URL=https://api.groq.com/openai/v1
# LLM_BASE_URL=https://openrouter.ai/api/v1
# LLM_BASE_URL=http://localhost:11434/v1

# App Configuration
DEMO_MODE=true
CHASER_INTERVAL_SECONDS=60
PORT=8000
```

> **Security Note:** `.env` is ignored by `.gitignore` and never committed to source control.

### 4. Start the Application
```bash
uvicorn app.main:app --reload --port 8000
```
Open your browser to: **[http://localhost:8000](http://localhost:8000)**

---

## 🧪 How to Test the Flow (Judge Walkthrough)

### Step 1: Issue an Invoice via Natural Language
In the chat panel on the left, type:
> *"Invoice sarah@example.com $400 for logo design, due in 15 days"*

1. The AI agent extracts the details and calls the `create_and_send_invoice` tool.
2. A real PayPal invoice is created and sent in the PayPal Sandbox (`INV2-XXXX-XXXX-XXXX-XXXX`).
3. The dashboard on the right automatically updates within 5 seconds displaying the new invoice with a `SENT` badge.

### Step 2: Test Confirmation Safeguards
Type:
> *"Invoice alex@techcorp.io $1,500 for enterprise security review"*

Notice that because the amount exceeds **$1,000 USD**, the agent's built-in safety prompt will pause, summarize the invoice details, and explicitly ask for your confirmation before issuing the invoice.

### Step 3: Test Autonomous Chaser with `DEMO_MODE=true`
With `DEMO_MODE=true`:
- Any unpaid invoice older than **60 seconds** is automatically flagged as overdue.
- The background chaser (`scheduler.py`) evaluates invoices every 60 seconds (or click **"Run Chaser Now"** on the dashboard to test instantly).
- The chaser automatically dispatches **Reminder #1** (Friendly) via PayPal's `/remind` API and logs the event in the reminders table.
- Click on the **⚡ 1 sent** badge on the dashboard row to open the modal view of all dispatched reminder messages and timestamps.
- Successive runs escalate the tone: **Reminder #2 (Second Notice)** -> **Reminder #3 (Final Urgent Notice)**. Maximum 3 reminders per invoice.

### Step 4: Simulate Invoice Payment
You can settle the invoice either by:
- **Sandbox Buyer Payment**: Paying the sandbox invoice directly through PayPal Sandbox.
- **One-Click Dev Simulator**: Click the green **"Mark Paid"** button on the invoice row (calls `POST /dev/simulate-paid/{invoice_id}`).
- The invoice status instantly transitions to `PAID` (green badge), the amount moves to "Collected / Paid", and the auto-chaser permanently ceases reminders.

---

## 🛠️ PayPal Invoicing v2 Integration Highlights

This project adheres strictly to official PayPal Invoicing v2 specifications:

| Capability | PayPal Endpoint | Implementation |
|---|---|---|
| **OAuth 2.0 Auth** | `POST /v1/oauth2/token` | Cached bearer token with buffer refresh in [`app/paypal/client.py`](app/paypal/client.py) |
| **Create Invoice** | `POST /v2/invoicing/invoices` | Draft creation with recipient, items, USD currency, and payment terms in [`app/paypal/invoices.py`](app/paypal/invoices.py) |
| **Send Invoice** | `POST /v2/invoicing/invoices/{id}/send` | Immediate delivery to buyer email via PayPal sandbox |
| **Get Invoice** | `GET /v2/invoicing/invoices/{id}` | Status retrieval and verification |
| **Send Reminder** | `POST /v2/invoicing/invoices/{id}/remind` | Used by the autonomous chaser with escalating message copy |
| **Cancel Invoice** | `POST /v2/invoicing/invoices/{id}/cancel` | Cancellation with reason note |
| **Webhook Verification** | `POST /v1/notifications/verify-webhook-signature` | Cryptographic signature verification in [`app/paypal/webhooks.py`](app/paypal/webhooks.py) |

---

## 🤖 AI Agent & Tool Calling Architecture

- **Engine**: OpenAI-compatible Python SDK with function calling (`type: "function"`). Supports OpenAI, Groq, OpenRouter, Together, Local Ollama, and other compatible providers via `LLM_BASE_URL`.
- **Rate Limit Resilience**: Automatic retry with backoff and friendly user messaging on HTTP 429 rate limit responses.
- **Session Memory**: In-memory conversational state per session (`session_id`).
- **Prompt Safeguards**:
  - Currency strictly restricted to **USD ($)**.
  - Required fields check: `client_email`, `amount`, `description`. Never invents emails or amounts.
  - Large transaction safeguard: Invoices over **$1,000 USD** require explicit human-in-the-loop confirmation.
  - Concise, professional freelancer-oriented demeanor.

---

## 🧪 Running Automated Tests

Run the complete test suite with pytest:
```bash
pytest -v
```

Test coverage includes:
- `tests/test_paypal.py`: PayPal API functions, OAuth token caching, error handling with PayPal response bodies.
- `tests/test_db.py`: SQLite persistence, upsert operations, status sync, reminder counters.
- `tests/test_agent.py`: Tool dispatching, Anthropic tool-use parsing, session memory.
- `tests/test_api.py`: FastAPI endpoints, webhook ingestion, dev simulation.
- `tests/test_scheduler.py`: Chaser escalation tones (Friendly -> Direct -> Urgent), 60s demo mode threshold, 3-reminder limit.
- `tests/test_integration.py`: Complete end-to-end freelancer journey from conversational prompt to invoice generation, chasing, and payment.

---

## ☁️ Deployment (Render)

This repository includes a [`render.yaml`](render.yaml) specification for 1-click deployment on Render's free tier.

### Deploy Steps:
1. Fork or push this repository to GitHub.
2. Sign in to [Render](https://render.com) and click **New + -> Blueprint**.
3. Connect your repository; Render will detect `render.yaml`.
4. Enter your environment variables in the Render dashboard:
   - `PAYPAL_CLIENT_ID`
   - `PAYPAL_SECRET`
   - `LLM_API_KEY`
5. Click **Apply**. Your app will build and deploy on a live HTTPS URL.
6. Register the webhook URL in PayPal Developer Dashboard: `https://your-service.onrender.com/webhooks/paypal` and paste the generated Webhook ID into `PAYPAL_WEBHOOK_ID`.

---

## 📄 License

This project is licensed under the terms of the [MIT License](LICENSE).

