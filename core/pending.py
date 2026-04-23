"""Bekleyen kullanıcı niyetleri — pending_actions tablosu."""

from datetime import datetime, timezone

from core.db import db


def init_pending_table() -> None:
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_actions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                text        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                resolved_at TEXT
            )
        """)


def add_pending(user_id: int, text: str) -> int:
    """Yeni bekleyen niyet ekler, oluşturulan kaydın id'sini döndürür."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as c:
        cur = c.execute(
            "INSERT INTO pending_actions (user_id, text, created_at) VALUES (?, ?, ?)",
            (user_id, text, now),
        )
        return cur.lastrowid


def resolve_pending(action_id: int) -> None:
    """Kaydı çözümlendi olarak işaretler (resolved_at = şimdiki zaman)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as c:
        c.execute(
            "UPDATE pending_actions SET resolved_at = ? WHERE id = ?",
            (now, action_id),
        )


def get_open_pendings(user_id: int) -> list[dict]:
    """Belirli kullanıcının çözümlenmemiş kayıtlarını döndürür."""
    with db() as c:
        rows = c.execute(
            "SELECT id, user_id, text, created_at FROM pending_actions "
            "WHERE user_id = ? AND resolved_at IS NULL ORDER BY id",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_open_pendings() -> list[dict]:
    """Tüm kullanıcıların çözümlenmemiş kayıtlarını döndürür (haftalık özet için)."""
    with db() as c:
        rows = c.execute(
            "SELECT id, user_id, text, created_at FROM pending_actions "
            "WHERE resolved_at IS NULL ORDER BY user_id, id",
        ).fetchall()
    return [dict(r) for r in rows]
