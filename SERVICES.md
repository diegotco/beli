# Beli — External Services & Cost Reference

Every external service Beli uses, its purpose, and estimated monthly cost
based on light personal use (1 user, ~50 messages/day).

---

## Paid services

### 🚂 Railway — Cloud hosting
**Purpose:** Runs Beli 24/7 in the cloud.
**Plan:** Hobby ($5/month flat + resource usage). Beli is lightweight and typically stays within the included credit.
**Estimated cost:** ~$5/month
**URL:** https://railway.app

---

### 🤖 Anthropic — Claude API (Beli's brain)
**Purpose:** Processes all messages, reads chats, drafts replies, extracts memory facts.
**Model:** `claude-sonnet-4-5` (default). Can be switched to `claude-haiku-4-5` for ~10x lower cost.
**Pricing:** ~$3/M input tokens, ~$15/M output tokens. Each turn ≈ 2,000–5,000 tokens.
**Estimated cost:** ~$3–8/month at 50 messages/day
**URL:** https://console.anthropic.com

---

### 📱 WAHA — WhatsApp bridge (optional)
**Purpose:** Self-hosted Docker container that bridges WhatsApp to Beli (ghost mode).
**Deployment:** Docker image on Railway as a separate service.
**Estimated cost:** ~$0–5/month (depends on Railway resource usage)
**URL:** https://waha.devlike.pro

---

### ✉️ AgentMail — Agent's own email (optional)
**Purpose:** Gives your agent its own email address to receive messages.
**Estimated cost:** ~$0–5/month depending on plan
**URL:** https://agentmail.to

---

### 💬 OpenAI GPT-4o — Chat router (optional)
**Purpose:** Handles general conversation questions (no tools needed) for faster, cheaper responses. Claude handles all tool-use actions regardless.
**Estimated cost:** Variable — only used for non-tool messages
**URL:** https://platform.openai.com

---

## Free services

### ✈️ Telegram Bot API
**Purpose:** Main interface — the bot the owner chats with.
**Cost:** Free, no limits for personal use.
**URL:** https://core.telegram.org/bots/api

---

### 👻 Telegram MTProto (Telethon) — Ghost mode
**Purpose:** Reads personal Telegram chats and sends messages as the owner. Enables `/digest`.
**Cost:** Free — uses official Telegram API with personal credentials.
**Requires:** API ID + Hash from https://my.telegram.org/apps

---

### 🎤 Groq — Voice transcription
**Purpose:** Transcribes voice notes using Whisper.
**Model:** `whisper-large-v3`
**Cost:** Free tier covers hundreds of minutes/month — sufficient for personal use.
**URL:** https://console.groq.com

---

### 📅 Google Calendar API + ✅ Google Tasks API
**Purpose:** Read/create calendar events and manage shopping list.
**Cost:** Free — well within Google's generous personal quotas.
**Setup note:** OAuth app must be set to **"In production"** (Google Auth Platform → Audience) to prevent tokens from expiring every 7 days.
**URL:** https://console.cloud.google.com

---

### 📧 Gmail API
**Purpose:** Read inbox and send emails from the owner's Gmail account.
**Cost:** Free.
**Setup note:** Same OAuth app as Calendar — ensure **"In production"** status.

---

### 💸 Payg0 — MXN payments
**Purpose:** Check balance, view transaction history, send MXN payments from Telegram.
**Cost:** Free API — Payg0 may charge transaction fees per their platform terms.
**URL:** https://payg0.io

---

### 🐙 GitHub
**Purpose:** Source control. Optional: GitHub Actions for health check monitoring.
**Cost:** Free for public repos.
**URL:** https://github.com

---

## Monthly cost summary

| Service              | Cost/month   | Required?  |
|----------------------|--------------|------------|
| Railway              | ~$5          | ✅ Yes     |
| Anthropic (Claude)   | ~$3–8        | ✅ Yes     |
| WAHA (WhatsApp)      | ~$0–5        | Optional   |
| AgentMail            | ~$0–5        | Optional   |
| OpenAI (GPT-4o)      | Variable     | Optional   |
| Everything else      | Free         | —          |
| **Total**            | **~$8–23**   |            |

> With only the core module active (Telegram + AI): **~$8–13/month**.
> With all paid modules active (+ WhatsApp + AgentMail): up to **~$23/month**.
> Costs scale with usage — very low usage (< 20 msgs/day) can be as low as **$5–7/month**.

---

## Reducing costs

- **Switch to Haiku:** set `CLAUDE_MODEL=claude-haiku-4-5-20251001` in Railway (~10x cheaper than Sonnet, less capable)
- **Reduce memory window:** lower `MEMORY_WINDOW` to send fewer tokens per request
- **Skip optional modules:** only enable the services you actually use
