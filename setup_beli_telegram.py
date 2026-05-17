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
        print("ERROR: TELEGRAM_API_ID y TELEGRAM_API_HASH deben estar en el .env")
        sys.exit(1)

    print("=" * 55)
    print("  Setup de la cuenta de Telegram de Beli")
    print("=" * 55)
    print("Ingresa el número mexicano de Beli (formato: +521XXXXXXXXXX):")
    phone = input("  Teléfono: ").strip()

    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        await client.start(phone=phone)

        me = await client.get_me()
        print(f"\n✓ Sesión iniciada como: {me.first_name} {me.last_name or ''} (@{me.username or 'sin username'})")

        # Optionally update the profile name to "Beli"
        update = input("\n¿Actualizar el nombre del perfil a 'Beli'? (s/n): ").strip().lower()
        if update == "s":
            await client(UpdateProfileRequest(first_name="Beli", last_name=""))
            print("✓ Nombre actualizado a 'Beli'")

        print("\n✓ Sesión guardada en data/beli_session.session")
        print("✓ Ya puedes agregar BELI_TELEGRAM_PHONE al .env y reiniciar Beli")


if __name__ == "__main__":
    asyncio.run(main())
