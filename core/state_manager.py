"""
state_manager.py — v1.5.3
Gestionnaire d'état persistant via SQLite.

CHANGELOG v1.5.3 :
  - FIX : purge des signaux avec content_hash='' AVANT CREATE UNIQUE INDEX
    Les anciens signaux (v1.4 et avant) ont tous content_hash='' ce qui
    cause une violation UNIQUE constraint à la création de l'index.
    Solution : on les supprime proprement — ils sont de toute façon
    inutilisables pour la déduplication (hash manquant).
"""

import sqlite3
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent
DB_PATH = ROOT_DIR / "data" / "agent.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_db():
    """
    Initialisation DB en 4 étapes garanties dans l'ordre :
      1. CREATE TABLE   — structure de base
      2. _migrate_db()  — ajout colonnes manquantes
      3. _purge_legacy_signals() — supprime anciens signaux sans hash
      4. CREATE INDEX   — après migration ET purge
    """
    with get_connection() as conn:

        # ── ÉTAPE 1 : Tables ──────────────────────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                twitter_handle TEXT,
                discord_invite TEXT,
                telegram_handle TEXT,
                website_url TEXT,
                contract_address TEXT,
                chain TEXT,
                tge_date DATE,
                priority INTEGER DEFAULT 5,
                tags TEXT DEFAULT '[]',
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL DEFAULT '',
                raw_data TEXT DEFAULT '{}',
                urgency_score INTEGER DEFAULT 0,
                actioned BOOLEAN DEFAULT 0,
                notified BOOLEAN DEFAULT 0,
                collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                generated_content TEXT,
                deadline DATETIME,
                completed BOOLEAN DEFAULT 0,
                notified BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS wallet_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                project_id INTEGER,
                score_estimate REAL,
                breakdown TEXT DEFAULT '{}',
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                signals_collected INTEGER DEFAULT 0,
                signals_new INTEGER DEFAULT 0,
                signals_duplicate INTEGER DEFAULT 0,
                actions_generated INTEGER DEFAULT 0,
                notifications_sent INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                error_log TEXT
            );
        """)

        # ── ÉTAPE 2 : Migration colonnes manquantes ───────────
        _migrate_db(conn)

        # ── ÉTAPE 3 : Purge signaux legacy sans hash ──────────
        # Les signaux v1.4 ont content_hash='' → doublons sur l'index unique
        # On les supprime avant de créer l'index.
        _purge_legacy_signals(conn)

        # ── ÉTAPE 4 : Index — après migration ET purge ────────
        conn.executescript("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_hash
                ON signals(project_id, content_hash);

            CREATE INDEX IF NOT EXISTS idx_signals_project
                ON signals(project_id, collected_at);

            CREATE INDEX IF NOT EXISTS idx_signals_notified
                ON signals(notified, urgency_score);
        """)

    logger.info(f"Base de données initialisée : {DB_PATH}")


def _migrate_db(conn: sqlite3.Connection):
    """Ajoute les colonnes manquantes sur DB existante. Safe à rejouer."""
    migrations = [
        ("signals",    "content_hash",     "TEXT NOT NULL DEFAULT ''"),
        ("signals",    "notified",          "BOOLEAN DEFAULT 0"),
        ("agent_runs", "signals_new",       "INTEGER DEFAULT 0"),
        ("agent_runs", "signals_duplicate", "INTEGER DEFAULT 0"),
        ("projects",   "website_url",       "TEXT"),
    ]
    for table, column, col_def in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            logger.info(f"Migration DB : {table}.{column} ajoutée ✅")
        except sqlite3.OperationalError:
            pass  # Colonne déjà existante


def _purge_legacy_signals(conn: sqlite3.Connection):
    """
    Supprime les signaux dont content_hash='' (anciens signaux v1.4).
    Nécessaire pour permettre la création de l'index UNIQUE.
    Ces signaux sont inutilisables pour la déduplication de toute façon.
    """
    result = conn.execute(
        "DELETE FROM signals WHERE content_hash = ''"
    )
    if result.rowcount > 0:
        logger.info(
            f"Purge legacy : {result.rowcount} ancien(s) signal(s) sans hash supprimé(s) "
            f"(migration v1.4→v1.5)"
        )


# ── Hash de déduplication ────────────────────────────────────

def compute_signal_hash(project_id: int, source: str, raw_content: str) -> str:
    key = f"{project_id}|{source}|{raw_content[:500]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def signal_already_seen(project_id: int, content_hash: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM signals WHERE project_id = ? AND content_hash = ?",
            (project_id, content_hash)
        ).fetchone()
        return row is not None


# ── Projets ──────────────────────────────────────────────────

def upsert_project(project: dict) -> int:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (project["name"],)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE projects SET
                    twitter_handle = ?, discord_invite = ?, telegram_handle = ?,
                    website_url = ?, contract_address = ?, chain = ?, tge_date = ?,
                    priority = ?, tags = ?, active = 1
                WHERE name = ?
            """, (
                project.get("twitter_handle"),
                project.get("discord_invite"),
                project.get("telegram_handle"),
                project.get("website_url"),
                project.get("contract_address"),
                project.get("chain"),
                project.get("tge_date"),
                project.get("priority", 5),
                json.dumps(project.get("tags", [])),
                project["name"],
            ))
            return existing["id"]
        else:
            cursor = conn.execute("""
                INSERT INTO projects
                    (name, twitter_handle, discord_invite, telegram_handle,
                     website_url, contract_address, chain, tge_date, priority, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project["name"],
                project.get("twitter_handle"),
                project.get("discord_invite"),
                project.get("telegram_handle"),
                project.get("website_url"),
                project.get("contract_address"),
                project.get("chain"),
                project.get("tge_date"),
                project.get("priority", 5),
                json.dumps(project.get("tags", [])),
            ))
            return cursor.lastrowid


