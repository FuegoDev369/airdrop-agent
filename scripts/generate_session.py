"""
generate_session.py
Script ONE-SHOT pour générer le TELEGRAM_SESSION_STRING.

À lancer UNE SEULE FOIS depuis Termux (ou n'importe quel terminal).
Le SESSION_STRING généré est ensuite ajouté dans GitHub Secrets.
Il ne expire jamais tant que tu ne te déconnectes pas manuellement.

Usage :
    pip install telethon
    python scripts/generate_session.py
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    print("=" * 55)
    print("  AirdropAgent — Génération SESSION_STRING Telegram")
    print("=" * 55)
    print()
    print("Tu as besoin de API_ID et API_HASH depuis my.telegram.org")
    print("(voir guide README section Telegram Tracker)")
    print()

    api_id   = input("Entre ton API_ID   : ").strip()
    api_hash = input("Entre ton API_HASH : ").strip()

    if not api_id.isdigit():
        print("❌ API_ID doit être un nombre entier.")
        return

    print()
    print("Connexion à Telegram...")
    print("Tu vas recevoir un code de vérification sur ton compte Telegram.")
    print()

    async with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        session_string = client.session.save()

    print()
    print("=" * 55)
    print("✅  SESSION_STRING généré avec succès !")
    print("=" * 55)
    print()
    print("Copie la chaîne ci-dessous en entier (1 seule ligne) :")
    print()
    print(session_string)
    print()
    print("=" * 55)
    print("Étape suivante :")
    print("  GitHub → Settings → Secrets → Actions")
    print("  → New secret : TELEGRAM_SESSION_STRING")
    print("  → Colle la chaîne ci-dessus")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
