"""
generate_session_strings.py - Regenerate Telethon session strings for Railway.

Run this when session strings have been invalidated (AuthKeyDuplicatedError).
It authenticates each account and prints the new session string to paste into
Railway environment variables.

Usage:
    python3 generate_session_strings.py
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")


async def authenticate(label: str, phone: str) -> str:
    """Authenticate a Telegram account and return the session string."""
    print(f"\n{'='*55}")
    print(f"  Authenticating: {label}")
    print(f"  Phone: {phone}")
    print(f"{'='*55}")

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start(phone=phone)
    session_string = client.session.save()
    me = await client.get_me()
    print(f"✓ Authenticated as: {me.first_name} (@{me.username or 'no username'})")
    await client.disconnect()
    return session_string


async def main():
    if not API_ID or not API_HASH:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
        sys.exit(1)

    owner_phone = input("\nYour personal Telegram phone (for OWNER_SESSION_STRING, e.g. +521XXXXXXXXXX): ").strip()
    beli_phone  = os.getenv("BELI_TELEGRAM_PHONE", "").strip() or \
                  input("Beli's Telegram phone (for BELI_SESSION_STRING, e.g. +529XXXXXXXXXX): ").strip()

    owner_string = await authenticate("Owner account", owner_phone)
    beli_string  = await authenticate("Beli account", beli_phone)

    print("\n" + "="*55)
    print("  NEW SESSION STRINGS — copy these to Railway")
    print("="*55)
    print(f"\nOWNER_SESSION_STRING=\n{owner_string}\n")
    print(f"BELI_SESSION_STRING=\n{beli_string}\n")
    print("="*55)
    print("Run this to update Railway automatically:")
    print(f'  export RAILWAY_API_TOKEN=<your_token>')
    print(f'  railway variables set OWNER_SESSION_STRING="{owner_string}"')
    print(f'  railway variables set BELI_SESSION_STRING="{beli_string}"')


if __name__ == "__main__":
    asyncio.run(main())
