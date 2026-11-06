# Hackathon Demo Video Script: InvoicePilot (PayChase AI)

> **Target Duration:** 2 minutes 25 seconds (Maximum allowed: 2 minutes 45 seconds)  
> **Format:** Screen recording with voiceover narration.

---

## 📋 Pre-Recording Checklist

Before hitting record, ensure the following setup is complete:

- [ ] **Reset DB**: Click the red **"Reset DB"** button on the dashboard to ensure a clean invoice list.
- [ ] **Clear Chat**: Click **"Clear Chat"** above the conversation pane.
- [ ] **Demo Mode Active**: Ensure `DEMO_MODE=true` is set in `.env` (causes invoices to become overdue after 60 seconds).
- [ ] **Laptop Settings**: Plugged into AC power, screen saver and sleep turned OFF, Do Not Disturb enabled.
- [ ] **Browser Tabs Prepared**:
  - **Tab 1:** `http://localhost:8000` (PayChase AI UI: split chat on left, empty dashboard on right).
  - **Tab 2:** `https://www.sandbox.paypal.com` (Logged into your US Personal buyer sandbox account).
  - **Tab 3:** `https://developer.paypal.com/dashboard/` (PayPal Developer Apps & Credentials / Sandbox accounts).
- [ ] **Webhook Tunnel (Optional)**: Cloudflare tunnel or ngrok running if demonstrating real-time webhook push.

---

## 🎬 Timed Scene-by-Scene Script

### Beat 1: The Problem (0:00 – 0:15 | 15 seconds)
- **On Screen:** Close-up of freelancer staring at a spreadsheet or opening an unpaid invoice reminder email. Pan over to the PayChase AI interface (`http://localhost:8000`).
- **Voiceover:**
  > *"Every freelancer knows this pain: you deliver great work, but then spend hours tracking down late payments, calculating overdue days, and sending awkward reminders. What if an autonomous AI agent handled your entire PayPal invoicing and payment collection for you?"*

---

### Beat 2: Create Real PayPal Invoice by Chat (0:15 – 0:45 | 30 seconds)
- **On Screen:** On `http://localhost:8000`, freelancer types in the chat input:  
  `"Invoice sb-buyer@personal.example.com $400 for logo design, due in 15 days"` and hits Send.
- **On Screen Actions:**
  - AI thinking indicator appears.
  - AI outputs formatted confirmation card with real PayPal Invoice ID (`INV2-...`).
  - Right pane dashboard immediately populates the new invoice row with a blue `SENT` badge.
- **Voiceover:**
  > *"Meet InvoicePilot. I simply tell the agent in plain English: 'Invoice my client $400 for logo design, due in 15 days'. Under the hood, the AI agent calls PayPal's Invoicing v2 API to create and send a real PayPal sandbox invoice. Within seconds, it appears right here on my live dashboard—fully tracked."*

---

### Beat 3: Autonomous Escalating Chaser in Action (0:45 – 1:15 | 30 seconds)
- **On Screen:** 
  - Point to the invoice status. In `DEMO_MODE`, the invoice flags as overdue after 60 seconds.
  - Click **"Run Chaser Now"** (or let the background 60s timer fire).
  - Show the reminder badge increment to `⚡ 1 sent`.
  - Click on the reminder badge to open the **Reminder History Modal**, showing the timestamp and the polite "Friendly Reminder" message copy.
  - Trigger again to demonstrate tone escalation to "Second Notice" and "Urgent Final Notice".
- **Voiceover:**
  > *"Now here is the superpower: our autonomous chaser engine. In demo mode, unpaid invoices become overdue in 60 seconds. The background worker evaluates overdue status and automatically dispatches PayPal reminders directly to the client's inbox. Each reminder escalates gracefully: from friendly check-in, to firm follow-up, to urgent final notice—capped safely at three reminders."*

---

### Beat 4: Client Pays in PayPal & Live Settlement (1:15 – 1:50 | 35 seconds)
- **On Screen:**
  - Switch to **Tab 2** (`sandbox.paypal.com` logged in as the buyer).
  - Open the invoice notification under Activity showing the $400 invoice.
  - Click **Pay Now** and complete payment.
  - Switch back to **Tab 1** (PayChase AI dashboard).
  - Click **"Sync with PayPal"** (or watch the webhook update automatically).
  - The invoice row instantly transitions to a green `PAID` badge with `[PayPal Settled]`.
  - The Collected metric card increments by $400.
  - The chaser immediately deschedules all further reminders.
- **Voiceover:**
  > *"Let's switch to the client's perspective in PayPal Sandbox. The client sees the official invoice, clicks Pay Now, and completes the payment. Returning to our dashboard, PayChase AI detects the settlement via webhook and live reconciliation. The invoice flips to PAID with a verified PayPal Settled badge, and the chaser permanently stops. No manual checking, no awkward follow-ups."*

---

### Beat 5: Under the Hood: PayPal APIs + Webhooks + AI Guardrails (1:50 – 2:10 | 20 seconds)
- **On Screen:** Split screen or quick montage showing:
  - Code snippet of `app/paypal/invoices.py` (OAuth client, create draft, send, remind, cancel, delete).
  - Terminal showing pytest running with all 51 tests passing.
  - Terminal showing webhook verification code in `app/paypal/webhooks.py`.
- **Voiceover:**
  > *"Under the hood, InvoicePilot uses Python, FastAPI, and PayPal Invoicing API v2. It features OAuth token caching, cryptographic webhook signature verification, automatic draft cleanup on transmission failure, and strict AI safety rules that require human confirmation for any invoice over $1,000."*

---

### Beat 6: Wrap-up & Future Vision (2:10 – 2:25 | 15 seconds)
- **On Screen:** Full view of the dual-pane dashboard with completed metrics and GitHub repo link.
- **Voiceover:**
  > *"InvoicePilot turns PayPal from a passive payment processor into an active financial copilot that gets freelancers paid faster. Thank you for watching, and check out our open-source repo to try it yourself!"*

---

## 💡 Quick Presentation Tips
1. **Pacing:** Speak clearly and calmly; don't rush. The timings above include 20 seconds of breathing room.
2. **Cursor Movement:** Use smooth, deliberate mouse movements. Pause for half a second before clicking buttons.
3. **Zoom:** Use 110% or 125% browser zoom in Chrome so text, badges, and numbers are crisp on 1080p video.

