"""
discord_tracker.py — v1.7
Lecture des channels Discord des projets via bot officiel.

Approche : Bot Discord en READ ONLY invité sur les serveurs des projets.
100% conforme aux ToS Discord. Aucun risque de ban.

Prérequis :
  - DISCORD_BOT_TOKEN dans GitHub Secrets
  - Le bot invité sur les serveurs des projets trackés
  - channels_to_watch configurés dans settings.yaml par projet

CHANGELOG v1.7 :
  - Implémentation initiale discord.py read-only
  - Récupération des N derniers messages par channel configuré
  - Filtrage messages trop courts, bots, et messages système
  - Gestion gracieuse si serveur/channel inaccessible
"""

import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DiscordTracker:
    """Client Discord asynchrone en lecture seule via bot officiel."""

    def __init__(self):
        self.bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        self.enabled   = bool(self.bot_token)
        self.client    = None

        if not self.enabled:
            logger.info("DiscordTracker désactivé — DISCORD_BOT_TOKEN manquant")

    async def _get_client(self):
        """Initialise le client discord.py."""
        if self.client:
            return self.client
        try:
            import discord

            # Intents minimaux — lecture seule des messages
            intents = discord.Intents.default()
            intents.message_content = True
            intents.guilds           = True

            self.client = discord.Client(intents=intents)
            return self.client
        except ImportError:
            raise ImportError(
                "Package 'discord.py' manquant. Lance : pip install discord.py"
            )

    async def get_channel_messages(
        self,
        guild_id: int,
        channel_names: list,
        limit: int = 20
    ) -> list:
        """
        Récupère les derniers messages de channels spécifiques d'un serveur.

        Args:
            guild_id      : ID numérique du serveur Discord
            channel_names : liste de noms de channels à lire
                            ex: ["announcements", "general", "alpha"]
            limit         : nombre max de messages par channel

        Returns:
            liste de dicts {content, channel, author, date, source}
        """
        if not self.enabled:
            return []

        messages = []

        try:
            import discord

            intents = discord.Intents.default()
            intents.message_content = True

            # Client temporaire pour une seule requête
            client = discord.Client(intents=intents)
            collected = []

            @client.event
            async def on_ready():
                try:
                    guild = client.get_guild(guild_id)
                    if not guild:
                        logger.warning(f"Discord : serveur {guild_id} introuvable ou bot non invité")
                        await client.close()
                        return

                    logger.info(f"Discord connecté : serveur '{guild.name}'")

                    for channel in guild.text_channels:
                        # Filtrer uniquement les channels configurés
                        if channel_names and channel.name not in channel_names:
                            continue

                        try:
                            async for msg in channel.history(limit=limit):
                                # Ignorer les bots et messages système
                                if msg.author.bot:
                                    continue
                                if not msg.content or len(msg.content.strip()) < 15:
                                    continue

                                collected.append({
                                    "content": msg.content.strip(),
                                    "channel": channel.name,
                                    "author":  str(msg.author),
                                    "date":    str(msg.created_at),
                                    "url":     msg.jump_url,
                                    "source":  "discord",
                                })
                        except discord.Forbidden:
                            logger.debug(f"Discord : channel #{channel.name} inaccessible (permissions)")
                        except Exception as e:
                            logger.debug(f"Discord : erreur channel #{channel.name} : {e}")

                finally:
                    await client.close()

            await client.start(self.bot_token)
            messages = collected
            logger.info(f"Discord serveur {guild_id} : {len(messages)} messages récupérés")

        except ImportError:
            raise
        except Exception as e:
            logger.warning(f"Discord tracker : {e}")

        return messages

    async def get_messages_by_invite(
        self,
        guild_id: int,
        channel_names: list,
        limit: int = 20
    ) -> list:
        """Alias de get_channel_messages pour clarté."""
        return await self.get_channel_messages(guild_id, channel_names, limit)


class DiscordTrackerSync:
    """
    Wrapper synchrone pour DiscordTracker.
    Utilisé par agent.py qui n'est pas async.
    """

    def __init__(self):
        self._tracker = DiscordTracker()
        self._loop    = None

    @property
    def enabled(self) -> bool:
        return self._tracker.enabled

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def get_messages(
        self,
        guild_id: int,
        channel_names: list,
        limit: int = 20
    ) -> list:
        """Interface synchrone pour get_channel_messages."""
        if not self._tracker.enabled:
            return []
        if not guild_id:
            return []
        try:
            loop = self._get_loop()
            return loop.run_until_complete(
                self._tracker.get_channel_messages(guild_id, channel_names, limit)
            )
        except Exception as e:
            logger.warning(f"DiscordTrackerSync : {e}")
            return []

    def close(self):
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.close()
            except Exception:
                pass
