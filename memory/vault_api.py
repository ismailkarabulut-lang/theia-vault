"""Vault CRUD + FTS arama + audit — asyncio.to_thread ile async wrapper."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from core.db import db
from supabase_sync import sync_entry, sync_soft_delete, sync_topic  # ← eklendi

log = logging.getLogger("vault")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["meta"] = json.loads(d.get("meta") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["meta"] = {}
    return d


# ── Sync katmanı ──────────────────────────────────────────────────────────────

def _sync_write_entry(entry: dict, actor: str) -> dict:
    """Atomik: entries INSERT + audit + queue (tek transaction)."""
    entry_id = entry.get("id") or str(uuid.uuid4())
    now = _now()

    row = {
        "id":         entry_id,
        "content":    entry["content"],
        "summary":    entry.get("summary"),
        "topic_slug": entry.get("topic_slug"),
        "source":     entry.get("source", "manual"),
        "created_by": actor,
        "confidence": entry.get("confidence", 1.0),
        "version":    1,
        "deleted":    0,
        "created_at": now,
        "updated_at": now,
        "meta":       json.dumps(entry.get("meta", {})),
    }

    with db() as c:
        c.execute("""
            INSERT INTO entries
                (id, content, summary, topic_slug, source, created_by,
                 confidence, version, deleted, created_at, updated_at, meta)
            VALUES
                (:id, :content, :summary, :topic_slug, :source, :created_by,
                 :confidence, :version, :deleted, :created_at, :updated_at, :meta)
        """, row)

        c.execute("""
            INSERT INTO audit (action, target_id, actor, status, detail, ts)
            VALUES ('write_entry', ?, ?, 'ok', ?, ?)
        """, (entry_id, actor, f"source={row['source']}", now))

        c.execute("""
            INSERT INTO queue (job_type, payload, status, attempts, created_at, updated_at)
            VALUES ('summarize', ?, 'pending', 0, ?, ?)
        """, (json.dumps({"entry_id": entry_id}), now, now))

    result = {**row, "meta": entry.get("meta", {})}
    sync_entry(result)  # ← Supabase'e fire-and-forget
    return result


def _sync_get_entry(entry_id: str) -> dict | None:
    with db() as c:
        row = c.execute(
            "SELECT * FROM entries WHERE id=? AND deleted=0", (entry_id,)
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def _sync_soft_delete(entry_id: str, actor: str) -> bool:
    now = _now()
    with db() as c:
        affected = c.execute(
            "UPDATE entries SET deleted=1, updated_at=? WHERE id=? AND deleted=0",
            (now, entry_id),
        ).rowcount
        if affected:
            c.execute("""
                INSERT INTO audit (action, target_id, actor, status, ts)
                VALUES ('soft_delete', ?, ?, 'ok', ?)
            """, (entry_id, actor, now))

    if affected:
        sync_soft_delete(entry_id, now)  # ← Supabase'e fire-and-forget
    return bool(affected)


def _fts5_query(query: str) -> str | None:
    import re
    words = re.findall(r"\w+", query)
    if not words:
        return None
    return " ".join(f'"{w}"' for w in words)


def _sync_search_entries(query: str, limit: int) -> list[dict]:
    safe_query = _fts5_query(query)
    if not safe_query:
        return []
    with db() as c:
        rows = c.execute("""
            SELECT e.*
            FROM entries_fts f
            JOIN entries e ON e.rowid = f.rowid
            WHERE entries_fts MATCH ?
              AND e.deleted = 0
            ORDER BY rank
            LIMIT ?
        """, (safe_query, limit)).fetchall()
    return [_row_to_dict(r) for r in rows]


def _sync_merge_to_topic(
    slug: str, entry_ids: list[str], summary: str, actor: str
) -> None:
    now = _now()
    title = slug.replace("_", " ").replace("-", " ").title()

    with db() as c:
        c.execute("""
            INSERT INTO topics (slug, title, summary, version, entry_count, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                summary     = excluded.summary,
                version     = version + 1,
                entry_count = excluded.entry_count,
                updated_at  = excluded.updated_at
        """, (slug, title, summary, len(entry_ids), now, now))

        for eid in entry_ids:
            c.execute(
                "INSERT OR IGNORE INTO topic_entries (topic_slug, entry_id) VALUES (?, ?)",
                (slug, eid),
            )
            c.execute(
                "UPDATE entries SET topic_slug=?, updated_at=? WHERE id=?",
                (slug, now, eid),
            )

        c.execute("""
            INSERT INTO audit (action, target_id, actor, status, detail, ts)
            VALUES ('merge_to_topic', ?, ?, 'ok', ?, ?)
        """, (slug, actor, f"entries={len(entry_ids)}", now))

        # topic'in güncel versiyonunu al
        row = c.execute("SELECT * FROM topics WHERE slug=?", (slug,)).fetchone()

    if row:
        sync_topic(  # ← Supabase'e fire-and-forget
            slug=row["slug"], title=row["title"], summary=row["summary"],
            entry_count=row["entry_count"], version=row["version"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )


# ── Public async API ──────────────────────────────────────────────────────────

async def write_entry(entry: dict, actor: str) -> dict:
    return await asyncio.to_thread(_sync_write_entry, entry, actor)


async def get_entry(entry_id: str, actor: str) -> dict | None:
    return await asyncio.to_thread(_sync_get_entry, entry_id)


async def soft_delete(entry_id: str, actor: str) -> bool:
    return await asyncio.to_thread(_sync_soft_delete, entry_id, actor)


async def search_entries(query: str, actor: str, limit: int = 10) -> list[dict]:
    return await asyncio.to_thread(_sync_search_entries, query, limit)


async def merge_to_topic(
    slug: str, entry_ids: list[str], summary: str, actor: str
) -> None:
    await asyncio.to_thread(_sync_merge_to_topic, slug, entry_ids, summary, actor)
