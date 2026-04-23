"""Başlangıç komutu."""

from telegram import Update
from telegram.ext import ContextTypes

from core.config import ok


async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    await update.message.reply_text("THEIA hazır, Kaptan.")
