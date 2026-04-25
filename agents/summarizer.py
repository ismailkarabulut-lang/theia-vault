"""Queue worker — 'summarize' ve 'topic_merge' işlerini tüketir."""

import asyncio
import json
import logging
from datetime import datetime, timezone

import anthropic

from core.config import claude
from core.db import db
from memory import vault_api

log = logging.getLogger("summarizer")

_HAIKU        = "claude-haiku-4-5-20251001"
_POLL_SECS    = 5
_MAX_ATTEMPTS = 3

_SUMMARY_PROMPT = (
    "Aşağıdaki metni 1-2 cümleyle özetle. Türkçe yaz. "
    "Sadece özeti döndür, başka hiçbir şey ekleme.\n\n{content}"
)
_TOPIC_PROMPT = (
    "Aşağıdaki {n} girdiyi tek bir kısa paragrafta özetle. "
    "Türkçe yaz. Sadece özeti döndür.\n\n{entries}"
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Sync DB yardımcıları ──────────────────────────────────────────────────────

def _claim_job() -> dict | None:
    """En eski pending işi atomic olarak 'processing' durumuna çeker."""
    with db() as c:
        row = c.execute(
            """
            SELECT * FROM queue
            WHERE status = 'pending' AND attempts < ?
            ORDER BY id
            LIMIT 1
            """,
            (_MAX_ATTEMPTS,),
        ).fetchone()
        if row is None:
            return None
        c.execute(
            "UPDATE queue SET status='processing', attempts=attempts+1, updated_at=? WHERE id=?",
            (_now(), row["id"]),
        )
    return dict(row)


def _finish_job(job_id: int, status: str, detail: str = "") -> None:
    with db() as c:
        c.execute(
            "UPDATE queue SET status=?, updated_at=? WHERE id=?",
            (status, _now(), job_id),
        )
        if detail:
            log.debug("job %d → %s: %s", job_id, status, detail)


def _update_summary(entry_id: str, summary: str) -> None:
    """Entry.summary günceller ve FTS5 indeksini senkronize eder."""
    now = _now()
    with db() as c:
        row = c.execute(
            "SELECT rowid, content, summary FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if row is None:
            return

        c.execute(
            "UPDATE entries SET summary=?, updated_at=? WHERE id=?",
            (summary, now, entry_id),
        )

        # FTS5 content table güncelleme: önce eski kaydı sil, sonra yenisini ekle
        c.execute(
            "INSERT INTO entries_fts(entries_fts, rowid, content, summary) VALUES('delete', ?, ?, ?)",
            (row["rowid"], row["content"], row["summary"]),
        )
        c.execute(
            "INSERT INTO entries_fts(rowid, content, summary) VALUES(?, ?, ?)",
            (row["rowid"], row["content"], summary),
        )


def _get_entries_content(entry_ids: list[str]) -> list[str]:
    if not entry_ids:
        return []
    placeholders = ",".join("?" * len(entry_ids))
    with db() as c:
        rows = c.execute(
            f"SELECT content FROM entries WHERE id IN ({placeholders}) AND deleted=0",
            entry_ids,
        ).fetchall()
    return [r["content"] for r in rows]


# ── Haiku çağrıları ───────────────────────────────────────────────────────────

def _call_haiku(prompt: str) -> str:
    resp = claude.messages.create(
        model=_HAIKU,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── İş işleyicileri ───────────────────────────────────────────────────────────

async def _handle_summarize(payload: dict) -> None:
    entry_id = payload.get("entry_id")
    if not entry_id:
        raise ValueError("payload'da entry_id yok")

    with db() as c:
        row = c.execute(
            "SELECT content FROM entries WHERE id=? AND deleted=0", (entry_id,)
        ).fetchone()
    if row is None:
        log.warning("summarize: entry bulunamadı entry_id=%s", entry_id)
        return

    summary = await asyncio.to_thread(
        _call_haiku,
        _SUMMARY_PROMPT.format(content=row["content"]),
    )
    await asyncio.to_thread(_update_summary, entry_id, summary)
    log.info("summarize OK entry_id=%s", entry_id[:8])


async def _handle_topic_merge(payload: dict) -> None:
    slug      = payload.get("slug")
    entry_ids = payload.get("entry_ids", [])
    actor     = payload.get("actor", "summarizer")

    if not slug or not entry_ids:
        raise ValueError("payload'da slug veya entry_ids yok")

    contents = await asyncio.to_thread(_get_entries_content, entry_ids)
    if not contents:
        log.warning("topic_merge: girdi içeriği bulunamadı slug=%s", slug)
        return

    joined  = "\n---\n".join(contents)
    summary = await asyncio.to_thread(
        _call_haiku,
        _TOPIC_PROMPT.format(n=len(contents), entries=joined),
    )
    await vault_api.merge_to_topic(slug, entry_ids, summary, actor)
    log.info("topic_merge OK slug=%s entries=%d", slug, len(entry_ids))


# ── Ana döngü ─────────────────────────────────────────────────────────────────

async def run_forever() -> None:
    log.info("Summarizer başlatıldı (poll=%ds, max_attempts=%d)", _POLL_SECS, _MAX_ATTEMPTS)
    while True:
        try:
            job = await asyncio.to_thread(_claim_job)
            if job is None:
                await asyncio.sleep(_POLL_SECS)
                continue

            job_id   = job["id"]
            job_type = job["job_type"]
            payload  = json.loads(job["payload"])
            log.debug("İş alındı: id=%d type=%s", job_id, job_type)

            try:
                if job_type == "summarize":
                    await _handle_summarize(payload)
                elif job_type == "topic_merge":
                    await _handle_topic_merge(payload)
                else:
                    log.warning("Bilinmeyen job_type=%s, atlanıyor", job_type)

                _finish_job(job_id, "done")

            except (anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError) as e:
                log.warning("API hatası job=%d: %s", job_id, e)
                _finish_job(job_id, "pending", f"api_error: {e}")  # yeniden denenecek

            except Exception as e:
                log.exception("İş başarısız job=%d type=%s", job_id, job_type)
                _finish_job(job_id, "failed", str(e))

        except Exception:
            log.exception("run_forever döngüsünde beklenmeyen hata")
            await asyncio.sleep(_POLL_SECS)
