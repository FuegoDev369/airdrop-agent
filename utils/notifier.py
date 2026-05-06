"""
notifier.py — v1.9
Notification system — Discord Webhook + Telegram Bot.
Enabled/disabled via config/settings.yaml without touching code.

CHANGELOG v1.9:
  - Full translation to English (comments, logs, docstrings)
  - No functional changes
"""

import os
import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Discord embed colors by urgency level
URGENCY_COLORS = {
    "critical": 0xFF0000,
    "high":     0xFF6B00,
    "medium":   0xFFD700,
    "low":      0x00C851,
    "info":     0x4A90D9,
}

URGENCY_EMOJIS = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🟢",
    "info":     "🔵",
}


def _urgency_level(score: int) -> str:
    if score >= 9:  return "critical"
    if score >= 7:  return "high"
    if score >= 5:  return "medium"
    if score >= 3:  return "low"
    return "info"


class Notifier:
    def __init__(self, config: dict):
        self.cfg          = config.get("notifications", {})
        self.discord_cfg  = self.cfg.get("discord", {})
        self.telegram_cfg = self.cfg.get("telegram", {})
        self.urgency_threshold = self.cfg.get("urgency_threshold", 7)

        # Credentials from environment variables (GitHub Secrets)
        self.discord_webhook  = os.environ.get("DISCORD_WEBHOOK")
        self.telegram_token   = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    # ── Discord ──────────────────────────────────────────────

    def _send_discord(self, content: str = "", embeds: list = None, mention: bool = False) -> bool:
        if not self.discord_cfg.get("enabled", False):
            return False
        if not self.discord_webhook:
            logger.warning("DISCORD_WEBHOOK missing from environment")
            return False

        payload = {}
        if mention and self.discord_cfg.get("mention_on_urgent", False):
            payload["content"] = f"@everyone {content}" if content else "@everyone"
        elif content:
            payload["content"] = content

        if embeds:
            payload["embeds"] = embeds

        try:
            resp = requests.post(self.discord_webhook, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Discord notification sent")
            return True
        except Exception as e:
            logger.error(f"Discord error: {e}")
            return False

    def _build_signal_embed(self, project_name: str, signal: dict) -> dict:
        score  = signal.get("urgency_score", 0)
        level  = _urgency_level(score)
        emoji  = URGENCY_EMOJIS[level]

        return {
            "title":       f"{emoji} {project_name} — {signal.get('signal_type', 'signal').upper()}",
            "description": signal.get("summary", signal.get("content", ""))[:400],
            "color":       URGENCY_COLORS[level],
            "fields": [
                {"name": "⚡ Urgency",    "value": f"`{score}/10`",                                  "inline": True},
                {"name": "📡 Source",     "value": signal.get("source", "unknown").capitalize(),     "inline": True},
                {"name": "🎯 Action",     "value": signal.get("action_required") or "Monitor",       "inline": False},
            ],
            "footer":    {"text": f"AirdropAgent • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Telegram ─────────────────────────────────────────────

    def _send_telegram(self, text: str) -> bool:
        if not self.telegram_cfg.get("enabled", False):
            return False
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
            return False

        url     = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id":                  self.telegram_chat_id,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Telegram notification sent")
            return True
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False

    # ── Public notification methods ──────────────────────────

    def notify_signal(self, project_name: str, signal: dict) -> int:
        """Notify an urgent signal. Returns number of channels notified."""
        score = signal.get("urgency_score", 0)
        if score < self.urgency_threshold:
            return 0

        sent       = 0
        level      = _urgency_level(score)
        is_critical = level in ("critical", "high")

        if self.discord_cfg.get("quest_alerts", True):
            embed = self._build_signal_embed(project_name, signal)
            if self._send_discord(embeds=[embed], mention=is_critical):
                sent += 1

        if self.telegram_cfg.get("quest_alerts", True):
            emoji = URGENCY_EMOJIS[level]
            text  = (
                f"{emoji} <b>{project_name}</b> — {signal.get('signal_type', '').upper()}\n\n"
                f"{signal.get('summary', signal.get('content', ''))[:300]}\n\n"
                f"⚡ Urgency: <b>{score}/10</b>\n"
                f"📡 Source: {signal.get('source', 'unknown').capitalize()}\n"
                f"🎯 Action: {signal.get('action_required') or 'Monitor'}"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_daily_brief(self, brief_text: str, actions_count: int) -> int:
        """Send the daily briefing. Returns number of channels notified."""
        sent     = 0
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

        if self.discord_cfg.get("daily_brief", True):
            embed = {
                "title":       f"📋 AirdropAgent Daily Brief — {date_str}",
                "description": brief_text[:2000],
                "color":       URGENCY_COLORS["info"],
                "fields":      [{"name": "🎯 Pending actions", "value": str(actions_count), "inline": True}],
                "footer":      {"text": "AirdropAgent • Daily Briefing"},
                "timestamp":   datetime.utcnow().isoformat(),
            }
            if self._send_discord(embeds=[embed]):
                sent += 1

        if self.telegram_cfg.get("daily_brief", True):
            text = (
                f"📋 <b>AirdropAgent Daily Brief — {date_str}</b>\n\n"
                f"{brief_text[:1500]}\n\n"
                f"🎯 <b>{actions_count} pending action(s)</b>"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_tweet_suggestion(self, project_name: str, tweet: str) -> int:
        """Notify a generated tweet ready to post."""
        sent = 0

        if self.discord_cfg.get("action_suggestions", True):
            embed = {
                "title":       f"🐦 Tweet suggestion — {project_name}",
                "description": f"```\n{tweet}\n```",
                "color":       URGENCY_COLORS["medium"],
                "footer":      {"text": "Copy and post on Twitter/X"},
                "timestamp":   datetime.utcnow().isoformat(),
            }
            if self._send_discord(embeds=[embed]):
                sent += 1

        if self.telegram_cfg.get("action_suggestions", True):
            text = (
                f"🐦 <b>Tweet suggestion — {project_name}</b>\n\n"
                f"<code>{tweet}</code>\n\n"
                f"📋 Copy and post on Twitter/X"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_snapshot_alert(
        self,
        project_name: str,
        details: str,
        days_estimate: Optional[int] = None,
    ) -> int:
        """Critical snapshot/TGE imminent alert."""
        sent     = 0
        days_str = f"~{days_estimate} days" if days_estimate else "imminent"

        if self.discord_cfg.get("enabled", False):
            embed = {
                "title":       f"⚠️ SNAPSHOT DETECTED — {project_name}",
                "description": f"**Estimated snapshot: {days_str}**\n\n{details[:400]}",
                "color":       URGENCY_COLORS["critical"],
                "footer":      {"text": "AirdropAgent • Snapshot Alert"},
                "timestamp":   datetime.utcnow().isoformat(),
            }
            if self._send_discord(embeds=[embed], mention=True):
                sent += 1

        if self.telegram_cfg.get("snapshot_alerts", True):
            text = (
                f"⚠️ <b>SNAPSHOT DETECTED — {project_name}</b>\n\n"
                f"📅 Estimated: <b>{days_str}</b>\n\n"
                f"{details[:500]}"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_run_summary(self, stats: dict) -> int:
        """Send end-of-run summary."""
        sent         = 0
        status_emoji = "✅" if stats.get("status") == "success" else "❌"

        text = (
            f"{status_emoji} <b>AirdropAgent run completed</b>\n\n"
            f"📡 Signals collected: {stats.get('signals_collected', 0)}\n"
            f"🎯 Actions generated: {stats.get('actions_generated', 0)}\n"
            f"🔔 Notifications sent: {stats.get('notifications_sent', 0)}\n"
            f"⏱️ Next run: in ~{stats.get('next_run_hours', 2)}h"
        )

        if self._send_telegram(text):
            sent += 1

        return sent
