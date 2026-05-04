"""
content_engine.py
Moteur de génération de contenu — tweets, suggestions d'actions Discord,
messages communautaires. Basé sur le contexte récent de chaque projet.
"""

import logging
from typing import Optional
from core.llm_engine import LLMEngine

logger = logging.getLogger(__name__)


class ContentEngine:
    def __init__(self, llm: LLMEngine, config: dict):
        self.llm = llm
        self.cfg = config.get("scoring", {}).get("content_generation", {})
        self.tweets_per_project = self.cfg.get("tweets_per_project_per_day", 2)
        self.languages = self.cfg.get("languages", ["fr", "en"])

    def build_project_context(self, project: dict, signals: list) -> str:
        """Construit le contexte d'un projet à partir de ses signaux récents."""
        if not signals:
            return f"Projet {project['name']} — aucun signal récent disponible."

        top_signals = sorted(signals, key=lambda s: s.get("urgency_score", 0), reverse=True)[:5]
        lines = [f"Projet : {project['name']} ({project.get('chain', 'blockchain')})"]
        lines.append("Signaux récents :")
        for s in top_signals:
            src = s.get("source", "?").upper()
            content = s.get("content", "")[:200]
            lines.append(f"  [{src}] {content}")
        return "\n".join(lines)

    def generate_tweets(self, project: dict, signals: list) -> list:
        """
        Génère des tweets pour un projet basés sur son activité récente.
        Retourne une liste de strings (tweets prêts à poster).
        """
        context = self.build_project_context(project, signals)
        tweets = []

        for lang in self.languages[:self.tweets_per_project]:
            try:
                tweet = self.llm.generate_tweet(
                    project_name=project["name"],
                    context=context,
                    language=lang,
                )
                if tweet and len(tweet.strip()) > 10:
                    tweets.append({
                        "text": tweet.strip(),
                        "language": lang,
                        "project": project["name"],
                    })
                    logger.info(f"Tweet généré pour {project['name']} ({lang})")
            except Exception as e:
                logger.warning(f"Erreur génération tweet {project['name']} : {e}")

        return tweets

    def generate_discord_action(self, project: dict, quest_signal: dict) -> Optional[str]:
        """Génère une suggestion d'action Discord basée sur une quête détectée."""
        try:
            system = """Tu es un expert airdrop qui guide les utilisateurs sur Discord.
Tu donnes des instructions claires et actionnables en français.
Tu réponds uniquement avec les instructions, sans introduction."""

            prompt = f"""Le projet "{project['name']}" a une activité Discord importante :

Signal : {quest_signal.get('content', '')[:500]}

Génère une liste d'actions concrètes (3-5 étapes max) que l'utilisateur doit faire
sur le Discord du projet pour maximiser son engagement et ses chances d'airdrop.
Sois spécifique et actionnable."""

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
                    "description": action_required or f"Participer à la quête détectée sur {project['name']}",
                    "urgency": signal.get("urgency_score", 7),
                    "source_signal": signal.get("id"),
                })
            elif signal_type in ("snapshot", "tge_signal"):
                actions.append({
                    "type": "onchain_tx",
                    "description": f"URGENT : Snapshot imminent sur {project['name']} — vérifier éligibilité",
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

        # Toujours ajouter une action Twitter si le projet est actif
        if signals:
            actions.append({
                "type": "tweet",
                "description": f"Poster un tweet d'engagement pour {project['name']} aujourd'hui",
                "urgency": 4,
                "source_signal": None,
            })

        return sorted(actions, key=lambda a: a.get("urgency", 0), reverse=True)
