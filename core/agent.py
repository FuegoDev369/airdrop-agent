"""
agent.py — v1.1
Orchestrateur principal d'AirdropAgent.
Boucle de décision : Collecter → Analyser → Décider → Notifier.

CHANGELOG v1.1 :
  - FIX : initialize_db() appelé EN PREMIER avant tout accès SQLite
  - FIX : trackers initialisé hors du try pour éviter NameError dans finally
  - FIX : run_id initialisé à None pour éviter NameError dans finally
  - FIX : ROOT_DIR / CONFIG_PATH en chemins absolus (Termux + GH Actions)
"""

import yaml
import logging
import traceback
from pathlib import Path
from datetime import datetime

from core.state_manager import (
    initialize_db, upsert_project, get_active_projects,
    insert_signal, insert_action, get_pending_actions,
    start_run, finish_run
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

# Chemins absolus — fonctionnent sur Termux ET GitHub Actions
ROOT_DIR = Path(__file__).parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"


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
    """Collecte et classe les signaux pour un projet. Retourne les signaux insérés."""
    inserted = []
    project_id = project["id"]
    project_name = project["name"]

    # ── Twitter ──────────────────────────────────────────────
    twitter_handle = project.get("twitter_handle")
    if twitter_handle and trackers.get("twitter"):
        try:
            tweets = trackers["twitter"].get_tweets(twitter_handle)
            for tweet in tweets:
                content = tweet.get("content", "")
                if not content or len(content) < 10:
                    continue
                classification = llm.classify_signal(content, project_name)
                signal = {
                    "project_id":   project_id,
                    "source":       "twitter",
                    "signal_type":  classification.get("signal_type", "regular_update"),
                    "content":      classification.get("summary", content[:300]),
                    "raw_data":     {"original": content, "url": tweet.get("url", "")},
                    "urgency_score": classification.get("urgency_score", 2),
                    "action_required": classification.get("action_required"),
                }
                signal["id"] = insert_signal(signal)
                inserted.append(signal)
        except Exception as e:
            logger.warning(f"Twitter tracker — {project_name} : {e}")

    # ── Telegram ─────────────────────────────────────────────
    telegram_handle = project.get("telegram_handle")
    if telegram_handle and trackers.get("telegram"):
        try:
            messages = trackers["telegram"].get_messages(telegram_handle, limit=15)
            for msg in messages:
                content = msg.get("content", "")
                if not content or len(content) < 10:
                    continue
                classification = llm.classify_signal(content, project_name)
                signal = {
                    "project_id":   project_id,
                    "source":       "telegram",
                    "signal_type":  classification.get("signal_type", "regular_update"),
                    "content":      classification.get("summary", content[:300]),
                    "raw_data":     {"original": content},
                    "urgency_score": classification.get("urgency_score", 2),
                    "action_required": classification.get("action_required"),
                }
                signal["id"] = insert_signal(signal)
                inserted.append(signal)
        except Exception as e:
            logger.warning(f"Telegram tracker — {project_name} : {e}")

    logger.info(f"{project_name} : {len(inserted)} signal(s) collecté(s)")
    return inserted


def generate_actions(project: dict, signals: list, content_engine: ContentEngine) -> list:
    """Génère les actions recommandées pour un projet et les insère en DB."""
    action_plan = content_engine.generate_action_plan(project, signals)
    inserted = []

    for action in action_plan:
        action_data = {
            "project_id":       project["id"],
            "action_type":      action.get("type", "general"),
            "description":      action.get("description", ""),
            "generated_content": None,
        }
        if action.get("type") == "tweet":
            try:
                tweets = content_engine.generate_tweets(project, signals)
                if tweets:
                    action_data["generated_content"] = tweets[0]["text"]
            except Exception as e:
                logger.warning(f"Génération tweet {project['name']} : {e}")

        action_data["id"] = insert_action(action_data)
        inserted.append(action_data)

    return inserted


def run_agent():
    """
    Point d'entrée principal — exécuté par GitHub Actions (cron) ou manuellement.
    """
    logger.info("=" * 60)
    logger.info("AirdropAgent — Démarrage du run")
    logger.info("=" * 60)

    # Initialisés HORS du try pour être accessibles dans finally sans NameError
    trackers: dict = {}
    run_id = None
    stats = {
        "signals_collected":  0,
        "actions_generated":  0,
        "notifications_sent": 0,
        "status":             "success",
        "error_log":          None,
        "next_run_hours":     2,
    }

    try:
        # ── ÉTAPE 1 : Config ──────────────────────────────────
        config = load_config()
        logger.info(f"Config chargée : {len(config.get('projects', []))} projet(s) défini(s)")

        # ── ÉTAPE 2 : DB — DOIT ÊTRE EN PREMIER ──────────────
        # initialize_db() crée toutes les tables si elles n'existent pas.
        # Tout appel SQLite avant cette ligne provoque "no such table".
        initialize_db()
        logger.info("Base de données initialisée ✅")

        # ── ÉTAPE 3 : Sync projets → DB ──────────────────────
        sync_projects_from_config(config)

        # ── ÉTAPE 4 : Démarrer le run en DB ──────────────────
        run_id = start_run()
        logger.info(f"Run #{run_id} démarré")

        # ── ÉTAPE 5 : Init composants ─────────────────────────
        llm            = LLMEngine(config)
        notifier       = Notifier(config)
        content_engine = ContentEngine(llm, config)

        trackers = {
            "twitter":  TwitterTracker(config),
            "telegram": TelegramTrackerSync(config),
        }

        # ── ÉTAPE 6 : Récupérer les projets actifs ────────────
        projects = get_active_projects()
        logger.info(f"{len(projects)} projet(s) actif(s) à traiter")

        if not projects:
            logger.warning("⚠️  Aucun projet actif — vérifie config/settings.yaml")

        all_project_data = []

        # ── ÉTAPE 7 : Boucle par projet ───────────────────────
        for project in projects:
            logger.info(f"--- {project['name']} ---")
            try:
                # Collecter
                signals = collect_signals(project, trackers, llm)
                stats["signals_collected"] += len(signals)

                # Notifier urgences
                threshold = config["notifications"].get("urgency_threshold", 7)
                urgent = [s for s in signals if s.get("urgency_score", 0) >= threshold]

                for signal in urgent[:3]:
                    sent = notifier.notify_signal(project["name"], signal)
                    stats["notifications_sent"] += sent
                    if signal.get("signal_type") in ("snapshot", "tge_signal"):
                        notifier.notify_snapshot_alert(
                            project["name"], signal.get("content", "")
                        )

                # Générer actions
                actions = generate_actions(project, signals, content_engine)
                stats["actions_generated"] += len(actions)

                # Notifier tweets générés
                tweet_actions = [
                    a for a in actions
                    if a.get("action_type") == "tweet" and a.get("generated_content")
                ]
                for ta in tweet_actions[:1]:
                    sent = notifier.notify_tweet_suggestion(
                        project["name"], ta["generated_content"]
                    )
                    stats["notifications_sent"] += sent

                all_project_data.append({
                    "name":          project["name"],
                    "priority":      project.get("priority", 5),
                    "signals_count": len(signals),
                    "urgent_count":  len(urgent),
                    "actions_count": len(actions),
                    "top_signal":    signals[0].get("content", "") if signals else "Aucun signal",
                })

            except Exception as e:
                logger.error(f"Erreur projet {project['name']} : {e}")
                logger.debug(traceback.format_exc())
                continue

        # ── ÉTAPE 8 : Briefing quotidien (6h-9h UTC) ─────────
        current_hour = datetime.utcnow().hour
        if 6 <= current_hour <= 9:
            logger.info("Génération du briefing quotidien...")
            try:
                brief          = llm.generate_daily_brief(all_project_data)
                pending        = get_pending_actions()
                sent           = notifier.notify_daily_brief(brief, len(pending))
                stats["notifications_sent"] += sent
            except Exception as e:
                logger.warning(f"Briefing quotidien : {e}")

        # ── ÉTAPE 9 : Résumé de run ───────────────────────────
        stats["next_run_hours"] = config["agent"].get("run_interval_hours", 2)
        notifier.notify_run_summary(stats)

    except Exception as e:
        stats["status"]    = "error"
        stats["error_log"] = str(e)
        logger.error(f"Erreur critique : {e}")
        logger.error(traceback.format_exc())

    finally:
        # Clôture DB
        if run_id is not None:
            finish_run(run_id, stats, stats["status"])

        # Fermeture Telegram (safe même si trackers est vide)
        telegram = trackers.get("telegram")
        if telegram:
            try:
                telegram.close()
            except Exception:
                pass

        logger.info(
            f"Run terminé — signaux: {stats['signals_collected']} | "
            f"actions: {stats['actions_generated']} | "
            f"notifs: {stats['notifications_sent']} | "
            f"status: {stats['status']}"
        )
        logger.info("=" * 60)

    return stats


if __name__ == "__main__":
    run_agent()
