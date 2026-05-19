# Beli — External Services & Cost Estimate

This file lists every external service Beli depends on, its purpose, pricing model,
and an estimated monthly cost based on light personal use (1 user, ~50 messages/day).

---

## 1. Railway — Cloud Hosting
**Purpose:** Runs the Beli process 24/7 in the cloud.
**Plan:** Hobby ($5/month flat + resource usage)
**Pricing:**
- $5/month base fee (includes $5 of usage credit)
- CPU: ~$0.000463/vCPU/minute
- RAM: ~$0.000231/GB/minute
- Beli is lightweight — typically stays within the $5 credit
**Estimated cost:** ~$5/month
**URL:** https://railway.app

---

## 2. Anthropic — Claude API (Beli's brain)
**Purpose:** Processes all messages, reads chats, drafts replies, extracts facts.
**Model in use:** `claude-sonnet-4-5`
**Pricing (input / output per million tokens):**
- Input: ~$3.00
- Output: ~$15.00
- Each conversation turn ≈ 2,000–5,000 tokens (including system prompt + history)
**Estimated cost:** ~$3–8/month at 50 messages/day
**Note:** Switching to `claude-haiku-4-5` reduces cost by ~10x at the expense of quality.
**URL:** https://console.anthropic.com

---

## 3. Telegram Bot API — Bot interface
**Purpose:** The @IamBeliBot interface through which the owner chats with Beli.
**Pricing:** Free — no limits for personal use.
**URL:** https://core.telegram.org/bots/api

---

## 4. Telegram MTProto (via Telethon) — Personal account access
**Purpose:** Reads the owner's personal Telegram chats (`/digest`) and sends messages
as the owner (ghost mode) using the owner's own Telegram session.
**Pricing:** Free — uses the official Telegram API with personal credentials.
**Requires:** Telegram API ID + API Hash from https://my.telegram.org/apps

---

## 5. Groq — Voice note transcription
**Purpose:** Transcribes voice messages sent to Beli using OpenAI's Whisper model.
**Model:** `whisper-large-v3`
**Pricing:**
- Free tier: generous free quota for personal use
- Paid: $0.111/hour of audio (~$0.002/minute)
**Estimated cost:** ~$0/month (free tier sufficient for personal use)
**URL:** https://console.groq.com

---

## 6. AgentMail — Beli's email inbox
**Purpose:** Gives Beli a real email address (`beli@agentmail.to`) so she can send
emails on the owner's behalf.
**Pricing:** Check current pricing at https://agentmail.to
**Estimated cost:** ~$0–5/month depending on plan
**URL:** https://agentmail.to

---

## 7. GitHub — Source control + health monitoring
**Purpose (1):** Hosts the source code repository.
**Purpose (2):** GitHub Actions runs a health check every 5 minutes that pings
`/health` on Railway and sends a Telegram alert if Beli goes down.
**Pricing:** Free for public and private repos (Actions: 2,000 min/month free).
- Health check workflow uses ~1 min/run × 288 runs/day = ~288 min/day → paid tier needed
  if the repo is private and usage exceeds the free quota.
**Estimated cost:** $0/month (public repo) or $4/month (GitHub Pro for private repos)
**URL:** https://github.com

---

## Summary — Estimated Monthly Cost

| Service         | Cost/month       |
|-----------------|------------------|
| Railway         | ~$5.00           |
| Anthropic API   | ~$3–8.00         |
| Telegram APIs   | Free             |
| Groq (Whisper)  | Free             |
| AgentMail       | ~$0–5.00         |
| GitHub          | Free             |
| **Total**       | **~$8–18/month** |

> Costs scale with usage. At very low usage (< 20 messages/day) the total can be
> as low as $5–7/month. At high usage (hundreds of messages/day + many voice notes)
> it could reach $20–30/month, driven mainly by the Claude API.

---

## Reducing costs

- **Swap model:** Change `CLAUDE_MODEL=claude-haiku-4-5-20251001` in Railway to use
  the cheaper/faster Haiku model (~10x cheaper than Sonnet).
- **Reduce memory window:** Lower `MEMORY_WINDOW` to send fewer tokens per request.
- **Voice notes:** Groq's free tier covers hundreds of minutes/month — unlikely to hit limits.
