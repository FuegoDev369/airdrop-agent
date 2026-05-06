"""
agent.py — v1.9
AirdropAgent main orchestrator.

Run cycle: Collect → Deduplicate → Analyze → Notify
Entry point for GitHub Actions and local Termux usage.

CHANGELOG v1.9:
  - Full translation to English (comments, logs, docstrings)
  - No functional changes from v1.8.1
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
    """
    Bidirectional sync between settings.yaml and the database.
    - Projects in config → upserted (added or updated)
    - Projects in DB missing from config → deactivated (active=0)
    """
    projects     = config.get("projects", [])
    active_names = [p["name"] for p in projects]
    for project in projects:
        upsert_project(project)
    deactivated = deactivate_removed_projects(active_names)
    if deactivated:
        logger.info(f"Project sync: {len(active_names)} active | deactivated: {deactivated}")
    else:
        logger.info(f"Project sync: {len(active_names)} active project(s), none deactivated")


def _collect_from_source(
    raw_items: list,
    source: str,
    project_id: int,
    project_name: str,
    llm: LLMEngine,
) -> tuple:
    """
    Filter duplicates, batch-classify new items, and insert into DB.
    Returns (new_signals list, duplicate_count int).
    Shared logic for Twitter, Telegram, and Discord.
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


def collect_and_deduplicate(
    project: dict,
    trackers: dict,
    llm: LLMEngine,
) -> dict:
    """
    Collect, deduplicate, and batch-classify signals from all sources
    (Twitter, Telegram, Discord) for a given project.
    """
    pid   = project["id"]
    pname = project["name"]
    all_new     = []
    total_dupes = 0

    # ── Twitter ──────────────────────────────────────────────
    twitter_handle = project.get("twitter_handle", "").strip()
    if twitter_handle and trackers.get("twitter"):
        try:
            raw = trackers["twitter"].get_tweets(twitter_handle)
            new, dupes = _collect_from_source(raw, "twitter", pid, pname, llm)
            all_new += new
            total_dupes += dupes
            logger.info(f"{pname} Twitter: {len(new)} new, {dupes} duplicates skipped")
        except Exception as e:
            logger.warning(f"Twitter tracker — {pname}: {e}")
            logger.debug(traceback.format_exc())
    elif not twitter_handle:
        logger.debug(f"{pname}: twitter_handle not configured — Twitter skipped")

    # ── Telegram ─────────────────────────────────────────────
    tg_handle = project.get("telegram_handle", "").strip()
    tg        = trackers.get("telegram")

    if not tg_handle:
        logger.info(f"{pname}: telegram_handle not configured — Telegram skipped")
    elif tg and tg.enabled:
        logger.info(f"{pname}: reading Telegram @{tg_handle}...")
        try:
            raw = tg.get_messages(tg_handle, limit=20)
            new, dupes = _collect_from_source(raw, "telegram", pid, pname, llm)
            all_new += new
            total_dupes += dupes
            logger.info(f"{pname} Telegram: {len(new)} new, {dupes} duplicates skipped")
        except Exception as e:
            logger.warning(f"Telegram tracker — {pname}: {e}")
    else:
        logger.info(f"{pname}: TelegramTracker disabled (missing secrets)")

    # ── Discord ──────────────────────────────────────────────
    guild_id = project.get("discord_guild_id", 0)
    channels = project.get("discord_channels", [])
    discord  = trackers.get("discord")

    if not guild_id or guild_id == 0:
        logger.info(f"{pname}: discord_guild_id not configured — Discord skipped")
    elif discord and discord.enabled:
        logger.info(f"{pname}: reading Discord guild {guild_id} channels {channels}...")
        try:
            raw = discord.get_messages(guild_id, channels, limit=20)
            new, dupes = _collect_from_source(raw, "discord", pid, pname, llm)
            all_new += new
            total_dupes += dupes
            logger.info(f"{pname} Discord: {len(new)} new, {dupes} duplicates skipped")
        except Exception as e:
            logger.warning(f"Discord tracker — {pname}: {e}")
            logger.debug(traceback.format_exc())
    else:
        logger.info(f"{pname}: DiscordTracker disabled (DISCORD_USER_TOKEN missing)")

    return {"new": all_new, "duplicate": total_dupes}


def generate_actions(
    project: dict,
    signals: list,
    content_engine: ContentEngine,
) -> list:
    """Generate recommended actions for a project and insert them into DB."""
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
                logger.warning(f"Tweet generation — {project['name']}: {e}")

        action_data["id"] = insert_action(action_data)
        inserted.append(action_data)

    return inserted


