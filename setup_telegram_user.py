"""
setup_telegram_user.py - One-time Telethon authentication script.

Run this ONCE to link Beli to your personal Telegram account.
It will ask for your phone number and a verification code sent by Telegram.
After that, a session file is saved and Beli can send messages without re-authenticating.

Usage:
    python3 setup_telegram_user.py
"""
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = str(Path(__file__).parent / "data" / "telethon_session")

if not API_ID or not API_HASH:
    print("\n❌ Error: TELEGRAM_API_ID and TELEGRAM_API_HASH are not set in your .env file.")
    print("   Follow the instructions in SETUP.md to get them from https://my.telegram.org/apps\n")
    exit(1)

print("\n=== Telethon — First-time authentication ===")
print("This will link Beli to your personal Telegram account.")
print("You will receive a verification code from Telegram.\n")

from telethon.sync import TelegramClient

with TelegramClient(SESSION_PATH, API_ID, API_HASH) as client:
    client.start()
    me = client.get_me()
    print(f"\n✅ Authentication successful!")
    print(f"   Logged in as: {me.first_name} {me.last_name or ''} (@{me.username})")
    print(f"   Session saved to: {SESSION_PATH}.session")
    print("\nBeli can now send Telegram messages on your behalf. Restart Beli to apply.\n")
