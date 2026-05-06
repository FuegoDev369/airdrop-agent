"""
telegram_tracker.py — v1.9
Read Telegram project channels via Telethon official API.

CHANGELOG v1.9:
  - Full translation to English (comments, logs, docstrings)
  - No functional changes from v1.6
"""

import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramTracker:
    """Async Telegram client based on Telethon + StringSession."""

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
            logger.info(f"TelegramTracker disabled — missing: {', '.join(missing)}")

    async def _connect(self):
        """Initialize and connect the Telethon client."""
        if self.client and self.client.is_connected():
            return

        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            self.client = TelegramClient(
                StringSession(self.session_str),
                int(self.api_id),
                self.api_hash,
                request_retries=3,
                connection_retries=3,
                retry_delay=2,
            )
            await self.client.connect()

            if not await self.client.is_user_authorized():
                raise RuntimeError(
                    "Telegram session not authorized. "
                    "Regenerate SESSION_STRING with: python scripts/generate_session.py"
                )

            me = await self.client.get_me()
            logger.info(f"Telegram connected: @{me.username or me.first_name}")

        except ImportError:
            raise ImportError("Package 'telethon' missing. Run: pip install telethon")

    async def get_channel_messages(self, handle: str, limit: int = 20) -> list:
        """
        Fetch the latest text messages from a Telegram channel or group.

        Args:
            handle : username without @ (e.g. "monadxyz") or invite link
            limit  : max number of messages to fetch

        Returns:
            list of dicts {content, date, message_id, views, url, source}
        """
        if not self.enabled:
            return []

        try:
            await self._connect()
            messages = []

            async for msg in self.client.iter_messages(handle, limit=limit):
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

            logger.info(f"Telegram @{handle}: {len(messages)} messages fetched")
            return messages

        except Exception as e:
            err = str(e)
            if "USERNAME_NOT_OCCUPIED" in err or "Cannot find any entity" in err:
                logger.warning(f"Telegram @{handle}: channel not found or private")
            elif "FLOOD_WAIT" in err:
                logger.warning(f"Telegram @{handle}: flood wait — retry later")
            else:
                logger.warning(f"Telegram @{handle}: {e}")
            return []

    async def disconnect(self):
        """Cleanly close the Telegram connection."""
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            logger.debug("Telegram disconnected")


class TelegramTrackerSync:
    """
    Synchronous wrapper for TelegramTracker.
    Used by agent.py which is not async.
    Creates its own isolated event loop.
    """

    def __init__(self):
        self._tracker = TelegramTracker()
        self._loop    = None

    @property
    def enabled(self) -> bool:
        return self._tracker.enabled

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def get_messages(self, handle: str, limit: int = 20) -> list:
        """Synchronous interface for get_channel_messages."""
        if not self._tracker.enabled or not handle:
            return []
        try:
            loop = self._get_loop()
            return loop.run_until_complete(
                self._tracker.get_channel_messages(handle.strip(), limit)
            )
        except Exception as e:
            logger.warning(f"TelegramTrackerSync — @{handle}: {e}")
            return []

    def close(self):
        """Cleanly close connection and event loop."""
        if self._tracker.enabled and self._loop and not self._loop.is_closed():
            try:
                self._loop.run_until_complete(self._tracker.disconnect())
                self._loop.close()
            except Exception:
                pass
