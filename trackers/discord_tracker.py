"""
discord_tracker.py — v1.9.1
Read Discord project channels via direct HTTP REST API.

Approach: HTTP requests to Discord API using your user token.
Read-only, low frequency (every 2h) — minimal risk.
No external Discord library required — uses only requests.

Prerequisites:
  - DISCORD_USER_TOKEN in GitHub Secrets
    (your Discord account token — see README Step 6)
  - discord_guild_id and discord_channels configured in settings.yaml

Security note:
  Using a personal user token with the Discord API is technically
  outside Discord's ToS for automated use. Risk is low given
  read-only access at low frequency, but use at your own discretion.
  See README for the full risk assessment.

CHANGELOG v1.9.1:
  - Full translation to English (comments, docstrings, strings)
  - No functional changes from v1.7.1
"""

import os
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


class DiscordTracker:
    """Read Discord channels via HTTP REST API — user token, read-only."""

    def __init__(self):
        self.token   = os.environ.get("DISCORD_USER_TOKEN", "").strip()
        self.enabled = bool(self.token)

        if not self.enabled:
            logger.info("DiscordTracker disabled — DISCORD_USER_TOKEN missing")
            return

        # Headers mimicking the Discord web app
        self.headers = {
            "Authorization": self.token,
            "Content-Type":  "application/json",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "X-Discord-Locale": "en-US",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """GET request on the Discord API with rate limit handling."""
        url = f"{DISCORD_API}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=15)

            # Rate limit — wait and retry once
            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 5)
                logger.warning(f"Discord rate limit — waiting {retry_after}s")
                time.sleep(retry_after + 1)
                resp = self.session.get(url, params=params, timeout=15)

            if resp.status_code == 401:
                logger.error("Discord: invalid or expired token")
                return None
            if resp.status_code == 403:
                logger.debug(f"Discord: access denied on {endpoint}")
                return None
            if resp.status_code == 404:
                logger.debug(f"Discord: resource not found {endpoint}")
                return None

            resp.raise_for_status()
            return resp.json()

        except requests.RequestException as e:
            logger.warning(f"Discord API: {e}")
            return None

    def get_guild_channels(self, guild_id: int) -> list:
        """List all text channels in a Discord server."""
        data = self._get(f"/guilds/{guild_id}/channels")
        if not data:
            return []
        # Filter text channels only (type 0)
        return [ch for ch in data if ch.get("type") == 0]

    def get_channel_messages(self, channel_id: int, limit: int = 20) -> list:
        """Fetch the latest messages from a channel."""
        data = self._get(
            f"/channels/{channel_id}/messages",
            params={"limit": min(limit, 100)}
        )
        return data if data else []

    def get_messages(
        self,
        guild_id: int,
        channel_names: list,
        limit: int = 20,
    ) -> list:
        """
        Fetch messages from configured channels of a Discord server.

        Args:
            guild_id      : numeric Discord server ID
            channel_names : names of channels to monitor
            limit         : max messages per channel

        Returns:
            list of dicts {content, channel, author, date, url, source}
        """
        if not self.enabled:
            return []

        # 1. List server channels
        all_channels = self.get_guild_channels(guild_id)
        if not all_channels:
            logger.warning(f"Discord: no accessible channels on server {guild_id}")
            return []

        # 2. Filter by configured names
        if channel_names:
            target_channels = [
                ch for ch in all_channels
                if ch.get("name") in channel_names
            ]
        else:
            target_channels = all_channels[:3]

        if not target_channels:
            available = [ch.get("name") for ch in all_channels[:10]]
            logger.warning(
                f"Discord: channels {channel_names} not found on server {guild_id}. "
                f"Available: {available}"
            )
            return []

        # 3. Fetch messages from each target channel
        all_messages = []
        for channel in target_channels:
            ch_id   = channel["id"]
            ch_name = channel["name"]

            raw = self.get_channel_messages(int(ch_id), limit)
            time.sleep(0.5)  # Delay between channels to avoid rate limiting

            for msg in raw:
                content = msg.get("content", "").strip()
                if not content or len(content) < 15:
                    continue
                if msg.get("author", {}).get("bot", False):
                    continue

                author = msg.get("author", {})
                all_messages.append({
                    "content": content,
                    "channel": ch_name,
                    "author":  author.get("username", "unknown"),
                    "date":    msg.get("timestamp", ""),
                    "url":     f"https://discord.com/channels/{guild_id}/{ch_id}/{msg['id']}",
                    "source":  "discord",
                })

        logger.info(
            f"Discord server {guild_id}: {len(all_messages)} messages "
            f"from {len(target_channels)} channel(s)"
        )
        return all_messages


class DiscordTrackerSync:
    """
    Synchronous interface — no async needed with the HTTP REST API.
    Drop-in replacement for the previous discord.py-based implementation.
    """

    def __init__(self):
        self._tracker = DiscordTracker()

    @property
    def enabled(self) -> bool:
        return self._tracker.enabled

    def get_messages(
        self,
        guild_id: int,
        channel_names: list,
        limit: int = 20,
    ) -> list:
        """Direct synchronous call — HTTP API is natively synchronous."""
        if not self._tracker.enabled or not guild_id:
            return []
        try:
            return self._tracker.get_messages(guild_id, channel_names, limit)
        except Exception as e:
            logger.warning(f"DiscordTrackerSync: {e}")
            return []

    def close(self):
        """Close the HTTP session."""
        try:
            if self._tracker.enabled and self._tracker.session:
                self._tracker.session.close()
        except Exception:
            pass
