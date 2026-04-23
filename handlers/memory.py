"""Hafıza komutları: /memory, /hafiza, /kaydet, /unut."""

from telegram import Update
from telegram.ext import ContextTypes

from core.config import claude, ok
from memory.memory_manager import MemoryManager

memory_manager = MemoryManager()


async def _mem_view(update: Update, user_id: int) -> None:
    mem = memory_manager.load_memory(user_id)
    if mem:
        await update.message.reply_text(f"📝 Hatırladıklarım:\n\n{mem}")
    else:
        await update.message.reply_text("Henüz hiçbir şey kaydetmedim.")


async def mem_view_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    await _mem_view(update, update.effective_user.id)


async def mem_save_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    parts = (update.message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("Kullanım: `/kaydet <bilgi>`", parse_mode="Markdown")
        return
    msg = await memory_manager.manual_save(update.effective_user.id, parts[1].strip(), claude)
    await update.message.reply_text(msg)


async def mem_forget_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    parts = (update.message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("Kullanım: `/unut <bilgi>`", parse_mode="Markdown")
        return
    msg = await memory_manager.manual_forget(update.effective_user.id, parts[1].strip(), claude)
    await update.message.reply_text(msg)
