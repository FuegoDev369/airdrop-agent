"""
content_engine.py — v1.9
Content generation engine — tweets, Discord action suggestions,
community messages. Based on each project's recent signal context.

CHANGELOG v1.9:
  - Full translation to English (comments, logs, docstrings)
  - Tweets always generated in English (tweet_language: "en")
  - Notifications/actions in configurable language (notification_language)
"""

import logging
from typing import Optional
from core.llm_engine import LLMEngine

logger = logging.getLogger(__name__)


class ContentEngine:
    def __init__(self, llm: LLMEngine, config: dict):
        self.llm = llm
        self.cfg = config.get("scoring", {}).get("content_generation", {})

        # Tweet language — always English, not configurable
        self.tweet_language = "en"

        # Notification/action language — configurable
        lang_cfg = config.get("language", {})
        self.notification_language = lang_cfg.get("notification_language", "en")

        logger.debug(
            f"ContentEngine — tweets: {self.tweet_language} | "
            f"notifications: {self.notification_language}"
        )

    def build_project_context(self, project: dict, signals: list) -> str:
        """Build project context string from recent signals for LLM prompting."""
        if not signals:
            return f"Project: {project['name']} — no recent signals available."

        top_signals = sorted(
            signals, key=lambda s: s.get("urgency_score", 0), reverse=True
        )[:5]

        lines = [f"Project: {project['name']} ({project.get('chain', 'blockchain')})"]
        lines.append("Recent signals:")
        for s in top_signals:
            src     = s.get("source", "?").upper()
            content = s.get("content", "")[:200]
            lines.append(f"  [{src}] {content}")
        return "\n".join(lines)

    def generate_tweet(self, project: dict, signals: list) -> Optional[str]:
        """
        Generate a single English tweet for a project.
        Tweets are ALWAYS in English — the standard language of crypto on Twitter/X.
        Returns the tweet text or None on failure.
        """
        context = self.build_project_context(project, signals)
        try:
            tweet = self.llm.generate_tweet(
                project_name=project["name"],
                context=context,
                language="en",  # Forced English — not configurable
            )
            if tweet and len(tweet.strip()) > 10:
                logger.info(f"Tweet generated for {project['name']}")
                return tweet.strip()
        except Exception as e:
            logger.warning(f"Tweet generation error — {project['name']}: {e}")
        return None

    def generate_tweets(self, project: dict, signals: list) -> list:
        """Wrapper returning a list for compatibility with agent.py."""
        tweet = self.generate_tweet(project, signals)
        if tweet:
            return [{"text": tweet, "language": "en", "project": project["name"]}]
        return []

    def generate_discord_action(self, project: dict, quest_signal: dict) -> Optional[str]:
        """Generate a Discord action suggestion in the configured language."""
        lang             = self.notification_language
        lang_instruction = "in French" if lang == "fr" else f"in English"

        try:
            system = (
                f"You are an airdrop expert guiding users on Discord. "
                f"Give clear, actionable instructions {lang_instruction}. "
                f"Reply only with the instructions, no introduction."
            )
            prompt = (
                f'Project "{project["name"]}" has important Discord activity:\n\n'
                f'Signal: {quest_signal.get("content", "")[:500]}\n\n'
                f"Generate a list of 3-5 concrete steps the user should take "
                f"on the project's Discord to maximize engagement and airdrop chances. "
                f"Be specific and actionable. Write {lang_instruction}."
            )
            return self.llm.call(prompt, system)
        except Exception as e:
            logger.warning(f"Discord action generation error: {e}")
            return None

    def generate_action_plan(self, project: dict, signals: list) -> list:
        """
        Generate a prioritized action plan for a project.
        Returns a list of structured action dicts.
        """
        actions       = []
        urgent_signals = [s for s in signals if s.get("urgency_score", 0) >= 7]

        for signal in urgent_signals[:3]:
            signal_type     = signal.get("signal_type", "")
            action_required = signal.get("action_required")

            if signal_type == "quest":
                actions.append({
                    "type":         "discord_task",
                    "description":  action_required or f"Participate in the detected quest on {project['name']}",
                    "urgency":      signal.get("urgency_score", 7),
                    "source_signal": signal.get("id"),
                })
            elif signal_type in ("snapshot", "tge_signal"):
                actions.append({
                    "type":         "onchain_tx",
                    "description":  f"URGENT: Imminent snapshot on {project['name']} — verify eligibility now",
                    "urgency":      10,
                    "source_signal": signal.get("id"),
                })
            elif action_required:
                actions.append({
                    "type":         "general",
                    "description":  action_required,
                    "urgency":      signal.get("urgency_score", 5),
                    "source_signal": signal.get("id"),
                })

        # Always add one tweet action per project per run if signals exist
        if signals:
            actions.append({
                "type":         "tweet",
                "description":  f"Post an engagement tweet for {project['name']}",
                "urgency":      4,
                "source_signal": None,
            })

        return sorted(actions, key=lambda a: a.get("urgency", 0), reverse=True)
