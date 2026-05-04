"""
agent.py
Orchestrateur principal d'AirdropAgent.
Boucle de décision : Collecter → Analyser → Décider → Notifier.
Point d'entrée pour GitHub Actions.
"""

import yaml
import logging
import traceback
from pathlib import Path
from datetime import datetime

from core.state_manager import (
    initialize_db, upsert_project, get_active_projects,
    insert_signal, get_recent_signals, insert_action,
    get_pending_actions, start_run, finish_run
)
from core.llm_engine import LLMEngine
from trackers.twitter_tracker import TwitterTracker
from trackers.telegram_tracker import TelegramTrackerSync
from engines.content_engine import ContentEngine
from utils.notifier import Notifier

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AirdropAgent")

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def sync_projects_from_config(config: dict):
    """Synchronise les projets du settings.yaml vers la base de données."""
    projects = config.get("projects", [])
    for project in projects:
        pid = upsert_project(project)
        logger.debug(f"Projet synchronisé : {project['name']} (id={pid})")
    logger.info(f"{len(projects)} projet(s) synchronisé(s) depuis la config")


def collect_signals(project: dict, trackers: dict, llm: LLMEngine) -> list:
    """
    Collecte et classe les signaux pour un projet donné.
    Retourne la liste des signaux insérés en DB.
    """
    inserted = []
    project_id = project["id"]
    project_name = project["name"]

    # ── Twitter ──
    twitter_handle = project.get("twitter_handle")
    if twitter_handle and trackers.get("twitter"):
        tweets = trackers["twitter"].get_tweets(twitter_handle)
        for tweet in tweets:
            content = tweet.get("content", "")
            if not content or len(content) < 10:
                continue

            classification = llm.classify_signal(content, project_name)
            signal = {
                "project_id": project_id,
                "source": "twitter",
                "signal_type": classification.get("signal_type", "regular_update"),
                "content": classification.get("summary", content[:300]),
                "raw_data": {"original": content, "url": tweet.get("url", "")},
                "urgency_score": classification.get("urgency_score", 2),
                "action_required": classification.get("action_required"),
            }
            signal_id = insert_signal(signal)
            signal["id"] = signal_id
            inserted.append(signal)

    # ── Telegram ──
    telegram_handle = project.get("telegram_handle")
    if telegram_handle and trackers.get("telegram"):
        messages = trackers["telegram"].get_messages(telegram_handle, limit=15)
        for msg in messages:
            content = msg.get("content", "")
            if not content or len(content) < 10:
                continue

            classification = llm.classify_signal(content, project_name)
            signal = {
                "project_id": project_id,
                "source": "telegram",
                "signal_type": classification.get("signal_type", "regular_update"),
                "content": classification.get("summary", content[:300]),
                "raw_data": {"original": content},
                "urgency_score": classification.get("urgency_score", 2),
                "action_required": classification.get("action_required"),
            }
            signal_id = insert_signal(signal)
            signal["id"] = signal_id
            inserted.append(signal)

    logger.info(f"{project_name} : {len(inserted)} signal(s) collecté(s)")
    return inserted


def generate_actions(project: dict, signals: list, content_engine: ContentEngine) -> list:
    """Génère les actions recommandées pour un projet et les insère en DB."""
    action_plan = content_engine.generate_action_plan(project, signals)
    inserted = []

    for action in action_plan:
        action_data = {
            "project_id": project["id"],
            "action_type": action.get("type", "general"),
            "description": action.get("description", ""),
            "generated_content": None,
        }

        # Générer le tweet si l'action est de type tweet
        if action.get("type") == "tweet":
            tweets = content_engine.generate_tweets(project, signals)
            if tweets:
                action_data["generated_content"] = tweets[0]["text"]

        action_id = insert_action(action_data)
        action_data["id"] = action_id
        inserted.append(action_data)

    return inserted


