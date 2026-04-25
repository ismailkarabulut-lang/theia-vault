"""Veritabanı işlemleri."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from core.config import DB_PATH


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                type           TEXT NOT NULL,
                content        TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                check_after    INTEGER DEFAULT 0,
                status         TEXT DEFAULT 'active',
                recurrence     TEXT DEFAULT 'none',
                created_at     TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id  INTEGER NOT NULL,
                check_at TEXT NOT NULL,
                status   TEXT DEFAULT 'pending'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        # ── Vault tabloları ──────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id           TEXT PRIMARY KEY,
                content      TEXT NOT NULL,
                summary      TEXT,
                topic_slug   TEXT,
                source       TEXT NOT NULL CHECK(source IN ('manual','telegram','gmail','drive','agent')),
                created_by   TEXT NOT NULL,
                confidence   REAL DEFAULT 1.0,
                version      INTEGER DEFAULT 1,
                deleted      INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                meta         TEXT DEFAULT '{}'
            )
        """)
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                content, summary,
                content='entries', content_rowid='rowid'
            )
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS entries_fts_insert
            AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, content, summary)
                VALUES (new.rowid, new.content, new.summary);
            END
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                slug         TEXT PRIMARY KEY,
                title        TEXT NOT NULL,
                summary      TEXT NOT NULL,
                version      INTEGER DEFAULT 1,
                entry_count  INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS topic_entries (
                topic_slug   TEXT NOT NULL REFERENCES topics(slug),
                entry_id     TEXT NOT NULL REFERENCES entries(id),
                PRIMARY KEY (topic_slug, entry_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                action       TEXT NOT NULL,
                target_id    TEXT,
                actor        TEXT NOT NULL,
                status       TEXT DEFAULT 'ok',
                detail       TEXT,
                ts           TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                actor        TEXT NOT NULL,
                scope        TEXT NOT NULL,
                granted_at   TEXT NOT NULL,
                granted_by   TEXT NOT NULL,
                PRIMARY KEY (actor, scope)
            )
        """)
        c.executemany(
            "INSERT OR IGNORE INTO permissions VALUES (?, ?, datetime('now'), ?)",
            [
                ("human",            "read",          "system"),
                ("human",            "write_entry",   "system"),
                ("human",            "delete",        "system"),
                ("human",            "admin",         "system"),
                ("haiku_summarizer", "read",          "system"),
                ("haiku_summarizer", "write_summary", "system"),
                ("web_agent",        "read",          "system"),
                ("web_agent",        "write_entry",   "system"),
                ("memory_agent",     "read",          "system"),
                ("orchestrator_v1",  "read",          "system"),
                ("orchestrator_v1",  "write_entry",   "system"),
                ("orchestrator_v1",  "merge_topic",   "system"),
            ],
        )
        c.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type     TEXT NOT NULL,
                payload      TEXT NOT NULL,
                status       TEXT DEFAULT 'pending',
                attempts     INTEGER DEFAULT 0,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)


def _dt_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def save_message(user_id: int, role: str, content: str) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, _dt_str(datetime.now())),
        )


def get_history(user_id: int, limit: int = 20) -> list[dict]:
    with db() as c:
        rows = c.execute(
            "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_full_history(user_id: int) -> list[dict]:
    with db() as c:
        rows = c.execute(
            "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]
