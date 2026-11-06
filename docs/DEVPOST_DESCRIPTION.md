# Devpost Project Story: InvoicePilot (PayChase AI)

## Inspiration
Ask any freelancer what they dislike most about running their business, and the answer is almost universal: chasing late payments. It is awkward, time-consuming, and emotionally draining to continually check bank statements, calculate days overdue, and draft delicate reminder emails to clients. Freelancers lose billions annually in unpaid invoices simply because the follow-up process is manual and uncomfortable. We wanted to build an autonomous "Agentic Commerce" assistant that takes this burden off the freelancer's shoulders entirely.

## What It Does
InvoicePilot (PayPal app name: PayChase AI) acts as an autonomous billing and collection department for solo freelancers:
1. **Natural Language Invoicing**: Freelancers simply tell the agent in chat: *"Invoice sarah@example.com $400 for logo design, due in 15 days"*.
2. **Real PayPal Invoicing API v2**: The AI agent creates and sends a real PayPal invoice directly through the PayPal Sandbox.
3. **Autonomous Escalating Chaser**: A background engine identifies invoices that have passed their due date and automatically sends up to 3 escalating reminders through PayPal's `/remind` API (Friendly check-in -> Firm second notice -> Urgent final payment notice).
4. **Real-time Webhook & Reconciliation**: Ingests PayPal webhooks and runs background status synchronization so the chaser instantly stops the moment an invoice is paid.
5. **Live Dual-Pane Dashboard**: Features conversational AI on the left and a reactive real-time dashboard on the right with KPI counters and reminder audit trails.

## How We Built It
- **Backend**: Python 3.11+ and FastAPI.
- **AI Agent**: OpenAI-compatible tool-calling loop (supporting OpenAI, Groq, OpenRouter, and Ollama) with strict safety prompts (human confirmation required for invoices exceeding $1,000 USD, mandatory client email and amount, USD currency lock).
- **PayPal Integration**: Official PayPal Invoicing v2 REST endpoints (`/v2/invoicing/invoices`, `/send`, `/remind`, `/cancel`), OAuth 2.0 client credentials token caching with buffer refresh, and cryptographic webhook signature verification (`/v1/notifications/verify-webhook-signature`).
- **Database & Engine**: SQLite for local persistence with transactional safety and an asynchronous background scheduler for automated reminder evaluation.
- **Frontend**: Clean vanilla JavaScript and CSS split-screen interface with zero build step.

## Challenges We Ran Into
Building real agentic commerce revealed several subtle real-world integration edge cases:
1. **PayPal Create Response Structure**: PayPal's `POST /v2/invoicing/invoices` returns HTTP 201 with HATEOAS links rather than an explicit top-level `id` field. We had to parse the invoice ID reliably from the `href` URI.
2. **Cross-Border Recipient Restrictions**: PayPal blocks cross-border USD invoices sent to Indian recipient accounts in sandbox. We had to ensure our test buyer sandbox accounts were strictly configured as US Personal accounts.
3. **Webhook Payload Variations**: PayPal sends webhook event resources with different shapes depending on the event (nested inside `resource["invoice"]["id"]`, at `resource["id"]`, or within `resource["links"]`). We engineered a multi-strategy extractor to handle all variants.
4. **API Throttling & Reconciliation Locks**: Continuous background polling hammered sandbox endpoints. We implemented a shared async lock, 15-second minimum intervals, and bounded concurrency (`asyncio.Semaphore(5)`) to protect API quotas.
5. **LLM Reasoning Leakage**: Open-weights reasoning models occasionally leaked internal chain-of-thought tokens into the chat. We configured explicit suppression flags and introduced a deterministic template safety-net that builds the final confirmation directly from the verified PayPal response.

## Accomplishments That We're Proud Of
- A truly working, end-to-end autonomous flow: natural language prompt to real PayPal Sandbox delivery to webhook detection to automated tone-escalated reminder dispatch.
- Robust guardrails: zero hallucinations on amounts or emails, and an explicit safeguard on transactions over $1,000.
- A fully tested codebase with 51 automated pytest unit and integration tests.

## What We Learned
True agentic commerce is far more than slapping an LLM on top of a database. Real payment APIs have strict state machines. The AI agent must respect idempotency, cleanup orphan drafts on transmission errors, verify cryptographic signatures, and reconcile live payment truth so clients are never chased for settled invoices.

## What's Next
- Multi-currency support (EUR, GBP, CAD) with automated conversion rates.
- Multi-channel escalation: adding SMS (Twilio) and WhatsApp Business reminders alongside PayPal email notifications.
- Multi-tenant OAuth for team agencies and independent contractor marketplaces.

