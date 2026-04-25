"""Ajan yetki kontrolü — permissions + audit tablosu üzerinden."""

import asyncio
import logging
from datetime import datetime, timezone

from core.db import db

log = logging.getLogger("vault.permissions")


class PermissionDenied(Exception):
    """Actor, istenen scope için yetkisiz."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Sync katmanı ──────────────────────────────────────────────────────────────

def _sync_require_permission(actor: str, scope: str) -> None:
    with db() as c:
        row = c.execute(
            "SELECT 1 FROM permissions WHERE actor=? AND scope=?",
            (actor, scope),
        ).fetchone()

    if row is None:
        # Audit ayrı transaction'da commit edilmeli — exception rollback'i önlemek için
        with db() as c:
            c.execute("""
                INSERT INTO audit (action, target_id, actor, status, detail, ts)
                VALUES ('permission_check', ?, ?, 'denied', ?, ?)
            """, (scope, actor, f"scope={scope}", _now()))
        raise PermissionDenied(f"{actor!r} → {scope!r} yetkisi yok")


def _sync_grant_permission(actor: str, scope: str, granted_by: str) -> None:
    now = _now()
    with db() as c:
        c.execute(
            """
            INSERT OR IGNORE INTO permissions (actor, scope, granted_at, granted_by)
            VALUES (?, ?, ?, ?)
            """,
            (actor, scope, now, granted_by),
        )
        c.execute("""
            INSERT INTO audit (action, target_id, actor, status, detail, ts)
            VALUES ('grant_permission', ?, ?, 'ok', ?, ?)
        """, (scope, granted_by, f"to={actor}", now))


# ── Public async API ──────────────────────────────────────────────────────────

async def require_permission(actor: str, scope: str) -> None:
    """Yetkiyi doğrular. Yoksa PermissionDenied fırlatır ve audit'e 'denied' yazar."""
    await asyncio.to_thread(_sync_require_permission, actor, scope)


async def grant_permission(actor: str, scope: str, granted_by: str) -> None:
    """Yeni ajan veya scope için yetki ekler. Zaten varsa sessizce geçer."""
    await asyncio.to_thread(_sync_grant_permission, actor, scope, granted_by)