def run_agent():
    """
    Point d'entrée principal de l'agent.
    Exécuté par GitHub Actions selon le cron configuré.
    """
    logger.info("=" * 60)
    logger.info("AirdropAgent — Démarrage du run")
    logger.info("=" * 60)

    run_id = start_run()
    stats = {
        "signals_collected": 0,
        "actions_generated": 0,
        "notifications_sent": 0,
        "status": "success",
        "error_log": None,
        "next_run_hours": 2,
    }

    try:
        # ── Initialisation ────────────────────────────────────
        config = load_config()
        initialize_db()
        sync_projects_from_config(config)

        llm = LLMEngine(config)
        notifier = Notifier(config)
        content_engine = ContentEngine(llm, config)

        trackers = {
            "twitter": TwitterTracker(config),
            "telegram": TelegramTrackerSync(config),
        }

        projects = get_active_projects()
        logger.info(f"{len(projects)} projet(s) actif(s) à traiter")

        all_project_data = []

        # ── Boucle principale par projet ──────────────────────
        for project in projects:
            logger.info(f"--- Traitement : {project['name']} ---")

            try:
                # 1. Collecter les signaux
                signals = collect_signals(project, trackers, llm)
                stats["signals_collected"] += len(signals)

                # 2. Notifier les signaux urgents
                urgent = [s for s in signals if s.get("urgency_score", 0) >= config["notifications"].get("urgency_threshold", 7)]
                for signal in urgent[:3]:  # Max 3 alertes par projet par run
                    sent = notifier.notify_signal(project["name"], signal)
                    stats["notifications_sent"] += sent

                    # Alerte snapshot spéciale
                    if signal.get("signal_type") in ("snapshot", "tge_signal"):
                        notifier.notify_snapshot_alert(
                            project["name"],
                            signal.get("content", ""),
                        )

                # 3. Générer les actions
                actions = generate_actions(project, signals, content_engine)
                stats["actions_generated"] += len(actions)

                # 4. Notifier les suggestions de tweets
                tweet_actions = [a for a in actions if a.get("action_type") == "tweet" and a.get("generated_content")]
                for ta in tweet_actions[:1]:  # 1 tweet suggéré par projet par run
                    sent = notifier.notify_tweet_suggestion(project["name"], ta["generated_content"])
                    stats["notifications_sent"] += sent

                # Collecter pour le briefing
                all_project_data.append({
                    "name": project["name"],
                    "priority": project.get("priority", 5),
                    "signals_count": len(signals),
                    "urgent_count": len(urgent),
                    "actions_count": len(actions),
                    "top_signal": signals[0].get("content", "") if signals else "Aucun signal",
                })

            except Exception as e:
                logger.error(f"Erreur traitement {project['name']} : {e}")
                logger.debug(traceback.format_exc())
                continue

        # ── Briefing quotidien ────────────────────────────────
        # Envoyé une seule fois par jour (vérification heure)
        current_hour = datetime.utcnow().hour
        if 6 <= current_hour <= 9:  # Envoi briefing entre 6h et 9h UTC
            logger.info("Génération du briefing quotidien...")
            try:
                brief = llm.generate_daily_brief(all_project_data)
                pending_actions = get_pending_actions()
                sent = notifier.notify_daily_brief(brief, len(pending_actions))
                stats["notifications_sent"] += sent
            except Exception as e:
                logger.warning(f"Erreur briefing quotidien : {e}")

        # ── Résumé de run ─────────────────────────────────────
        stats["next_run_hours"] = config["agent"].get("run_interval_hours", 2)
        notifier.notify_run_summary(stats)

    except Exception as e:
        stats["status"] = "error"
        stats["error_log"] = str(e)
        logger.error(f"Erreur critique agent : {e}")
        logger.error(traceback.format_exc())

    finally:
        # Clôturer le run en DB
        finish_run(run_id, stats, stats["status"])

        # Fermer les connexions
        if "telegram" in trackers if "trackers" in dir() else {}:
            try:
                trackers["telegram"].close()
            except Exception:
                pass

        logger.info(f"Run terminé — signaux: {stats['signals_collected']}, "
                    f"actions: {stats['actions_generated']}, "
                    f"notifs: {stats['notifications_sent']}")
        logger.info("=" * 60)

    return stats


if __name__ == "__main__":
    run_agent()
