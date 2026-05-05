"""
agent.py — v1.7
Orchestrateur principal d'AirdropAgent.

CHANGELOG v1.7 :
  - Intégration DiscordTrackerSync dans la boucle de collecte
  - collect_and_deduplicate() étendu avec source Discord
  - Diagnostic explicite état Discord au démarrage
  - discord_guild_id et discord_channels lus depuis settings.yaml
"""

import yaml
import logging
import traceback
from pathlib import Path
from datetime import datetime

from core.state_manager import (
    initialize_db, upsert_project, get_active_projects,
    deactivate_removed_projects,
    insert_signal, get_unnotified_urgent_signals,
    mark_signals_notified, get_recent_signals,
    insert_action, get_pending_actions,
    start_run, finish_run, cleanup_old_signals,
    compute_signal_hash, signal_already_seen,
)
from core.llm_engine import LLMEngine
from trackers.twitter_tracker import TwitterTracker
from trackers.telegram_tracker import TelegramTrackerSync
from trackers.discord_tracker import DiscordTrackerSync
from engines.content_engine import ContentEngine
from utils.notifier import Notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AirdropAgent")

ROOT_DIR    = Path(__file__).parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def sync_projects_from_config(config: dict) -> dict:
    projects     = config.get("projects", [])
    active_names = [p["name"] for p in projects]
    for project in projects:
        upsert_project(project)
    deactivated = deactivate_removed_projects(active_names)
    if deactivated:
        logger.info(f"Sync projets : {len(active_names)} actifs | désactivés : {deactivated}")
    else:
        logger.info(f"Sync projets : {len(active_names)} actif(s), aucun désactivé")
    return {"active": len(active_names), "deactivated": len(deactivated)}


def _collect_from_source(
    raw_items: list,
    source: str,
    project_id: int,
    project_name: str,
    llm: LLMEngine,
) -> tuple[list, int]:
    """
    Filtre les doublons, classifie en batch et insère les nouveaux signaux.
    Retourne (new_signals, duplicate_count).
    Factorisé pour Twitter, Telegram et Discord.
    """
    fresh = []
    dupes = 0

    for item in raw_items:
        content = item.get("content", "")
        if not content or len(content) < 10:
            continue
        h = compute_signal_hash(project_id, source, content)
        if signal_already_seen(project_id, h):
            dupes += 1
        else:
            item["_hash"] = h
            fresh.append(item)

    if not fresh:
        return [], dupes

    contents         = [i["content"] for i in fresh]
    classifications  = llm.classify_signals_batch(contents, project_name)
    inserted         = []

    for item, classif in zip(fresh, classifications):
        signal = {
            "project_id":      project_id,
            "source":          source,
            "signal_type":     classif.get("signal_type", "regular_update"),
            "content":         classif.get("summary", item["content"][:300]),
            "content_hash":    item["_hash"],
            "raw_data":        {
                "original": item["content"],
                "url":      item.get("url", ""),
                "channel":  item.get("channel", ""),
            },
            "urgency_score":   classif.get("urgency_score", 2),
            "action_required": classif.get("action_required"),
        }
        sid = insert_signal(signal)
        if sid:
            signal["id"] = sid
            inserted.append(signal)

    return inserted, dupes


