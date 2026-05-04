"""
state_manager.py
Gestionnaire d'état persistant via SQLite.
Unique source de vérité pour toutes les données de l'agent.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "agent.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_db():
    """Crée toutes les tables si elles n'existent pas."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                twitter_handle TEXT,
                discord_invite TEXT,
                telegram_handle TEXT,
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
                raw_data TEXT DEFAULT '{}',
                urgency_score INTEGER DEFAULT 0,
                actioned BOOLEAN DEFAULT 0,
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
                actions_generated INTEGER DEFAULT 0,
                notifications_sent INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                error_log TEXT
            );
        """)
    logger.info(f"Base de données initialisée : {DB_PATH}")


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
                    contract_address = ?, chain = ?, tge_date = ?,
                    priority = ?, tags = ?, active = 1
                WHERE name = ?
            """, (
                project.get("twitter_handle"),
                project.get("discord_invite"),
                project.get("telegram_handle"),
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
                     contract_address, chain, tge_date, priority, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project["name"],
                project.get("twitter_handle"),
                project.get("discord_invite"),
                project.get("telegram_handle"),
                project.get("contract_address"),
                project.get("chain"),
                project.get("tge_date"),
                project.get("priority", 5),
                json.dumps(project.get("tags", [])),
            ))
            return cursor.lastrowid


def get_active_projects() -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE active = 1 ORDER BY priority DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Signaux ──────────────────────────────────────────────────

def insert_signal(signal: dict) -> int:
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO signals
                (project_id, source, signal_type, content, raw_data, urgency_score)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            signal["project_id"],
            signal["source"],
            signal["signal_type"],
            signal["content"],
            json.dumps(signal.get("raw_data", {})),
            signal.get("urgency_score", 0),
        ))
        return cursor.lastrowid


def get_recent_signals(project_id: int, hours: int = 24) -> list:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM signals
            WHERE project_id = ?
              AND collected_at >= datetime('now', ? || ' hours')
            ORDER BY urgency_score DESC, collected_at DESC
        """, (project_id, f"-{hours}")).fetchall()
        return [dict(r) for r in rows]


def get_unactioned_signals(min_urgency: int = 5) -> list:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT s.*, p.name as project_name
            FROM signals s
            JOIN projects p ON s.project_id = p.id
            WHERE s.actioned = 0 AND s.urgency_score >= ?
            ORDER BY s.urgency_score DESC
        """, (min_urgency,)).fetchall()
        return [dict(r) for r in rows]


def mark_signal_actioned(signal_id: int):
    with get_connection() as conn:
        conn.execute("UPDATE signals SET actioned = 1 WHERE id = ?", (signal_id,))


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


def mark_action_notified(action_id: int):
    with get_connection() as conn:
        conn.execute("UPDATE actions SET notified = 1 WHERE id = ?", (action_id,))


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
                actions_generated = ?,
                notifications_sent = ?,
                status = ?,
                error_log = ?
            WHERE id = ?
        """, (
            stats.get("signals_collected", 0),
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
