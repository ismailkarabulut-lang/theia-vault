"""Başlangıç komutu."""

from telegram import Update
from telegram.ext import ContextTypes


async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("THEIA hazır, Kaptan.")
