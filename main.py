#!/usr/bin/env python3
"""THEIA — Kaptan İsmail'in kişisel AI asistanı."""

import asyncio
import logging
from datetime import time as dtime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from agents import summarizer
from core.config import TOKEN, USER_ID, VAULT_DIR, log
from core.db import init_db
from core.pending import init_pending_table
from handlers.memory import mem_forget_cmd, mem_save_cmd, mem_view_cmd
from handlers.message import handle_message
from handlers.schedule import (
    cb_cancel,
    cb_delay,
    cb_done,
    cb_ertele,
    ekle_conv,
    liste,
    minute_job,
    sifirla,
    tamam_cmd,
    weekly_summary_job,
)
from handlers.shell import cb_cmd_no, cb_cmd_ok, cb_cmd_ok2, cmd_handler
from handlers.start import start


async def _auth(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or user.id != USER_ID:
        if user is not None:
            log.warning("Yetkisiz erişim: user_id=%s username=%s", user.id, user.username or "?")
        raise ApplicationHandlerStop


async def _post_init(app: Application) -> None:
    asyncio.create_task(summarizer.run_forever())


def main() -> None:
    init_db()
    init_pending_table()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    app = Application.builder().token(TOKEN).post_init(_post_init).build()

    app.add_handler(TypeHandler(Update, _auth), group=-1)

    app.add_handler(ekle_conv)
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("liste",   liste))
    app.add_handler(CommandHandler("sifirla", sifirla))
    app.add_handler(CommandHandler("memory",  mem_view_cmd))
    app.add_handler(CommandHandler("hafiza",  mem_view_cmd))
    app.add_handler(CommandHandler("remember", mem_save_cmd))
    app.add_handler(CommandHandler("kaydet",  mem_save_cmd))
    app.add_handler(CommandHandler("forget",  mem_forget_cmd))
    app.add_handler(CommandHandler("unut",    mem_forget_cmd))
    app.add_handler(CallbackQueryHandler(cb_done,    pattern=r"^done:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_cancel,  pattern=r"^cancel:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ertele,  pattern=r"^ertele:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_delay,   pattern=r"^d:\d+:\d+$"))
    app.add_handler(CommandHandler("cmd",    cmd_handler))
    app.add_handler(CallbackQueryHandler(cb_cmd_ok,  pattern=r"^cmd_ok:[0-9a-f]+$"))
    app.add_handler(CallbackQueryHandler(cb_cmd_ok2, pattern=r"^cmd_ok2:[0-9a-f]+$"))
    app.add_handler(CallbackQueryHandler(cb_cmd_no,  pattern=r"^cmd_no:[0-9a-f]+$"))
    app.add_handler(CommandHandler("tamam",   tamam_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(minute_job, interval=60, first=5)
    app.job_queue.run_daily(
        weekly_summary_job,
        time=dtime(6, 0, 0, tzinfo=timezone.utc),  # 09:00 UTC+3
        days=(0,),                                   # 0 = Pazartesi
    )

    log.info("THEIA başlatıldı.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
