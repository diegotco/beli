# 🤖 Beli — Your Personal AI Agent

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Railway](https://img.shields.io/badge/Deploy-Railway-purple.svg)](https://railway.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Claude](https://img.shields.io/badge/AI-Claude%20Sonnet-orange.svg)](https://anthropic.com)

> Beli lives in Telegram and manages your WhatsApp, Gmail, Google Calendar, shopping lists,
> group summaries, voice notes, payments, and more.
> **Open source. Runs on your own accounts. Costs ~$8–18/month.**

---

*¿Hablas español? Lee esta guía en [b3li.io](https://b3li.io)*

---

## ✨ What Beli can do

- 💬 **Answer questions** from Telegram with context about your life
- 📱 **Manage WhatsApp** in ghost mode — reads and replies as if it were you
- 📧 **Draft and summarize Gmail** messages
- 📅 **Manage Google Calendar** with natural language
- 🛒 **Keep your shopping list** via Google Tasks
- 🎤 **Transcribe voice notes** instantly with Groq/Whisper (free)
- 👥 **Summarize Telegram group conversations** with `/digest`
- 🧠 **Learn about you** and remember what matters over time
- ✉️ **Has its own email address** via AgentMail (beli@agentmail.to)
- 🐦 **Monitor and post on X/Twitter** — mentions, likes, tweets
- 💸 **Manage Payg0 payments** (MXN) — balance, history, transfers

---

## 🏗️ Architecture

```
User (Telegram / WhatsApp / Email)
             │
             ▼
          main.py
             │
      brain/router.py ──────────► Claude API (Anthropic)
             │                           │
     tools/executor.py          OpenAI GPT-4o (optional)
      ┌──────┼──────┬───────┬───────┐
      ▼      ▼      ▼       ▼       ▼
   Gmail  Calendar Tasks  X/Twitter Payg0
             │
      channels/
   ┌──────────┴────────────┐
   ▼                       ▼
telegram.py         whatsapp_webhook.py
telegram_listener.py  email_webhook.py
(Telethon ghost mode)  payg0_webhook.py
```

---

## 💰 Services & Costs

Everything runs on **your own accounts**. You control all data.

| Service | Purpose | Cost/month |
|---|---|---|
| 🚂 Railway | 24/7 cloud hosting | ~$5 |
| 🤖 Anthropic (Claude API) | AI brain | ~$3–8 |
| ✈️ Telegram Bot API | Main interface (BotFather) | Free |
| 👻 Telegram MTProto (Telethon) | Ghost mode + /digest | Free |
| 🎤 Groq (Whisper) | Voice note transcription | Free |
| ✉️ AgentMail | Beli's own email address | $0–5 |
| 📱 WAHA | WhatsApp bridge (self-hosted Docker) | ~$0–5 |
| 📅 Google Calendar API | Calendar management (OAuth) | Free |
| 📧 Gmail API | Read/send emails (OAuth) | Free |
| ✅ Google Tasks API | Shopping list (same OAuth as Calendar) | Free |
| 💬 OpenAI (GPT-4o) | Optional chat router | Variable |
| 🐦 X/Twitter API v2 | Monitor mentions/likes, post tweets | Free (DMs $100/mo) |
| 💸 Payg0 | MXN payments platform | Free |
| 🐙 GitHub | Source control + health check Actions | Free |

> With moderate use (~50 msgs/day) the real cost is **~$8/month**.

---

## 🚀 Quick Start (developers)

**Prerequisites:** Python 3.11+, a Railway account, a Telegram account.

```bash
# 1. Clone the repo
git clone https://github.com/diegotco/beli.git
cd beli

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env file
cp .env.example .env
# Edit .env with your API keys (see Environment Variables below)

# 4. Run locally
python3 main.py
```

For full setup instructions see [`SETUP.md`](SETUP.md) and [`SERVICES.md`](SERVICES.md).

---

## 🧩 Optional Modules

| Module | What it does | Setup script | Key env vars |
|---|---|---|---|
| 📱 WhatsApp | Ghost mode via WAHA bridge | — | `WAHA_URL`, `WAHA_API_KEY`, `WAHA_SESSION` |
| 📧 Gmail | Read/send emails | `setup_gmail.py` | `GMAIL_CREDENTIALS` |
| 📅 Google Calendar + Tasks | Events + shopping list | `setup_google_calendar.py` | `GOOGLE_CALENDAR_CREDENTIALS` |
| 👻 Telegram Ghost Mode | Read chats, `/digest` command | `generate_session_strings.py` | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `OWNER_SESSION_STRING` |
| 🐦 X/Twitter | Monitor mentions, post tweets | — | `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` |
| 💸 Payg0 | MXN payments | `scripts/get_payg0_webhook_secret.py` | `PAYG0_API_KEY`, `PAYG0_WEBHOOK_SECRET` |

---

## 🌐 Non-technical users

Not a developer? No problem.

Open ChatGPT, Claude, Grok, or Gemini and paste the setup prompt from **[b3li.io](https://b3li.io)**. An AI will guide you through forking the repo, creating accounts, and deploying to Railway — step by step, with screenshots.

**[→ Get started at b3li.io](https://b3li.io)**

Or use the **interactive setup wizard** — open `setup_wizard/wizard.html` in your browser (or run `python3 -m http.server 8080` in that folder). It walks you through each module and generates your `.env` file automatically. Everything runs locally — no data is ever sent anywhere.

---

## 📁 Project structure

```
beli/
├── main.py                        # Entry point, webhook server
├── personality.py                 # System prompt and identity
├── config.py                      # App configuration
├── requirements.txt
├── Procfile                       # Railway process definition
├── railway.json                   # Railway deploy config
│
├── brain/
│   ├── router.py                  # Claude/OpenAI routing logic
│   ├── claude_client.py           # Anthropic SDK wrapper
│   └── openai_client.py           # OpenAI SDK wrapper
│
├── channels/
│   ├── telegram.py                # Main Telegram bot (python-telegram-bot)
│   ├── telegram_listener.py       # Telethon listener (ghost mode)
│   ├── whatsapp_webhook.py        # WAHA webhook handler
│   ├── email_webhook.py           # AgentMail webhook handler
│   └── payg0_webhook.py           # Payg0 webhook handler
│
├── tools/
│   ├── executor.py                # Tool dispatch
│   ├── definitions.py             # Tool schemas for Claude
│   ├── calendar_tool.py           # Google Calendar + Tasks
│   ├── gmail_tool.py              # Gmail read/send
│   ├── email_sender.py            # Outbound email (AgentMail)
│   ├── transcriber.py             # Groq Whisper transcription
│   ├── telegram_sender.py         # Send Telegram messages
│   ├── whatsapp_sender.py         # Send WhatsApp via WAHA
│   ├── tasks_tool.py              # Google Tasks (shopping list)
│   ├── payg0_tool.py              # Payg0 payments
│   ├── x_monitor.py               # X/Twitter integration
│   ├── vision.py                  # Image understanding
│   └── birthday_scheduler.py      # Birthday reminders
│
├── settings/
│   └── notifications.py           # Notification preferences
│
├── scripts/
│   └── get_payg0_webhook_secret.py
│
├── setup_gmail.py                 # OAuth setup for Gmail
├── setup_google_calendar.py       # OAuth setup for Calendar
├── setup_telegram_user.py         # Telegram user session setup
├── setup_beli_telegram.py         # Bot initial config
├── generate_session_strings.py    # Generate Telethon session strings
│
├── landing/                       # b3li.io landing page
│   ├── index.html
│   ├── server.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── railway.json
│
├── setup_wizard/                  # Interactive setup wizard
│   └── wizard.html
│
├── memory/                        # Persistent memory files
├── data/                          # Runtime data
├── logs/                          # Log files
│
├── owner-profile.md               # Your profile (not committed)
├── reminders.md                   # Persistent reminders
├── contacts.json                  # Contact aliases
├── SETUP.md                       # Detailed setup guide
└── SERVICES.md                    # Services reference
```

---

## ⚙️ Environment Variables

| Variable | Description | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key from console.anthropic.com | ✅ Required |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | ✅ Required |
| `TELEGRAM_BOT_USERNAME` | Bot username (without @) | ✅ Required |
| `GROQ_API_KEY` | Groq API key for voice transcription | Recommended |
| `TELEGRAM_API_ID` | MTProto API ID from my.telegram.org | Ghost mode |
| `TELEGRAM_API_HASH` | MTProto API Hash from my.telegram.org | Ghost mode |
| `OWNER_SESSION_STRING` | Telethon session string | Ghost mode |
| `WAHA_URL` | WAHA service URL | WhatsApp module |
| `WAHA_SESSION` | WAHA session name (default: "default") | WhatsApp module |
| `WAHA_API_KEY` | WAHA API key | WhatsApp module |
| `GMAIL_CREDENTIALS` | JSON credentials from setup_gmail.py | Gmail module |
| `GOOGLE_CALENDAR_CREDENTIALS` | JSON credentials from setup_google_calendar.py | Calendar module |
| `PAYG0_API_KEY` | Payg0 API key | Payg0 module |
| `PAYG0_WEBHOOK_SECRET` | Payg0 webhook secret | Payg0 module |
| `BELI_PUBLIC_URL` | Your Railway service public URL | Webhooks |
| `X_API_KEY` | X/Twitter API key | Twitter module |
| `X_API_SECRET` | X/Twitter API secret | Twitter module |
| `X_ACCESS_TOKEN` | X/Twitter access token | Twitter module |
| `X_ACCESS_TOKEN_SECRET` | X/Twitter access token secret | Twitter module |
| `OPENAI_API_KEY` | OpenAI key (optional router fallback) | Optional |

---

## 🤝 Contributing

PRs are welcome! Whether it's a new integration, a bug fix, better docs, or a new language — open an issue first to discuss, then send a PR. The codebase is designed to be modular, so adding new tools/channels is straightforward.

---

## 📄 License

MIT — see [LICENSE](LICENSE).
