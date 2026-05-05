"""
Supabase sync katmanı — lokal SQLite'ın bulut yedği.
vault_api.py'ye dokunulmaz. Her write/delete/merge sonrası çağrılır.
Fire-and-forget: hata olsa bile ana akışı bozmaz.
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("supabase_sync")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://cynjiwqifbimmnfvbzue.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",  # upsert davranışı
}


def _headers() -> dict:
    """Her çağrıda güncel env'den header üretir."""
    key = os.getenv("SUPABASE_ANON_KEY", SUPABASE_KEY)
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


async def _post(table: str, payload: dict) -> None:
    """Tek kayıt upsert."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(url, json=payload, headers=_headers())
            if r.status_code not in (200, 201):
                log.warning("supabase %s upsert failed: %s %s", table, r.status_code, r.text[:200])
            else:
                log.debug("supabase %s synced: %s", table, payload.get("id", "?"))
    except Exception as e:
        log.warning("supabase sync error (%s): %s", table, e)


async def _patch(table: str, row_id: str, payload: dict) -> None:
    """ID ile patch (soft delete için)."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.patch(url, json=payload, headers=_headers())
            if r.status_code not in (200, 204):
                log.warning("supabase %s patch failed: %s %s", table, r.status_code, r.text[:200])
    except Exception as e:
        log.warning("supabase sync error patch (%s): %s", table, e)


# ── Public API ────────────────────────────────────────────────────────────────

def sync_entry(entry: dict) -> None:
    """
    vault_api.write_entry() sonrası çağrılır.
    asyncio.create_task ile fire-and-forget.
    """
    payload = {k: v for k, v in entry.items()}
    # meta dict → JSON string (Supabase jsonb kabul eder ama string de olur)
    if isinstance(payload.get("meta"), dict):
        import json
        payload["meta"] = json.dumps(payload["meta"])

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_post("entries", payload))
        else:
            loop.run_until_complete(_post("entries", payload))
    except Exception as e:
        log.warning("sync_entry dispatch failed: %s", e)


def sync_soft_delete(entry_id: str, updated_at: str) -> None:
    """
    vault_api.soft_delete() sonrası çağrılır.
    """
    try:
        loop = asyncio.get_event_loop()
        payload = {"deleted": 1, "updated_at": updated_at}
        if loop.is_running():
            asyncio.create_task(_patch("entries", entry_id, payload))
        else:
            loop.run_until_complete(_patch("entries", entry_id, payload))
    except Exception as e:
        log.warning("sync_soft_delete dispatch failed: %s", e)


def sync_topic(slug: str, title: str, summary: str, entry_count: int,
               version: int, created_at: str, updated_at: str) -> None:
    """
    vault_api.merge_to_topic() sonrası çağrılır.
    """
    payload = {
        "slug": slug,
        "title": title,
        "summary": summary,
        "entry_count": entry_count,
        "version": version,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_post("topics", payload))
        else:
            loop.run_until_complete(_post("topics", payload))
    except Exception as e:
        log.warning("sync_topic dispatch failed: %s", e)


# ── Bulk migrate: mevcut SQLite'ı Supabase'e tek seferlik yükle ──────────────

async def migrate_all(db_path: str) -> dict:
    """
    Terminalden: python -c "import asyncio; from supabase_sync import migrate_all; asyncio.run(migrate_all('theia.db'))"
    Mevcut tüm entries + topics'i Supabase'e yükler.
    """
    import sqlite3, json

    results = {"entries": 0, "topics": 0, "errors": 0}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    entries = conn.execute("SELECT * FROM entries WHERE deleted=0").fetchall()
    topics  = conn.execute("SELECT * FROM topics").fetchall()
    conn.close()

    async with httpx.AsyncClient(timeout=15) as client:
        for row in entries:
            d = dict(row)
            try:
                meta = json.loads(d.get("meta") or "{}")
                d["meta"] = json.dumps(meta)
            except Exception:
                d["meta"] = "{}"
            try:
                r = await client.post(
                    f"{SUPABASE_URL}/rest/v1/entries",
                    json=d, headers=_headers()
                )
                if r.status_code in (200, 201):
                    results["entries"] += 1
                else:
                    log.warning("migrate entry %s: %s", d.get("id"), r.text[:100])
                    results["errors"] += 1
            except Exception as e:
                log.warning("migrate entry error: %s", e)
                results["errors"] += 1

        for row in topics:
            d = dict(row)
            try:
                r = await client.post(
                    f"{SUPABASE_URL}/rest/v1/topics",
                    json=d, headers=_headers()
                )
                if r.status_code in (200, 201):
                    results["topics"] += 1
                else:
                    results["errors"] += 1
            except Exception as e:
                results["errors"] += 1

    log.info("migrate done: %s", results)
    return results
