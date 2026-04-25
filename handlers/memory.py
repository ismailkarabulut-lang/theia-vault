"""Hafıza komutları: /memory, /hafiza, /kaydet, /unut."""

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from core.db import db
from memory import vault_api


def _sync_recent(limit: int) -> list[dict]:
    with db() as c:
        rows = c.execute(
            """
            SELECT content, summary, source, created_at
            FROM   entries
            WHERE  deleted = 0
            ORDER  BY created_at DESC
            LIMIT  ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


async def _mem_view(update: Update, user_id: int) -> None:
    entries = await asyncio.to_thread(_sync_recent, 10)
    if not entries:
        await update.message.reply_text("Henüz hiçbir şey kaydetmedim.")
        return
    lines = ["📝 Son kayıtlar:\n"]
    for e in entries:
        text = e.get("summary") or e["content"][:120]
        lines.append(f"• {text}")
    await update.message.reply_text("\n".join(lines))


async def mem_view_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _mem_view(update, update.effective_user.id)


async def mem_save_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = (update.message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("Kullanım: `/kaydet <bilgi>`", parse_mode="Markdown")
        return
    await vault_api.write_entry(
        {"content": parts[1].strip(), "source": "manual"},
        actor="human",
    )
    await update.message.reply_text("✓ Kaydedildi.")


async def mem_forget_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = (update.message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("Kullanım: `/unut <bilgi>`", parse_mode="Markdown")
        return
    query   = parts[1].strip()
    results = await vault_api.search_entries(query, actor="human", limit=3)
    if not results:
        await update.message.reply_text("İlgili bir kayıt bulunamadı.")
        return
    ok = await vault_api.soft_delete(results[0]["id"], actor="human")
    if ok:
        await update.message.reply_text(f"✓ Silindi: {results[0]['content'][:80]!r}")
    else:
        await update.message.reply_text("Silme başarısız.")
