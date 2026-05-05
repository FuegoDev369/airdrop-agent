"""
content_engine.py — v1.2
Moteur de génération de contenu.

CHANGELOG v1.2 :
  - Tweets TOUJOURS générés en anglais (tweet_language: "en")
  - Notifications/actions en langue configurable (notification_language)
  - 1 seul tweet par projet par run (plus propre, moins de 429)
  - Contexte Discord en langue configurable
"""

import logging
from typing import Optional
from core.llm_engine import LLMEngine

logger = logging.getLogger(__name__)


class ContentEngine:
    def __init__(self, llm: LLMEngine, config: dict):
        self.llm = llm
        self.cfg = config.get("scoring", {}).get("content_generation", {})

        # Langue des tweets — toujours anglais, non négociable
        self.tweet_language = "en"

        # Langue des notifications/actions — configurable
        lang_cfg = config.get("language", {})
        self.notification_language = lang_cfg.get("notification_language", "en")

        logger.debug(
            f"ContentEngine — tweets: {self.tweet_language} | "
            f"notifications: {self.notification_language}"
        )

    def build_project_context(self, project: dict, signals: list) -> str:
        """Construit le contexte d'un projet à partir de ses signaux récents."""
        if not signals:
            return f"Project: {project['name']} — no recent signals available."

        top_signals = sorted(
            signals, key=lambda s: s.get("urgency_score", 0), reverse=True
        )[:5]

        lines = [f"Project: {project['name']} ({project.get('chain', 'blockchain')})"]
        lines.append("Recent signals:")
        for s in top_signals:
            src = s.get("source", "?").upper()
            content = s.get("content", "")[:200]
            lines.append(f"  [{src}] {content}")
        return "\n".join(lines)

    def generate_tweet(self, project: dict, signals: list) -> Optional[str]:
        """
        Génère UN tweet en anglais pour un projet.
        Les tweets sont TOUJOURS en anglais — langue de la crypto sur Twitter/X.
        Retourne le texte du tweet ou None si échec.
        """
        context = self.build_project_context(project, signals)
        try:
            tweet = self.llm.generate_tweet(
                project_name=project["name"],
                context=context,
                language="en",   # Forcé anglais — pas configurable
            )
            if tweet and len(tweet.strip()) > 10:
                logger.info(f"Tweet EN généré pour {project['name']}")
                return tweet.strip()
        except Exception as e:
            logger.warning(f"Erreur génération tweet {project['name']} : {e}")
        return None

    # Alias pour compatibilité avec agent.py
    def generate_tweets(self, project: dict, signals: list) -> list:
        """Wrapper retournant une liste pour compatibilité avec agent.py."""
        tweet = self.generate_tweet(project, signals)
        if tweet:
            return [{"text": tweet, "language": "en", "project": project["name"]}]
        return []

    def generate_discord_action(self, project: dict, quest_signal: dict) -> Optional[str]:
        """
        Génère une suggestion d'action Discord dans la langue configurée.
        """
        lang = self.notification_language
        lang_instruction = "en français" if lang == "fr" else f"in {lang}"

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
                f"Be specific and actionable."
            )
            return self.llm.call(prompt, system)
        except Exception as e:
            logger.warning(f"Erreur génération action Discord : {e}")
            return None

    def generate_action_plan(self, project: dict, signals: list) -> list:
        """
        Génère un plan d'actions priorisées pour un projet.
        Retourne une liste d'actions structurées.
        """
        actions = []
        urgent_signals = [s for s in signals if s.get("urgency_score", 0) >= 7]

        for signal in urgent_signals[:3]:
            signal_type = signal.get("signal_type", "")
            action_required = signal.get("action_required")

            if signal_type == "quest":
                actions.append({
                    "type": "discord_task",
                    "description": action_required or (
                        f"Participer à la quête détectée sur {project['name']}"
                        if self.notification_language == "fr"
                        else f"Participate in the detected quest on {project['name']}"
                    ),
                    "urgency": signal.get("urgency_score", 7),
                    "source_signal": signal.get("id"),
                })
            elif signal_type in ("snapshot", "tge_signal"):
                actions.append({
                    "type": "onchain_tx",
                    "description": (
                        f"URGENT : Snapshot imminent sur {project['name']} — vérifier éligibilité"
                        if self.notification_language == "fr"
                        else f"URGENT: Imminent snapshot on {project['name']} — check eligibility"
                    ),
                    "urgency": 10,
                    "source_signal": signal.get("id"),
                })
            elif action_required:
                actions.append({
                    "type": "general",
                    "description": action_required,
                    "urgency": signal.get("urgency_score", 5),
                    "source_signal": signal.get("id"),
                })

        # 1 tweet EN par projet par run
        if signals:
            actions.append({
                "type": "tweet",
                "description": (
                    f"Poster un tweet d'engagement pour {project['name']}"
                    if self.notification_language == "fr"
                    else f"Post an engagement tweet for {project['name']}"
                ),
                "urgency": 4,
                "source_signal": None,
            })

        return sorted(actions, key=lambda a: a.get("urgency", 0), reverse=True)
