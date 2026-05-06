"""
agent.py — v1.8
Orchestrateur principal d'AirdropAgent.

CHANGELOG v1.8 :
  - Intégration TGERadar : scoring TGE par projet à chaque run
  - Intégration SnapshotEngine : rapport éligibilité + checklist actions
  - Intégration WalletScorer : scoring on-chain des wallets configurés
  - Notifications dédiées pour alertes TGE/snapshot critiques
  - Wallet scoring envoyé une fois par jour (avec briefing)
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
from engines.tge_radar import TGERadar
from engines.snapshot_engine import SnapshotEngine
from engines.wallet_scorer import WalletScorer
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


def sync_projects_from_config(config: dict):
    projects     = config.get("projects", [])
    active_names = [p["name"] for p in projects]
    for project in projects:
        upsert_project(project)
    deactivated = deactivate_removed_projects(active_names)
    if deactivated:
        logger.info(f"Sync projets : {len(active_names)} actifs | désactivés : {deactivated}")
    else:
        logger.info(f"Sync projets : {len(active_names)} actif(s), aucun désactivé")


def _collect_from_source(raw_items, source, project_id, project_name, llm):
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

    contents        = [i["content"] for i in fresh]
    classifications = llm.classify_signals_batch(contents, project_name)
    inserted        = []

    for item, classif in zip(fresh, classifications):
        signal = {
            "project_id":      project_id,
            "source":          source,
            "signal_type":     classif.get("signal_type", "regular_update"),
            "content":         classif.get("summary", item["content"][:300]),
            "content_hash":    item["_hash"],
            "raw_data":        {"original": item["content"], "url": item.get("url", "")},
            "urgency_score":   classif.get("urgency_score", 2),
            "action_required": classif.get("action_required"),
        }
        sid = insert_signal(signal)
        if sid:
            signal["id"] = sid
            inserted.append(signal)

    return inserted, dupes


def collect_and_deduplicate(project, trackers, llm):
    pid   = project["id"]
    pname = project["name"]
    all_new     = []
    total_dupes = 0

    # Twitter
    handle = project.get("twitter_handle", "").strip()
    if handle and trackers.get("twitter"):
        try:
            raw = trackers["twitter"].get_tweets(handle)
            new, dupes = _collect_from_source(raw, "twitter", pid, pname, llm)
            all_new += new; total_dupes += dupes
            logger.info(f"{pname} Twitter : {len(new)} nouveaux, {dupes} doublons")
        except Exception as e:
            logger.warning(f"Twitter — {pname} : {e}")

    # Telegram
    tg_handle = project.get("telegram_handle", "").strip()
    tg        = trackers.get("telegram")
    if tg_handle and tg and tg.enabled:
        try:
            raw = tg.get_messages(tg_handle, limit=20)
            new, dupes = _collect_from_source(raw, "telegram", pid, pname, llm)
            all_new += new; total_dupes += dupes
            logger.info(f"{pname} Telegram : {len(new)} nouveaux, {dupes} doublons")
        except Exception as e:
            logger.warning(f"Telegram — {pname} : {e}")
    elif not tg_handle:
        logger.info(f"{pname} : telegram_handle non configuré")

    # Discord
    guild_id = project.get("discord_guild_id", 0)
    channels = project.get("discord_channels", [])
    discord  = trackers.get("discord")
    if guild_id and discord and discord.enabled:
        try:
            raw = discord.get_messages(guild_id, channels, limit=20)
            new, dupes = _collect_from_source(raw, "discord", pid, pname, llm)
            all_new += new; total_dupes += dupes
            logger.info(f"{pname} Discord : {len(new)} nouveaux, {dupes} doublons")
        except Exception as e:
            logger.warning(f"Discord — {pname} : {e}")
    elif not guild_id:
        logger.info(f"{pname} : discord_guild_id non configuré")

    return {"new": all_new, "duplicate": total_dupes}


def generate_actions(project, signals, content_engine):
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
                logger.warning(f"Tweet {project['name']} : {e}")
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

        # ── Composants ────────────────────────────────────────
        llm            = LLMEngine(config)
        notifier       = Notifier(config)
        content_engine = ContentEngine(llm, config)
        tge_radar      = TGERadar(config)
        snapshot_eng   = SnapshotEngine(config)
        wallet_scorer  = WalletScorer(config)

        telegram_tracker = TelegramTrackerSync()
        discord_tracker  = DiscordTrackerSync()

        logger.info(f"TelegramTracker : {'✅' if telegram_tracker.enabled else '⏸️ '}")
        logger.info(f"DiscordTracker  : {'✅' if discord_tracker.enabled else '⏸️ '}")
        logger.info(f"WalletScorer    : {'✅' if wallet_scorer.wallets else '⏸️  (aucun wallet configuré)'}")

        trackers = {
            "twitter":  TwitterTracker(config),
            "telegram": telegram_tracker,
            "discord":  discord_tracker,
        }

        projects = get_active_projects()
        logger.info(f"{len(projects)} projet(s) actif(s)")

        current_hour    = datetime.utcnow().hour
        is_morning_run  = 6 <= current_hour <= 9
        all_project_data = []

        # ── Boucle par projet ─────────────────────────────────
        for project in projects:
            logger.info(f"--- {project['name']} ---")
            try:
                # 1. Collecte + déduplication + batch LLM
                result      = collect_and_deduplicate(project, trackers, llm)
                new_signals = result["new"]
                dupe_count  = result["duplicate"]

                stats["signals_collected"]  += len(new_signals) + dupe_count
                stats["signals_new"]        += len(new_signals)
                stats["signals_duplicate"]  += dupe_count

                # 2. Notifications signaux urgents
                threshold  = config["notifications"].get("urgency_threshold", 7)
                unnotified = get_unnotified_urgent_signals(project["id"], threshold)
                notified_ids = []
                for signal in unnotified[:3]:
                    sent = notifier.notify_signal(project["name"], signal)
                    if sent > 0:
                        notified_ids.append(signal["id"])
                        stats["notifications_sent"] += sent
                if notified_ids:
                    mark_signals_notified(notified_ids)

                # 3. Génération actions + tweet
                actions = []
                if new_signals:
                    actions = generate_actions(project, new_signals, content_engine)
                    stats["actions_generated"] += len(actions)
                    for ta in [a for a in actions if a.get("action_type") == "tweet" and a.get("generated_content")][:1]:
                        sent = notifier.notify_tweet_suggestion(project["name"], ta["generated_content"])
                        stats["notifications_sent"] += sent

                # 4. ── TGE RADAR ──────────────────────────────
                recent_signals = get_recent_signals(project["id"], hours=48)
                tge_report     = tge_radar.analyze_signals(recent_signals, project["name"])

                if tge_radar.should_alert(tge_report, threshold=40):
                    logger.info(
                        f"TGE Radar — {project['name']} : "
                        f"score {tge_report['global_score']}/100 [{tge_report['risk_level']}]"
                    )

                    # 5. ── SNAPSHOT ENGINE ────────────────────
                    snapshot_report = snapshot_eng.build_report(
                        project, recent_signals, tge_report
                    )

                    # Notifier si score critique ou high
                    if tge_report["risk_level"] in ("critical", "high"):
                        timing = snapshot_report.get("timing", {})
                        sent   = notifier.notify_snapshot_alert(
                            project["name"],
                            snapshot_eng.format_notification(snapshot_report),
                            timing.get("days_estimate"),
                        )
                        stats["notifications_sent"] += sent

                # 6. ── WALLET SCORING (matin uniquement) ──────
                if is_morning_run and wallet_scorer.wallets:
                    logger.info(f"{project['name']} : scoring wallets...")
                    wallet_reports = wallet_scorer.score_all_wallets(project, llm)
                    if wallet_reports:
                        msg  = wallet_scorer.format_notification(wallet_reports, project["name"])
                        sent = notifier._send_telegram(msg) if hasattr(notifier, "_send_telegram") else 0
                        stats["notifications_sent"] += 1 if sent else 0

                all_project_data.append({
                    "name":          project["name"],
                    "priority":      project.get("priority", 5),
                    "signals_new":   len(new_signals),
                    "signals_total": len(recent_signals),
                    "urgent_count":  len(unnotified),
                    "actions_count": len(actions),
                    "tge_score":     tge_report.get("global_score", 0),
                    "tge_risk":      tge_report.get("risk_level", "low"),
                    "top_signal":    new_signals[0].get("content", "") if new_signals else "Aucun nouveau signal",
                })

            except Exception as e:
                logger.error(f"Erreur projet {project['name']} : {e}")
                logger.debug(traceback.format_exc())
                continue

        # ── Briefing quotidien (6h-9h UTC) ───────────────────
        if is_morning_run:
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
        for tracker in trackers.values():
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
