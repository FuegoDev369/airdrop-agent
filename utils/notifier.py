"""
notifier.py
Système de notifications — Discord Webhook + Telegram Bot.
Activé/désactivé via config/settings.yaml sans toucher au code.
"""

import os
import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Couleurs Discord embed par niveau d'urgence
URGENCY_COLORS = {
    "critical": 0xFF0000,   # Rouge
    "high":     0xFF6B00,   # Orange
    "medium":   0xFFD700,   # Jaune
    "low":      0x00C851,   # Vert
    "info":     0x4A90D9,   # Bleu
}

URGENCY_EMOJIS = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🟢",
    "info":     "🔵",
}


def _urgency_level(score: int) -> str:
    if score >= 9:   return "critical"
    if score >= 7:   return "high"
    if score >= 5:   return "medium"
    if score >= 3:   return "low"
    return "info"


class Notifier:
    def __init__(self, config: dict):
        self.cfg = config.get("notifications", {})
        self.discord_cfg = self.cfg.get("discord", {})
        self.telegram_cfg = self.cfg.get("telegram", {})
        self.urgency_threshold = self.cfg.get("urgency_threshold", 7)

        # Credentials depuis variables d'environnement (GitHub Secrets)
        self.discord_webhook = os.environ.get("DISCORD_WEBHOOK")
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    # ── Discord ──────────────────────────────────────────────

    def _send_discord(self, content: str = "", embeds: list = None, mention: bool = False):
        if not self.discord_cfg.get("enabled", False):
            return False
        if not self.discord_webhook:
            logger.warning("DISCORD_WEBHOOK manquant dans les secrets")
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
            logger.info("Notification Discord envoyée")
            return True
        except Exception as e:
            logger.error(f"Erreur Discord : {e}")
            return False

    def _build_signal_embed(self, project_name: str, signal: dict) -> dict:
        score = signal.get("urgency_score", 0)
        level = _urgency_level(score)
        emoji = URGENCY_EMOJIS[level]

        return {
            "title": f"{emoji} {project_name} — {signal.get('signal_type', 'signal').upper()}",
            "description": signal.get("summary", signal.get("content", ""))[:400],
            "color": URGENCY_COLORS[level],
            "fields": [
                {
                    "name": "⚡ Urgence",
                    "value": f"`{score}/10`",
                    "inline": True
                },
                {
                    "name": "📡 Source",
                    "value": signal.get("source", "inconnu").capitalize(),
                    "inline": True
                },
                {
                    "name": "🎯 Action recommandée",
                    "value": signal.get("action_required") or "Surveiller",
                    "inline": False
                },
            ],
            "footer": {"text": f"AirdropAgent • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ── Telegram ─────────────────────────────────────────────

    def _send_telegram(self, text: str):
        if not self.telegram_cfg.get("enabled", False):
            return False
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Notification Telegram envoyée")
            return True
        except Exception as e:
            logger.error(f"Erreur Telegram : {e}")
            return False

    # ── Méthodes publiques ───────────────────────────────────

    def notify_signal(self, project_name: str, signal: dict) -> int:
        """Notifie un signal urgent. Retourne le nombre de canaux notifiés."""
        score = signal.get("urgency_score", 0)
        if score < self.urgency_threshold:
            return 0

        sent = 0
        level = _urgency_level(score)
        is_critical = level in ("critical", "high")

        # Discord
        if self.discord_cfg.get("quest_alerts", True):
            embed = self._build_signal_embed(project_name, signal)
            if self._send_discord(embeds=[embed], mention=is_critical):
                sent += 1

        # Telegram
        if self.telegram_cfg.get("quest_alerts", True):
            emoji = URGENCY_EMOJIS[level]
            text = (
                f"{emoji} <b>{project_name}</b> — {signal.get('signal_type', '').upper()}\n\n"
                f"{signal.get('summary', signal.get('content', ''))[:300]}\n\n"
                f"⚡ Urgence : <b>{score}/10</b>\n"
                f"📡 Source : {signal.get('source', 'inconnu').capitalize()}\n"
                f"🎯 Action : {signal.get('action_required') or 'Surveiller'}"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_daily_brief(self, brief_text: str, actions_count: int) -> int:
        """Envoie le briefing quotidien."""
        sent = 0
        date_str = datetime.utcnow().strftime("%d/%m/%Y")

        # Discord
        if self.discord_cfg.get("daily_brief", True):
            embed = {
                "title": f"📋 Briefing AirdropAgent — {date_str}",
                "description": brief_text[:2000],
                "color": URGENCY_COLORS["info"],
                "fields": [
                    {"name": "🎯 Actions en attente", "value": str(actions_count), "inline": True},
                ],
                "footer": {"text": "AirdropAgent • Briefing Quotidien"},
                "timestamp": datetime.utcnow().isoformat(),
            }
            if self._send_discord(embeds=[embed]):
                sent += 1

        # Telegram
        if self.telegram_cfg.get("daily_brief", True):
            text = (
                f"📋 <b>Briefing AirdropAgent — {date_str}</b>\n\n"
                f"{brief_text[:1500]}\n\n"
                f"🎯 <b>{actions_count} actions en attente</b>"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_tweet_suggestion(self, project_name: str, tweet: str) -> int:
        """Notifie un tweet généré prêt à poster."""
        sent = 0

        # Discord
        if self.discord_cfg.get("action_suggestions", True):
            embed = {
                "title": f"🐦 Tweet suggéré — {project_name}",
                "description": f"```\n{tweet}\n```",
                "color": URGENCY_COLORS["medium"],
                "footer": {"text": "Copie et poste sur Twitter/X"},
                "timestamp": datetime.utcnow().isoformat(),
            }
            if self._send_discord(embeds=[embed]):
                sent += 1

        # Telegram
        if self.telegram_cfg.get("action_suggestions", True):
            text = (
                f"🐦 <b>Tweet suggéré — {project_name}</b>\n\n"
                f"<code>{tweet}</code>\n\n"
                f"📋 Copie et poste sur Twitter/X"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_snapshot_alert(self, project_name: str, details: str, days_estimate: Optional[int] = None) -> int:
        """Alerte snapshot/TGE imminent — priorité maximale."""
        sent = 0
        days_str = f"~{days_estimate} jours" if days_estimate else "imminent"

        # Discord
        if self.discord_cfg.get("enabled", False):
            embed = {
                "title": f"⚠️ SNAPSHOT DÉTECTÉ — {project_name}",
                "description": f"**Snapshot estimé : {days_str}**\n\n{details[:400]}",
                "color": URGENCY_COLORS["critical"],
                "footer": {"text": "AirdropAgent • Alerte Snapshot"},
                "timestamp": datetime.utcnow().isoformat(),
            }
            if self._send_discord(embeds=[embed], mention=True):
                sent += 1

        # Telegram
        if self.telegram_cfg.get("snapshot_alerts", True):
            text = (
                f"⚠️ <b>SNAPSHOT DÉTECTÉ — {project_name}</b>\n\n"
                f"📅 Estimé : <b>{days_str}</b>\n\n"
                f"{details[:500]}"
            )
            if self._send_telegram(text):
                sent += 1

        return sent

    def notify_run_summary(self, stats: dict) -> int:
        """Résumé de fin de run — envoyé uniquement si activé."""
        sent = 0
        status_emoji = "✅" if stats.get("status") == "success" else "❌"

        text = (
            f"{status_emoji} <b>Run AirdropAgent terminé</b>\n\n"
            f"📡 Signaux collectés : {stats.get('signals_collected', 0)}\n"
            f"🎯 Actions générées : {stats.get('actions_generated', 0)}\n"
            f"🔔 Notifications envoyées : {stats.get('notifications_sent', 0)}\n"
            f"⏱️ Prochain run : dans ~{stats.get('next_run_hours', 2)}h"
        )

        if self._send_telegram(text):
            sent += 1

        return sent
