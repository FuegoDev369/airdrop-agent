"""
telegram_tracker.py
Lecture des canaux Telegram des projets via Telethon.
Utilise l'API officielle Telegram (gratuite).
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramTracker:
    def __init__(self, config: dict):
        self.api_id = os.environ.get("TELEGRAM_API_ID")
        self.api_hash = os.environ.get("TELEGRAM_API_HASH")
        self.client = None
        self.enabled = bool(self.api_id and self.api_hash)

        if not self.enabled:
            logger.info("TelegramTracker désactivé (TELEGRAM_API_ID/HASH manquants)")

    async def _get_client(self):
        """Initialise le client Telethon à la demande."""
        if self.client:
            return self.client
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            session_str = os.environ.get("TELEGRAM_SESSION_STRING", "")
            self.client = TelegramClient(
                StringSession(session_str),
                int(self.api_id),
                self.api_hash
            )
            await self.client.start()
            logger.info("Client Telethon connecté")
            return self.client
        except ImportError:
            raise ImportError("Package 'telethon' manquant. Lance : pip install telethon")

    async def get_channel_messages(self, channel_handle: str, limit: int = 20) -> list:
        """Récupère les derniers messages d'un canal/groupe Telegram."""
        if not self.enabled:
            return []

        try:
            client = await self._get_client()
            messages = []

            async for msg in client.iter_messages(channel_handle, limit=limit):
                if not msg.text:
                    continue
                messages.append({
                    "content": msg.text,
                    "date": str(msg.date),
                    "message_id": msg.id,
                    "views": getattr(msg, "views", 0),
                    "source": "telegram",
                })

            logger.info(f"Telegram @{channel_handle} : {len(messages)} messages récupérés")
            return messages

        except Exception as e:
            logger.warning(f"Erreur Telegram @{channel_handle} : {e}")
            return []

    async def close(self):
        if self.client:
            await self.client.disconnect()


class TelegramTrackerSync:
    """
    Wrapper synchrone pour TelegramTracker.
    Utilisé par l'agent principal qui n'est pas async.
    """
    def __init__(self, config: dict):
        import asyncio
        self.config = config
        self.loop = asyncio.new_event_loop()
        self._tracker = TelegramTracker(config)

    def get_messages(self, handle: str, limit: int = 20) -> list:
        if not self._tracker.enabled:
            return []
        try:
            return self.loop.run_until_complete(
                self._tracker.get_channel_messages(handle, limit)
            )
        except Exception as e:
            logger.warning(f"Erreur sync Telegram : {e}")
            return []

    def close(self):
        try:
            self.loop.run_until_complete(self._tracker.close())
            self.loop.close()
        except Exception:
            pass