def collect_and_deduplicate(project: dict, trackers: dict, llm: LLMEngine) -> dict:
    """
    Collecte, déduplique et classifie les signaux de toutes les sources.
    Sources : Twitter + Telegram + Discord
    """
    project_id   = project["id"]
    project_name = project["name"]
    all_new      = []
    total_dupes  = 0

    # ── Twitter ──────────────────────────────────────────────
    twitter_handle = project.get("twitter_handle", "").strip()
    if twitter_handle and trackers.get("twitter"):
        try:
            raw = trackers["twitter"].get_tweets(twitter_handle)
            new, dupes = _collect_from_source(raw, "twitter", project_id, project_name, llm)
            all_new     += new
            total_dupes += dupes
            logger.info(f"{project_name} Twitter : {len(new)} nouveaux, {dupes} doublons ignorés")
        except Exception as e:
            logger.warning(f"Twitter — {project_name} : {e}")
            logger.debug(traceback.format_exc())
    elif not twitter_handle:
        logger.debug(f"{project_name} : twitter_handle vide — Twitter ignoré")

    # ── Telegram ─────────────────────────────────────────────
    telegram_handle = project.get("telegram_handle", "").strip()
    tg_tracker      = trackers.get("telegram")

    if not telegram_handle:
        logger.info(f"{project_name} : telegram_handle non configuré — Telegram ignoré")
    elif tg_tracker and tg_tracker.enabled:
        logger.info(f"{project_name} : lecture Telegram @{telegram_handle}...")
        try:
            raw = tg_tracker.get_messages(telegram_handle, limit=20)
            new, dupes = _collect_from_source(raw, "telegram", project_id, project_name, llm)
            all_new     += new
            total_dupes += dupes
            logger.info(f"{project_name} Telegram : {len(new)} nouveaux, {dupes} doublons ignorés")
        except Exception as e:
            logger.warning(f"Telegram — {project_name} : {e}")

    # ── Discord ──────────────────────────────────────────────
    guild_id      = project.get("discord_guild_id", 0)
    channels      = project.get("discord_channels", [])
    discord_tracker = trackers.get("discord")

    if not guild_id or guild_id == 0:
        logger.info(f"{project_name} : discord_guild_id non configuré — Discord ignoré")
    elif not discord_tracker or not discord_tracker.enabled:
        logger.info(f"{project_name} : DiscordTracker désactivé (DISCORD_BOT_TOKEN manquant)")
    else:
        logger.info(f"{project_name} : lecture Discord serveur {guild_id} channels {channels}...")
        try:
            raw = discord_tracker.get_messages(guild_id, channels, limit=20)
            new, dupes = _collect_from_source(raw, "discord", project_id, project_name, llm)
            all_new     += new
            total_dupes += dupes
            logger.info(f"{project_name} Discord : {len(new)} nouveaux, {dupes} doublons ignorés")
        except Exception as e:
            logger.warning(f"Discord — {project_name} : {e}")
            logger.debug(traceback.format_exc())

    return {"new": all_new, "duplicate": total_dupes}


