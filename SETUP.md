# BELI — Setup and Usage Guide


## What is Beli
Beli is your personal AI assistant. Claude (by Anthropic) is her brain.
Currently works on Telegram. Coming soon: WhatsApp, Gmail, Yahoo, and Google Calendar.

---

## STEP 1 — Get credentials (you do this once)

### 1A. Anthropic API Key (Beli's brain)
1. Go to https://console.anthropic.com/settings/keys
2. Create an account or sign in
3. Click **"Create Key"**
4. Copy the key (starts with `sk-ant-...`)
5. Save it somewhere safe — it's only shown once

**Estimated cost:** using `claude-haiku-4-5-20251001` (the default model),
a typical conversation costs less than $0.001. With normal usage, monthly cost is $1–5 USD.

### 1B. Telegram Bot Token
1. Open Telegram on your phone or computer
2. Search for **@BotFather** (it's an official Telegram bot)
3. Send the message: `/newbot`
4. BotFather will ask for:
   - **Bot name**: type `Beli` (or whatever display name you want)
   - **Bot username**: must end in `bot`, e.g. `beli_myassistant_bot`
5. BotFather will give you a token like: `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`
6. Copy that token

---

## STEP 2 — Configure the .env file

1. In the project folder, copy `.env.example` and rename it to `.env` (no `.example`)
2. Open `.env` with any text editor (TextEdit on Mac, Notepad on Windows)
3. Fill in the values:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
TELEGRAM_BOT_TOKEN=123456789:your-token-here
```

4. Save the file

---

## STEP 3 — Install Python and dependencies

### Install Python (if you don't have it)
- Go to https://www.python.org/downloads/
- Download the latest version (3.11 or higher)
- Install with default options

### Install Beli's dependencies

Open Terminal (Mac: `Cmd + Space`, type "Terminal") and run:

```bash
# Navigate to the project folder
cd /path/to/beli

# Install dependencies
pip3 install -r requirements.txt
```

---

## STEP 4 — Run Beli

In Terminal, from the project folder:

```bash
python3 main.py
```

If you see a message like:
```
Starting Beli on Telegram (polling mode)...
Beli is ready. Waiting for messages on Telegram...
```

Beli is running! Now:
1. Open Telegram
2. Search for your bot's username (the one you chose in STEP 1B)
3. Send it a message

---

## Available Telegram commands

| Command    | What it does                                          |
|------------|-------------------------------------------------------|
| `/start`   | Initial greeting and introduction                     |
| `/ayuda`   | Shows available commands                              |
| `/borrar`  | Clears the current conversation history               |
| `/memoria` | Shows the facts Beli has learned and remembers about you |

---

## Customize Beli

To change how she talks, her name, or her instructions:
- Open `personality.py` and edit `CORE_IDENTITY`
- To update your personal profile and context, edit `owner-profile.md`
- Save and restart Beli (`Ctrl+C` to stop, then `python3 main.py` again)

---

## How Beli's memory works

Beli has two types of memory:

**Short-term (sliding window):** the last 20 messages of conversation history, loaded
on every message. Configurable via `MEMORY_WINDOW` in `.env`.

**Long-term (automatic facts):** every hour, the system asks Claude to identify
what's worth remembering permanently from recent conversations and saves those facts.
Use `/memoria` to see what Beli has learned about you.

---

## View logs (to diagnose errors)

Logs are saved automatically in:
```
logs/beli.log
```

If something fails, open that file and look for lines with `ERROR`.

---

## Stop Beli

In the Terminal where Beli is running, press `Ctrl + C`.

---

## Project architecture

```
beli/
├── main.py                ← Entry point. Run this.
├── config.py              ← Reads .env and validates credentials
├── personality.py         ← Beli's identity and behavior logic
├── owner-profile.md       ← Owner's personal profile (edit this to update context)
├── requirements.txt       ← Python libraries
├── .env                   ← YOUR CREDENTIALS (never share)
│
├── brain/
│   └── claude_client.py   ← Connects to Claude (Anthropic API)
│
├── memory/
│   ├── manager.py         ← Persistent memory (SQLite)
│   └── extractor.py       ← Hourly automatic fact extraction
│
├── channels/
│   └── telegram.py        ← Telegram module
│
├── data/
│   └── beli_memory.db     ← Database (created automatically)
│
└── logs/
    └── beli.log           ← Event and error logs
```

---

## Upcoming modules

- `channels/whatsapp.py`            — WhatsApp Business API
- `channels/email.py`               — Gmail and Yahoo
- `integrations/google_calendar.py` — Google Calendar

---

## Estimated costs (May 2026)

| Service       | Plan            | Estimated/month |
|---------------|-----------------|-----------------|
| Anthropic API | claude-haiku    | $1 – $5 USD     |
| Telegram Bot  | Free            | $0              |
| Server        | Railway (hobby) | $5 USD          |
| **TOTAL**     |                 | **$6 – $10 USD**|

Well below the $25 USD monthly limit.
