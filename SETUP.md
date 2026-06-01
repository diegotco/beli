# Beli — Setup Guide

> **Easiest way to get started:** use the interactive wizard at **[b3li.io/setup](https://b3li.io/setup)** — it walks you through every step and generates your `.env` file automatically.

---

## What Beli can do

- 💬 Answer questions with context about your life (Telegram bot)
- 📱 Manage WhatsApp in ghost mode — reads and replies as if it were you
- 📧 Read and send Gmail messages
- 📅 Manage Google Calendar with natural language
- 🛒 Keep your shopping list via Google Tasks
- 🎤 Transcribe voice notes instantly (Groq/Whisper, free)
- 👥 Summarize Telegram group conversations with `/digest`
- 🧠 Learn about you and remember what matters over time
- ✉️ Give your agent its own email address (AgentMail)
- 💸 Manage Payg0 payments (MXN) — balance, history, transfers

---

## Prerequisites

- Python 3.11+
- A [Railway](https://railway.app) account (for 24/7 cloud hosting)
- A Telegram account

---

## Quick start

```bash
# 1. Clone or fork the repo
git clone https://github.com/diegotco/beli.git
cd beli

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Create your .env file
cp .env.example .env
# Edit .env with your API keys (see sections below)

# 4. Create your personal files (see section below)

# 5. Run locally
python3 main.py
```

---

## Personal files (required)

These files are in `.gitignore` — they never get pushed to GitHub.
Place them in the project root after cloning.

### `owner-profile.md`
Tells Beli who you are. Edit with your name, city, timezone, preferences, and anything you want her to know about you.

```markdown
# My profile

## Basic info
- **Name:** Your name
- **City:** Your city
- **Timezone:** America/Mexico_City

## About me
- ...

## Assistant preferences
- **Language:** Spanish
- **Tone:** Casual
```

### `contacts.json`
Maps nicknames to phone numbers. Beli uses this to find contacts by name.

```json
{
  "mom": "+521234567890",
  "work": "+521234567891"
}
```

Phone numbers must include country code. This file is private — never commit it.

### `reminders.md`
Persistent reminders Beli always keeps in mind (allergies, recurring tasks, special instructions).

```markdown
# Reminders

- Check emails on Monday mornings
```

---

## Module 1 — Core (required)

### Anthropic API key
1. Go to https://console.anthropic.com/settings/keys
2. Create an account and click **"Create Key"**
3. Copy the key (starts with `sk-ant-...`)

```
ANTHROPIC_API_KEY=sk-ant-...
```

**Cost:** ~$3–8 USD/month with moderate use (~50 messages/day).

### Telegram Bot
1. Open Telegram → search **@BotFather**
2. Send `/newbot` → choose name and username (must end in `bot`)
3. Copy the token BotFather gives you

```
TELEGRAM_BOT_TOKEN=1234567890:AAF...
TELEGRAM_BOT_USERNAME=your_bot_username
```

### Groq (voice transcription, free)
1. Create account at https://console.groq.com
2. Generate an API key

```
GROQ_API_KEY=gsk_...
```

---

## Module 2 — WhatsApp (optional)

Requires WAHA — a self-hosted WhatsApp bridge deployed as a Docker container on Railway.

1. In Railway: New Service → Docker Image → `devlikeapro/waha`
2. Copy the public URL of the service
3. Create an API key in the WAHA dashboard

```
WAHA_URL=https://waha.railway.app
WAHA_SESSION=default
WAHA_API_KEY=your-waha-api-key
```

---

## Module 3 — Gmail (optional)

### Set up Google Cloud project
1. Go to https://console.cloud.google.com
2. Create a project → APIs & Services → Library → enable **Gmail API**
3. Go to **Google Auth Platform → Audience** → set Publishing status to **"In production"**

> ⚠️ **Critical:** if you leave the app in *Testing* mode, Google revokes tokens every **7 days** and you'll need to re-authorize repeatedly. Switching to *In production* is free and requires no Google review.

4. APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app
5. Download the JSON → save as `google_client_secret.json` in the project root
6. Run the setup script:

```bash
python3 setup_gmail.py
```

7. Copy the JSON output and add it to your `.env`:

```
GMAIL_CREDENTIALS={"token": "...", "refresh_token": "..."}
```

---

## Module 4 — Google Calendar + Tasks (optional)

Uses the same Google Cloud project as Gmail.

1. APIs & Services → Library → enable **Google Calendar API** and **Tasks API**
2. Make sure the OAuth app is set to **"In production"** (see Module 3 note above)
3. Run the setup script:

```bash
python3 setup_google_calendar.py
```

4. Copy the JSON output:

```
GOOGLE_CALENDAR_CREDENTIALS={"token": "...", "refresh_token": "..."}
```

---

## Module 5 — Telegram ghost mode (optional)

Lets Beli read your personal Telegram chats and send messages as you. Also enables `/digest` for group summaries.

1. Go to https://my.telegram.org/apps → create an application
2. Copy API ID and API Hash
3. Generate a session string:

```bash
python3 generate_session_strings.py
```

```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abc123def456...
OWNER_SESSION_STRING=1BQANOTEuMTgy...
```

---

## Module 6 — Payg0 payments (optional)

Lets Beli check your balance, view transaction history, and send MXN payments.

1. Create account at https://payg0.io
2. Copy your API key from the dashboard
3. Run the webhook secret script:

```bash
python3 scripts/get_payg0_webhook_secret.py
```

```
PAYG0_API_KEY=payg0_...
BELI_PUBLIC_URL=https://your-service.railway.app
PAYG0_WEBHOOK_SECRET=whsec_...
```

---

## Module 7 — AgentMail (optional)

Gives your agent its own email address to receive messages.

1. Create account at https://agentmail.to
2. Create an inbox and copy the API key and inbox address

```
AGENTMAIL_API_KEY=am_...
AGENTMAIL_INBOX_ID=youragent@agentmail.to
```

---

## Deploy on Railway

1. Create account at https://railway.app
2. New Project → Deploy from GitHub repo → select your Beli fork
3. Go to **Variables** → add all variables from your `.env`
4. Railway auto-detects the `Procfile` and deploys

> 💡 You can paste all variables at once in Railway using the Raw Editor in `KEY=VALUE` format.

---

## Telegram commands

| Command    | What it does                                    |
|------------|-------------------------------------------------|
| `/start`   | Initial greeting                                |
| `/ayuda`   | Shows available commands                        |
| `/borrar`  | Clears conversation history                     |
| `/memoria` | Shows facts Beli has learned about you          |
| `/digest`  | Summarizes a Telegram group (ghost mode needed) |

---

## How memory works

**Short-term:** last 20 messages of conversation history (configurable via `MEMORY_WINDOW`).

**Long-term:** every hour, Claude automatically extracts and saves facts worth remembering. Use `/memoria` to see what Beli knows about you.

---

## Customizing Beli

- **Name and personality:** edit `personality.py`
- **Personal context:** edit `owner-profile.md`
- **Contacts:** edit `contacts.json`
- **Persistent reminders:** edit `reminders.md`

After editing, redeploy on Railway (or restart locally with `Ctrl+C` then `python3 main.py`).

---

## Estimated monthly cost

| Service       | Cost/month  |
|---------------|-------------|
| Railway       | ~$5         |
| Anthropic API | ~$3–8       |
| WAHA          | ~$0–5       |
| AgentMail     | ~$0–5       |
| Everything else | Free      |
| **Total**     | **~$8–23**  |

With only Module 1 active: **~$8–13/month**.
