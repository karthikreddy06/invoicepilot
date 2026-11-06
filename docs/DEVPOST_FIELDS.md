# Devpost Submission Form Fields

Copy and paste these pre-formatted snippets directly into the Devpost submission form.

---

## 1. Project Name Options (Must be under 60 characters)

- **Option A (Recommended):** `InvoicePilot: Autonomous PayPal Invoicing & Payment Chaser` *(58 chars)*
- **Option B:** `PayChase AI: Autonomous PayPal Invoicing Agent for Freelancers` *(59 chars)*
- **Option C:** `InvoicePilot: Agentic PayPal Commerce & Automated Chaser` *(55 chars)*

---

## 2. Tagline Options (Must be under 60 characters)

- **Option A (Recommended):** `AI agent creates, sends, and chases PayPal invoices until paid` *(60 chars)*
- **Option B:** `Autonomous PayPal invoicing and payment chaser for freelancers` *(59 chars)*
- **Option C:** `Chat to invoice on PayPal; auto-chase late payments with AI` *(56 chars)*

---

## 3. "Built With" Tags

```
python, fastapi, paypal-api, paypal-invoicing-v2, openai, groq, sqlite, httpx, pydantic, javascript, css3, html5, pytest
```

---

## 4. Testing Instructions (Text to paste into Devpost form)

```markdown
### Quick Testing Walkthrough for Judges:

1. **Prerequisites**: Python 3.11+, a PayPal Developer account (developer.paypal.com), and an LLM API key (Groq, OpenAI, or OpenRouter).

2. **Setup in under 3 minutes**:
   ```bash
   git clone https://github.com/your-username/PayChase-AI.git
   cd PayChase-AI
   python -m venv venv
   # Windows: .\venv\Scripts\Activate.ps1 | macOS/Linux: source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

3. **Configure .env**:
   Add your PayPal Sandbox credentials (from Developer Dashboard -> Apps & Credentials -> Sandbox Merchant App with Invoicing enabled):
   - `PAYPAL_CLIENT_ID=...`
   - `PAYPAL_SECRET=...`
   - `LLM_API_KEY=...` (e.g. from https://console.groq.com)
   - `LLM_MODEL=llama-3.3-70b-versatile` (or `gpt-4o-mini`)
   - `LLM_BASE_URL=https://api.groq.com/openai/v1` (if using Groq)
   - `DEMO_MODE=true` (marks invoices overdue after 60s for rapid review)

4. **Run the App**:
   ```bash
   uvicorn app.main:app --port 8000
   ```
   Open http://localhost:8000 in your browser.

5. **Test the Conversational Invoicing**:
   - In the chat panel on the left, type:
     "Invoice sb-buyer@personal.example.com $400 for logo design, due in 15 days"
     (Note: Ensure your recipient sandbox personal account is US-based, as PayPal blocks cross-border USD invoice payments to Indian accounts).
   - Watch the agent create and send a real PayPal Sandbox invoice. It appears immediately in the live dashboard on the right.

6. **Test Autonomous Tone-Escalated Chaser**:
   - With DEMO_MODE=true, wait 60s or click "Run Chaser Now" on the dashboard.
   - The chaser calls PayPal's /remind endpoint and issues Reminder #1 (Friendly). Click the reminder counter badge to view the audit log. Further triggers send Reminder #2 (Firm) and #3 (Urgent).

7. **Test Payment Settlement**:
   - Log into sandbox.paypal.com with your buyer sandbox account and pay the invoice.
   - Click "Sync with PayPal" on the dashboard (or let the 15s auto-reconciliation run). The invoice updates to PAID [PayPal Settled], permanently stopping the chaser.
   - (Alternative quick test: click "Simulate paid (demo)" on the invoice row to test local state transition).

8. **Automated Test Suite**:
   Run `pytest -v` to execute all 51 automated unit and integration tests.
```

---

## 5. Screenshots for Devpost Image Gallery (Order & Captions)

1. `docs/screenshots/01-create-invoice.png` — *Create an invoice by chatting*
2. `docs/screenshots/02-paid-dashboard.png` — *PAID with PayPal Settled and 3 reminders sent*
3. `docs/screenshots/03-paypal-payment.png` — *The client pays in the PayPal sandbox*


