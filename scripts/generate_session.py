"""
generate_session.py
One-time script to generate the TELEGRAM_SESSION_STRING.

Run ONCE from Termux (or any terminal).
The generated SESSION_STRING is then added to GitHub Secrets.
It never expires as long as you don't manually log out.

Usage:
    pip install telethon
    python scripts/generate_session.py
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    print("=" * 55)
    print("  AirdropAgent — Generate Telegram SESSION_STRING")
    print("=" * 55)
    print()
    print("You need API_ID and API_HASH from my.telegram.org")
    print("(see README — Step 5: Telegram API)")
    print()

    api_id   = input("Enter your API_ID   : ").strip()
    api_hash = input("Enter your API_HASH : ").strip()

    if not api_id.isdigit():
        print("❌ API_ID must be an integer.")
        return

    print()
    print("Connecting to Telegram...")
    print("You will receive a verification code on your Telegram account.")
    print()

    async with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        session_string = client.session.save()

    print()
    print("=" * 55)
    print("✅  SESSION_STRING generated successfully!")
    print("=" * 55)
    print()
    print("Copy the string below in its entirety (single line):")
    print()
    print(session_string)
    print()
    print("=" * 55)
    print("Next step:")
    print("  GitHub → Settings → Secrets → Actions")
    print("  → New secret: TELEGRAM_SESSION_STRING")
    print("  → Paste the string above")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
