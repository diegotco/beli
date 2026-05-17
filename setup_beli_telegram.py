"""
setup_beli_telegram.py - One-time setup to authenticate Beli's own Telegram account.

Run this ONCE with: python3 setup_beli_telegram.py
It will ask for the phone number and the verification code Telegram sends.
After completing, a session file is saved at data/beli_session.session
and Beli will use that account to send and receive messages.
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.account import UpdateProfileRequest

load_dotenv()

API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION  = str(Path(__file__).parent / "data" / "beli_session")


async def main():
    if not API_ID or not API_HASH:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in your .env file")
        sys.exit(1)

    print("=" * 55)
    print("  Beli Telegram Account Setup")
    print("=" * 55)
    print("Enter Beli's phone number in international format (e.g. +1XXXXXXXXXX):")
    phone = input("  Phone: ").strip()

    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        await client.start(phone=phone)

        me = await client.get_me()
        print(f"\n✓ Session started as: {me.first_name} {me.last_name or ''} (@{me.username or 'no username'})")

        # Optionally update the profile name to "Beli"
        update = input("\nUpdate the profile name to 'Beli'? (y/n): ").strip().lower()
        if update == "y":
            await client(UpdateProfileRequest(first_name="Beli", last_name=""))
            print("✓ Name updated to 'Beli'")

        print("\n✓ Session saved to data/beli_session.session")
        print("✓ You can now add BELI_TELEGRAM_PHONE to your .env and restart Beli")


if __name__ == "__main__":
    asyncio.run(main())
