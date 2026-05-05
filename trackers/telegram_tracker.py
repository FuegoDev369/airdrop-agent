"""
telegram_tracker.py — v1.6
Lecture des canaux/groupes Telegram des projets via Telethon.

CHANGELOG v1.6 :
  - Gestion robuste du SESSION_STRING (connexion sans interaction humaine)
  - Timeout et retry sur les canaux inaccessibles
  - Filtrage des messages trop courts ou non-texte
  - TelegramTrackerSync : wrapper synchrone propre pour agent.py
  - Désactivation gracieuse si credentials manquants
"""

import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramTracker:
    """Client Telegram asynchrone basé sur Telethon + StringSession."""

    def __init__(self):
        self.api_id      = os.environ.get("TELEGRAM_API_ID", "").strip()
        self.api_hash    = os.environ.get("TELEGRAM_API_HASH", "").strip()
        self.session_str = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
        self.client      = None

        self.enabled = bool(self.api_id and self.api_hash and self.session_str)

        if not self.enabled:
            missing = []
            if not self.api_id:      missing.append("TELEGRAM_API_ID")
            if not self.api_hash:    missing.append("TELEGRAM_API_HASH")
            if not self.session_str: missing.append("TELEGRAM_SESSION_STRING")
            logger.info(f"TelegramTracker désactivé — manquants : {', '.join(missing)}")

    async def _connect(self):
        """Initialise et connecte le client Telethon."""
        if self.client and self.client.is_connected():
            return

        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            self.client = TelegramClient(
                StringSession(self.session_str),
                int(self.api_id),
                self.api_hash,
                # Paramètres pour environnement headless (GitHub Actions)
                request_retries=3,
                connection_retries=3,
                retry_delay=2,
            )
            await self.client.connect()

            if not await self.client.is_user_authorized():
                raise RuntimeError(
                    "Session Telegram non autorisée. "
                    "Régénère le SESSION_STRING avec scripts/generate_session.py"
                )

            me = await self.client.get_me()
            logger.info(f"Telegram connecté : @{me.username or me.first_name}")

        except ImportError:
            raise ImportError("Package 'telethon' manquant. Lance : pip install telethon")

    async def get_channel_messages(self, handle: str, limit: int = 20) -> list:
        """
        Récupère les derniers messages texte d'un canal ou groupe Telegram.

        Args:
            handle : username sans @ (ex: "monadxyz") ou lien invite
            limit  : nombre max de messages à récupérer

        Returns:
            liste de dicts {content, date, message_id, views, source}
        """
        if not self.enabled:
            return []

        try:
            await self._connect()
            messages = []

            async for msg in self.client.iter_messages(handle, limit=limit):
                # Ignorer les messages sans texte
                if not msg.text or len(msg.text.strip()) < 15:
                    continue

                messages.append({
                    "content":    msg.text.strip(),
                    "date":       str(msg.date),
                    "message_id": msg.id,
                    "views":      getattr(msg, "views", 0) or 0,
                    "source":     "telegram",
                    "url":        f"https://t.me/{handle}/{msg.id}",
                })

            logger.info(f"Telegram @{handle} : {len(messages)} messages récupérés")
            return messages

        except Exception as e:
            err = str(e)
            if "USERNAME_NOT_OCCUPIED" in err or "Cannot find any entity" in err:
                logger.warning(f"Telegram @{handle} : canal introuvable ou privé")
            elif "FLOOD_WAIT" in err:
                logger.warning(f"Telegram @{handle} : flood wait — réessayer plus tard")
            else:
                logger.warning(f"Telegram @{handle} : {e}")
            return []

    async def disconnect(self):
        """Ferme proprement la connexion."""
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            logger.debug("Telegram déconnecté")


class TelegramTrackerSync:
    """
    Wrapper synchrone pour TelegramTracker.
    Utilisé par agent.py qui n'est pas async.
    Crée sa propre event loop isolée.
    """

    def __init__(self, config: dict = None):
        self._tracker = TelegramTracker()
        self._loop    = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    @property
    def enabled(self) -> bool:
        return self._tracker.enabled

    def get_messages(self, handle: str, limit: int = 20) -> list:
        """Interface synchrone pour get_channel_messages."""
        if not self._tracker.enabled:
            return []

        if not handle or not handle.strip():
            return []

        try:
            loop = self._get_loop()
            return loop.run_until_complete(
                self._tracker.get_channel_messages(handle.strip(), limit)
            )
        except Exception as e:
            logger.warning(f"TelegramTrackerSync — @{handle} : {e}")
            return []

    def close(self):
        """Ferme proprement la connexion et l'event loop."""
        if self._tracker.enabled and self._loop and not self._loop.is_closed():
            try:
                self._loop.run_until_complete(self._tracker.disconnect())
                self._loop.close()
            except Exception:
                pass
