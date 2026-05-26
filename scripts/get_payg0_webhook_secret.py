"""
scripts/get_payg0_webhook_secret.py

One-shot script to recover (or rotate) the Payg0 webhook secret.

Usage:
    python scripts/get_payg0_webhook_secret.py

It will:
  1. Ask for your Payg0 email + password (not echoed to terminal)
  2. Obtain a JWT session token
  3. Activate developer mode (required once)
  4. Use your API key to list webhooks
  5. Rotate the secret for the Beli webhook
  6. Print the new secret — copy it to Railway as PAYG0_WEBHOOK_SECRET
"""
import getpass
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api.payg0.io"
API_KEY = os.getenv("PAYG0_API_KEY", "")

if not API_KEY:
    print("ERROR: PAYG0_API_KEY not found in .env")
    sys.exit(1)


def step(msg: str) -> None:
    print(f"\n→ {msg}")


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


# ── 1. Login ──────────────────────────────────────────────────────────────────
step("Payg0 credentials (not stored anywhere)")
email    = input("  Email: ").strip()
password = getpass.getpass("  Password: ")

resp = requests.post(f"{BASE}/api/v1/auth/login",
                     json={"email": email, "password": password}, timeout=15)
if resp.status_code != 200:
    fail(f"Login failed: {resp.status_code} — {resp.text}")

data  = resp.json()
token = (data.get("token") or data.get("access_token") or
         data.get("accessToken") or data.get("jwt") or "")
if not token:
    fail(f"No token in response: {data}")
ok("Logged in")

jwt_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
api_headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# ── 2. Activate developer mode ────────────────────────────────────────────────
step("Activating developer mode")
resp = requests.patch(f"{BASE}/api/v1/users/developer-mode",
                      headers=jwt_headers, json={"enabled": True}, timeout=15)
if resp.status_code in (200, 204):
    ok("Developer mode active")
else:
    print(f"  (already active or not required: {resp.status_code})")

_EVENTS = ["payment.completed", "payment.pending", "payment.failed",
           "payment.cancelled", "payment.expired"]

# ── 3. List webhooks ──────────────────────────────────────────────────────────
step("Listing webhooks")
resp = requests.get(f"{BASE}/api/v1/webhooks", headers=api_headers, timeout=15)
if resp.status_code != 200:
    resp = requests.get(f"{BASE}/api/v1/webhooks", headers=jwt_headers, timeout=15)
if resp.status_code != 200:
    fail(f"Could not list webhooks: {resp.status_code} — {resp.text}")

data  = resp.json()
items = data if isinstance(data, list) else data.get("webhooks", data.get("data", []))

# ── 4. Register if none exist ─────────────────────────────────────────────────
if not items:
    print("  No webhooks found — registering one now.")
    public_url = input("  Enter your Railway public URL (e.g. https://web-production-xxx.up.railway.app): ").strip().rstrip("/")
    webhook_url = f"{public_url}/payg0/webhook"

    resp = requests.post(
        f"{BASE}/api/v1/webhooks",
        headers=api_headers,
        json={"url": webhook_url, "events": _EVENTS},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        resp = requests.post(
            f"{BASE}/api/v1/webhooks",
            headers=jwt_headers,
            json={"url": webhook_url, "events": _EVENTS},
            timeout=15,
        )
    if resp.status_code not in (200, 201):
        fail(f"Webhook registration failed: {resp.status_code} — {resp.text}")

    reg_data = resp.json()
    secret   = reg_data.get("secret", reg_data.get("signingSecret", ""))
    ok(f"Webhook registered at {webhook_url}")

    # Also set BELI_PUBLIC_URL reminder
    print("\n" + "=" * 60)
    print("  WEBHOOK SECRET (copy this to Railway):")
    print(f"\n  PAYG0_WEBHOOK_SECRET={secret}")
    print(f"  BELI_PUBLIC_URL={public_url}\n")
    print("=" * 60)
    print("\nAdd both variables in Railway → your project → Variables")
    print("Beli will verify webhook signatures on next deploy.\n")
    sys.exit(0)

# ── 5. Find Beli webhook and rotate secret ────────────────────────────────────
print(f"  Found {len(items)} webhook(s):")
for wh in items:
    print(f"    ID: {wh.get('id')}  URL: {wh.get('url')}  active: {wh.get('is_active')}")

beli_wh = next((w for w in items if "railway" in (w.get("url") or "").lower()), items[0])
wh_id   = beli_wh.get("id", "")
ok(f"Selected webhook ID: {wh_id}")

step("Rotating webhook secret")
resp = requests.post(f"{BASE}/api/v1/webhooks/{wh_id}/rotate-secret",
                     headers=api_headers, timeout=15)
if resp.status_code != 200:
    resp = requests.post(f"{BASE}/api/v1/webhooks/{wh_id}/rotate-secret",
                         headers=jwt_headers, timeout=15)
if resp.status_code != 200:
    fail(f"rotate-secret failed: {resp.status_code} — {resp.text}")

data   = resp.json()
secret = data.get("secret", data.get("signingSecret", ""))
if not secret:
    fail(f"No secret in response: {data}")

print("\n" + "=" * 60)
print("  WEBHOOK SECRET (copy this to Railway):")
print(f"\n  PAYG0_WEBHOOK_SECRET={secret}\n")
print("=" * 60)
print("\nAdd it in Railway → your project → Variables → PAYG0_WEBHOOK_SECRET")
print("Beli will start verifying webhook signatures on next deploy.\n")