def deactivate_removed_projects(active_names: list) -> list:
    if not active_names:
        logger.warning("deactivate_removed_projects : liste vide — aucune désactivation")
        return []

    with get_connection() as conn:
        placeholders = ",".join("?" * len(active_names))
        rows = conn.execute(f"""
            SELECT name FROM projects
            WHERE active = 1 AND name NOT IN ({placeholders})
        """, active_names).fetchall()

        removed = [row["name"] for row in rows]

        if removed:
            conn.execute(f"""
                UPDATE projects SET active = 0
                WHERE name NOT IN ({placeholders})
            """, active_names)
            for name in removed:
                logger.info(f"Projet désactivé (retiré du settings.yaml) : {name}")

    return removed


def get_active_projects() -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE active = 1 ORDER BY priority DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Signaux ──────────────────────────────────────────────────

def insert_signal(signal: dict) -> Optional[int]:
    with get_connection() as conn:
        try:
            cursor = conn.execute("""
                INSERT INTO signals
                    (project_id, source, signal_type, content,
                     content_hash, raw_data, urgency_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                signal["project_id"],
                signal["source"],
                signal["signal_type"],
                signal["content"],
                signal["content_hash"],
                json.dumps(signal.get("raw_data", {})),
                signal.get("urgency_score", 0),
            ))
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_unnotified_urgent_signals(project_id: int, min_urgency: int = 7) -> list:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM signals
            WHERE project_id = ? AND urgency_score >= ? AND notified = 0
            ORDER BY urgency_score DESC, collected_at DESC
            LIMIT 5
        """, (project_id, min_urgency)).fetchall()
        return [dict(r) for r in rows]


def mark_signals_notified(signal_ids: list):
    if not signal_ids:
        return
    placeholders = ",".join("?" * len(signal_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE signals SET notified = 1 WHERE id IN ({placeholders})",
            signal_ids
        )


def get_recent_signals(project_id: int, hours: int = 24) -> list:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM signals
            WHERE project_id = ?
              AND collected_at >= datetime('now', ? || ' hours')
            ORDER BY urgency_score DESC, collected_at DESC
        """, (project_id, f"-{hours}")).fetchall()
        return [dict(r) for r in rows]


# ── Nettoyage ─────────────────────────────────────────────────

def cleanup_old_signals(days: int = 7):
    with get_connection() as conn:
        result = conn.execute("""
            DELETE FROM signals
            WHERE notified = 1
              AND collected_at < datetime('now', ? || ' days')
        """, (f"-{days}",))
        if result.rowcount > 0:
            logger.info(f"Nettoyage DB : {result.rowcount} signaux anciens supprimés")


# ── Actions ──────────────────────────────────────────────────

def insert_action(action: dict) -> int:
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO actions
                (project_id, action_type, description, generated_content, deadline)
            VALUES (?, ?, ?, ?, ?)
        """, (
            action["project_id"],
            action["action_type"],
            action["description"],
            action.get("generated_content"),
            action.get("deadline"),
        ))
        return cursor.lastrowid


def get_pending_actions(project_id: Optional[int] = None) -> list:
    with get_connection() as conn:
        if project_id:
            rows = conn.execute("""
                SELECT a.*, p.name as project_name FROM actions a
                JOIN projects p ON a.project_id = p.id
                WHERE a.completed = 0 AND a.project_id = ?
                ORDER BY a.created_at DESC
            """, (project_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT a.*, p.name as project_name FROM actions a
                JOIN projects p ON a.project_id = p.id
                WHERE a.completed = 0
                ORDER BY p.priority DESC, a.created_at DESC
            """).fetchall()
        return [dict(r) for r in rows]


def mark_action_completed(action_id: int):
    with get_connection() as conn:
        conn.execute("UPDATE actions SET completed = 1 WHERE id = ?", (action_id,))


# ── Runs ─────────────────────────────────────────────────────

def start_run() -> int:
    with get_connection() as conn:
        cursor = conn.execute("INSERT INTO agent_runs DEFAULT VALUES")
        return cursor.lastrowid


def finish_run(run_id: int, stats: dict, status: str = "success"):
    with get_connection() as conn:
        conn.execute("""
            UPDATE agent_runs SET
                finished_at = CURRENT_TIMESTAMP,
                signals_collected = ?,
                signals_new = ?,
                signals_duplicate = ?,
                actions_generated = ?,
                notifications_sent = ?,
                status = ?,
                error_log = ?
            WHERE id = ?
        """, (
            stats.get("signals_collected", 0),
            stats.get("signals_new", 0),
            stats.get("signals_duplicate", 0),
            stats.get("actions_generated", 0),
            stats.get("notifications_sent", 0),
            status,
            stats.get("error_log"),
            run_id,
        ))


def get_last_run() -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
