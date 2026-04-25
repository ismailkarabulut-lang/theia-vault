"""Memory Agent — FTS arama + topic getirme + bağlam metni üretimi."""

import asyncio
import logging

from core.db import db
from memory import vault_api

log = logging.getLogger("memory_agent")

_ACTOR         = "memory_agent"
_ENTRY_LIMIT   = 5
_PREVIEW_CHARS = 200


# ── Sync DB yardımcıları ──────────────────────────────────────────────────────

def _fetch_topics(slugs: list[str]) -> dict[str, dict]:
    """slug → {title, summary} haritası. Tek DB açıp kapıyor."""
    if not slugs:
        return {}
    placeholders = ",".join("?" * len(slugs))
    with db() as c:
        rows = c.execute(
            f"SELECT slug, title, summary FROM topics WHERE slug IN ({placeholders})",
            slugs,
        ).fetchall()
    return {r["slug"]: {"title": r["title"], "summary": r["summary"]} for r in rows}


# ── Formatlama ────────────────────────────────────────────────────────────────

def _format_context(entries: list[dict], topics: dict[str, dict]) -> str:
    parts = ["[Hafıza Bağlamı]"]

    # Benzersiz topic özetleri — entry sırasına göre
    seen: set[str] = set()
    for e in entries:
        slug = e.get("topic_slug")
        if slug and slug not in seen and slug in topics:
            t = topics[slug]
            parts.append(f"Konu — {t['title']}: {t['summary']}")
            seen.add(slug)

    # Entry satırları: summary varsa onu, yoksa content önizlemesi
    parts.append("İlgili kayıtlar:")
    for e in entries:
        text = e.get("summary") or (e.get("content") or "")[:_PREVIEW_CHARS]
        parts.append(f"• {text}")

    return "\n".join(parts)


# ── Public async API ──────────────────────────────────────────────────────────

async def get_context(query: str, actor: str = _ACTOR) -> str:
    """
    Kullanıcı sorgusuna göre vault'tan ilgili bağlamı çeker.
    Sonuç yoksa veya hata olursa boş string döner —
    çağıran kod her zaman string alır, kontrol etmesi gerekmez.
    """
    try:
        entries = await vault_api.search_entries(query, actor=actor, limit=_ENTRY_LIMIT)
        if not entries:
            return ""

        # Tekrar eden slug'ları koru, sırayı boz (dict.fromkeys ile dedupe)
        slugs  = list(dict.fromkeys(e["topic_slug"] for e in entries if e.get("topic_slug")))
        topics = await asyncio.to_thread(_fetch_topics, slugs)

        return _format_context(entries, topics)

    except Exception:
        log.exception("get_context başarısız query=%r", query)
        return ""
