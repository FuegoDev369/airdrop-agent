"""
setup_discord.py
Script interactif d'aide à la configuration du Discord Tracker.

Ce script :
  1. Génère le lien d'invitation du bot (avec permissions minimales)
  2. Vérifie que le bot peut accéder aux serveurs configurés
  3. Liste les channels disponibles sur chaque serveur

Usage :
    pip install discord.py
    DISCORD_BOT_TOKEN=ton_token python scripts/setup_discord.py
"""

import os
import asyncio
import sys


async def main():
    print("=" * 55)
    print("  AirdropAgent — Setup Discord Tracker")
    print("=" * 55)
    print()

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        token = input("Entre ton DISCORD_BOT_TOKEN : ").strip()

    if not token:
        print("❌ Token manquant.")
        return

    try:
        import discord
    except ImportError:
        print("❌ discord.py manquant. Lance : pip install discord.py")
        return

    # Extraire le client_id depuis le token pour générer le lien d'invitation
    try:
        import base64
        client_id = base64.b64decode(token.split(".")[0] + "==").decode("utf-8")
        invite_url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={client_id}"
            f"&permissions=68608"     # READ_MESSAGES + READ_MESSAGE_HISTORY + VIEW_CHANNEL
            f"&scope=bot"
        )
        print(f"🔗 Lien d'invitation du bot (permissions lecture seule) :")
        print(f"   {invite_url}")
        print()
        print("→ Ouvre ce lien dans ton navigateur pour inviter le bot")
        print("  sur les serveurs Discord de tes projets trackés.")
        print()
        input("Appuie sur Entrée quand le bot est invité sur au moins un serveur...")
        print()
    except Exception:
        print("(Impossible de générer le lien automatiquement)")
        print()

    # Connexion et listing des serveurs accessibles
    print("Connexion au bot Discord...")
    results = []

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"✅ Bot connecté : {client.user}")
        print()

        if not client.guilds:
            print("⚠️  Le bot n'est membre d'aucun serveur.")
            print("   Utilise le lien d'invitation ci-dessus pour l'ajouter.")
            await client.close()
            return

        print(f"📋 Serveurs accessibles ({len(client.guilds)}) :")
        print()

        for guild in client.guilds:
            print(f"  🏠 {guild.name}")
            print(f"     Guild ID : {guild.id}  ← à mettre dans discord_guild_id")
            text_channels = [c for c in guild.text_channels]
            print(f"     Channels texte ({len(text_channels)}) :")
            for ch in text_channels[:10]:  # Max 10 channels affichés
                perms = ch.permissions_for(guild.me)
                readable = "✅" if perms.read_messages and perms.read_message_history else "❌"
                print(f"       {readable} #{ch.name}")
            if len(text_channels) > 10:
                print(f"       ... et {len(text_channels) - 10} autres")
            print()
            results.append({"name": guild.name, "id": guild.id})

        await client.close()

    await client.start(token)

    if results:
        print("=" * 55)
        print("Configuration à copier dans config/settings.yaml :")
        print("=" * 55)
        for r in results:
            print(f"""
  - name: "NOM_DU_PROJET"
    discord_guild_id: {r['id']}
    discord_channels:
      - "announcements"
      - "general"
""")


if __name__ == "__main__":
    asyncio.run(main())