def generate_actions(project: dict, signals: list, content_engine: ContentEngine) -> list:
    action_plan = content_engine.generate_action_plan(project, signals)
    inserted    = []
    for action in action_plan:
        action_data = {
            "project_id":        project["id"],
            "action_type":       action.get("type", "general"),
            "description":       action.get("description", ""),
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
    logger.info("=" * 60)
    logger.info("AirdropAgent — Démarrage du run")
    logger.info("=" * 60)

    trackers: dict = {}
    run_id = None
    stats  = {
        "signals_collected":  0,
        "signals_new":        0,
        "signals_duplicate":  0,
        "actions_generated":  0,
        "notifications_sent": 0,
        "status":             "success",
        "error_log":          None,
        "next_run_hours":     2,
    }

    try:
        config = load_config()
        logger.info(f"Config chargée : {len(config.get('projects', []))} projet(s)")

        initialize_db()
        logger.info("Base de données initialisée ✅")

        sync_projects_from_config(config)
        run_id = start_run()
        logger.info(f"Run #{run_id} démarré")

        cleanup_old_signals(days=7)

        llm            = LLMEngine(config)
        notifier       = Notifier(config)
        content_engine = ContentEngine(llm, config)

        # ── Instanciation trackers ────────────────────────────
        twitter_tracker  = TwitterTracker(config)
        telegram_tracker = TelegramTrackerSync()
        discord_tracker  = DiscordTrackerSync()

        # Diagnostics
        if telegram_tracker.enabled:
            logger.info("TelegramTracker ✅ activé")
        else:
            logger.info("TelegramTracker ⏸️  désactivé (secrets manquants)")

        if discord_tracker.enabled:
            logger.info("DiscordTracker  ✅ activé")
        else:
            logger.info("DiscordTracker  ⏸️  désactivé (DISCORD_BOT_TOKEN manquant)")

        trackers = {
            "twitter":  twitter_tracker,
            "telegram": telegram_tracker,
            "discord":  discord_tracker,
        }

        projects = get_active_projects()
        logger.info(f"{len(projects)} projet(s) actif(s) à traiter")

        if not projects:
            logger.warning("⚠️  Aucun projet actif — vérifie config/settings.yaml")

        all_project_data = []

        for project in projects:
            logger.info(f"--- {project['name']} ---")
            logger.info(
                f"  Sources → "
                f"Twitter: @{project.get('twitter_handle') or 'N/A'} | "
                f"Telegram: @{project.get('telegram_handle') or 'N/A'} | "
                f"Discord: {project.get('discord_guild_id') or 'N/A'}"
            )

            try:
                result      = collect_and_deduplicate(project, trackers, llm)
                new_signals = result["new"]
                dupe_count  = result["duplicate"]

                stats["signals_collected"]  += len(new_signals) + dupe_count
                stats["signals_new"]        += len(new_signals)
                stats["signals_duplicate"]  += dupe_count

                threshold  = config["notifications"].get("urgency_threshold", 7)
                unnotified = get_unnotified_urgent_signals(project["id"], threshold)

                notified_ids = []
                for signal in unnotified[:3]:
                    sent = notifier.notify_signal(project["name"], signal)
                    if sent > 0:
                        notified_ids.append(signal["id"])
                        stats["notifications_sent"] += sent
                    if signal.get("signal_type") in ("snapshot", "tge_signal"):
                        notifier.notify_snapshot_alert(
                            project["name"], signal.get("content", "")
                        )

                if notified_ids:
                    mark_signals_notified(notified_ids)

                actions = []
                if new_signals:
                    actions = generate_actions(project, new_signals, content_engine)
                    stats["actions_generated"] += len(actions)
                    for ta in [a for a in actions if a.get("action_type") == "tweet" and a.get("generated_content")][:1]:
                        sent = notifier.notify_tweet_suggestion(project["name"], ta["generated_content"])
                        stats["notifications_sent"] += sent

                recent = get_recent_signals(project["id"], hours=24)
                all_project_data.append({
                    "name":          project["name"],
                    "priority":      project.get("priority", 5),
                    "signals_new":   len(new_signals),
                    "signals_total": len(recent),
                    "urgent_count":  len(unnotified),
                    "actions_count": len(actions),
                    "top_signal":    new_signals[0].get("content", "") if new_signals else "Aucun nouveau signal",
                })

            except Exception as e:
                logger.error(f"Erreur projet {project['name']} : {e}")
                logger.debug(traceback.format_exc())
                continue

        # ── Briefing quotidien (6h-9h UTC) ───────────────────
        current_hour = datetime.utcnow().hour
        if 6 <= current_hour <= 9:
            logger.info("Génération du briefing quotidien...")
            try:
                brief   = llm.generate_daily_brief(all_project_data)
                pending = get_pending_actions()
                sent    = notifier.notify_daily_brief(brief, len(pending))
                stats["notifications_sent"] += sent
            except Exception as e:
                logger.warning(f"Briefing quotidien : {e}")

        stats["next_run_hours"] = config["agent"].get("run_interval_hours", 2)
        notifier.notify_run_summary(stats)

    except Exception as e:
        stats["status"]    = "error"
        stats["error_log"] = str(e)
        logger.error(f"Erreur critique : {e}")
        logger.error(traceback.format_exc())

    finally:
        if run_id is not None:
            finish_run(run_id, stats, stats["status"])

        for name, tracker in trackers.items():
            try:
                tracker.close()
            except Exception:
                pass

        logger.info(
            f"Run terminé — "
            f"nouveaux: {stats['signals_new']} | "
            f"doublons: {stats['signals_duplicate']} | "
            f"actions: {stats['actions_generated']} | "
            f"notifs: {stats['notifications_sent']} | "
            f"status: {stats['status']}"
        )
        logger.info("=" * 60)

    return stats


if __name__ == "__main__":
    run_agent()