def run_agent():
    """
    Main agent entry point.
    Executed by GitHub Actions (cron schedule) or manually.
    """
    logger.info("=" * 60)
    logger.info("AirdropAgent — Starting run")
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
        # ── Initialization ────────────────────────────────────
        config = load_config()
        logger.info(f"Config loaded: {len(config.get('projects', []))} project(s) defined")

        # DB must be initialized FIRST — before any SQLite access
        initialize_db()
        logger.info("Database initialized ✅")

        sync_projects_from_config(config)

        run_id = start_run()
        logger.info(f"Run #{run_id} started")

        # Clean up signals older than 7 days
        cleanup_old_signals(days=7)

        # ── Component initialization ──────────────────────────
        llm            = LLMEngine(config)
        notifier       = Notifier(config)
        content_engine = ContentEngine(llm, config)
        tge_radar      = TGERadar(config)
        snapshot_eng   = SnapshotEngine(config)
        wallet_scorer  = WalletScorer(config)

        telegram_tracker = TelegramTrackerSync()
        discord_tracker  = DiscordTrackerSync()

        # Diagnostics
        logger.info(f"TelegramTracker : {'✅ enabled' if telegram_tracker.enabled else '⏸  disabled (missing secrets)'}")
        logger.info(f"DiscordTracker  : {'✅ enabled' if discord_tracker.enabled else '⏸  disabled (DISCORD_USER_TOKEN missing)'}")
        logger.info(f"WalletScorer    : {'✅ ' + str(len(wallet_scorer.wallets)) + ' wallet(s)' if wallet_scorer.wallets else '⏸  disabled (no WALLET_ADDRESSES configured)'}")

        trackers = {
            "twitter":  TwitterTracker(config),
            "telegram": telegram_tracker,
            "discord":  discord_tracker,
        }

        projects = get_active_projects()
        logger.info(f"{len(projects)} active project(s) to process")

        if not projects:
            logger.warning("⚠️  No active projects — check config/settings.yaml")

        current_hour   = datetime.utcnow().hour
        is_morning_run = 6 <= current_hour <= 9
        all_project_data = []

        # ── Main project loop ─────────────────────────────────
        for project in projects:
            logger.info(f"--- {project['name']} ---")
            logger.info(
                f"  Sources → "
                f"Twitter: @{project.get('twitter_handle') or 'N/A'} | "
                f"Telegram: @{project.get('telegram_handle') or 'N/A'} | "
                f"Discord: {project.get('discord_guild_id') or 'N/A'}"
            )

            try:
                # 1. Collect + deduplicate + batch LLM classification
                result      = collect_and_deduplicate(project, trackers, llm)
                new_signals = result["new"]
                dupe_count  = result["duplicate"]

                stats["signals_collected"]  += len(new_signals) + dupe_count
                stats["signals_new"]        += len(new_signals)
                stats["signals_duplicate"]  += dupe_count

                # 2. Notify urgent unnotified signals
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

                # 3. Generate actions + tweet suggestion
                actions = []
                if new_signals:
                    actions = generate_actions(project, new_signals, content_engine)
                    stats["actions_generated"] += len(actions)
                    tweet_actions = [
                        a for a in actions
                        if a.get("action_type") == "tweet" and a.get("generated_content")
                    ]
                    for ta in tweet_actions[:1]:
                        sent = notifier.notify_tweet_suggestion(
                            project["name"], ta["generated_content"]
                        )
                        stats["notifications_sent"] += sent

                # 4. TGE Radar analysis (48h signals)
                recent_signals = get_recent_signals(project["id"], hours=48)
                tge_report     = tge_radar.analyze_signals(recent_signals, project["name"])

                alert_threshold = config.get("tge_radar", {}).get("alert_threshold", 40)
                if tge_radar.should_alert(tge_report, threshold=alert_threshold):
                    logger.info(
                        f"TGE Radar — {project['name']}: "
                        f"score {tge_report['global_score']}/100 [{tge_report['risk_level']}]"
                    )

                    # 5. Snapshot Engine report
                    snapshot_report = snapshot_eng.build_report(
                        project, recent_signals, tge_report
                    )

                    # Alert if critical or high risk
                    if tge_report["risk_level"] in ("critical", "high"):
                        timing = snapshot_report.get("timing", {})
                        sent   = notifier.notify_snapshot_alert(
                            project["name"],
                            snapshot_eng.format_notification(snapshot_report),
                            timing.get("days_estimate"),
                        )
                        stats["notifications_sent"] += sent

                # 6. Wallet Scoring (morning run only)
                if is_morning_run and wallet_scorer.wallets:
                    logger.info(f"{project['name']}: scoring wallets...")
                    try:
                        wallet_reports = wallet_scorer.score_all_wallets(project, llm)
                        if wallet_reports:
                            msg = wallet_scorer.format_notification(
                                wallet_reports, project["name"]
                            )
                            notifier._send_telegram(msg)
                            stats["notifications_sent"] += 1
                    except Exception as e:
                        logger.warning(f"Wallet scoring — {project['name']}: {e}")

                all_project_data.append({
                    "name":          project["name"],
                    "priority":      project.get("priority", 5),
                    "signals_new":   len(new_signals),
                    "signals_total": len(recent_signals),
                    "urgent_count":  len(unnotified),
                    "actions_count": len(actions),
                    "tge_score":     tge_report.get("global_score", 0),
                    "tge_risk":      tge_report.get("risk_level", "low"),
                    "top_signal":    new_signals[0].get("content", "") if new_signals else "No new signals",
                })

            except Exception as e:
                logger.error(f"Error processing {project['name']}: {e}")
                logger.debug(traceback.format_exc())
                continue

        # ── Daily briefing (6:00–9:00 UTC) ───────────────────
        if is_morning_run:
            logger.info("Generating daily briefing...")
            try:
                brief   = llm.generate_daily_brief(all_project_data)
                pending = get_pending_actions()
                sent    = notifier.notify_daily_brief(brief, len(pending))
                stats["notifications_sent"] += sent
            except Exception as e:
                logger.warning(f"Daily briefing error: {e}")

        stats["next_run_hours"] = config["agent"].get("run_interval_hours", 2)
        notifier.notify_run_summary(stats)

    except Exception as e:
        stats["status"]    = "error"
        stats["error_log"] = str(e)
        logger.error(f"Critical error: {e}")
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
            f"Run completed — "
            f"new: {stats['signals_new']} | "
            f"duplicates: {stats['signals_duplicate']} | "
            f"actions: {stats['actions_generated']} | "
            f"notifications: {stats['notifications_sent']} | "
            f"status: {stats['status']}"
        )
        logger.info("=" * 60)

    return stats


if __name__ == "__main__":
    run_agent()
