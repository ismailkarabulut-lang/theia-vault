"""Dakika başı ve haftalık özet cron job'ları."""

import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.config import CHAT_ID
from core.db import db
from core.pending import get_all_open_pendings
from handlers.schedule_crud import TYPE_LABEL, next_occurrence, dt_str

log = logging.getLogger(__name__)


async def minute_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    now   = datetime.now().replace(second=0, microsecond=0)
    now_s = dt_str(now)

    with db() as c:
        due_items = c.execute(
            "SELECT * FROM items WHERE status='active' AND scheduled_time <= ?", (now_s,)
        ).fetchall()

        for item in due_items:
            iid = item["id"]
            ca  = item["check_after"]

            if item["recurrence"] != "none":
                trigger_dt = datetime.strptime(item["scheduled_time"], "%Y-%m-%d %H:%M")
                nxt = next_occurrence(item["recurrence"], trigger_dt)
                if nxt:
                    c.execute("UPDATE items SET scheduled_time=? WHERE id=?", (dt_str(nxt), iid))
                else:
                    c.execute("UPDATE items SET status='completed' WHERE id=?", (iid,))
            else:
                new_status = "triggered" if ca > 0 else "completed"
                c.execute("UPDATE items SET status=? WHERE id=?", (new_status, iid))

            if ca > 0:
                c.execute(
                    "INSERT INTO checks (item_id, check_at) VALUES (?, ?)",
                    (iid, dt_str(now + timedelta(minutes=ca))),
                )

        due_checks = c.execute(
            "SELECT ch.id, ch.item_id, i.content, i.type "
            "FROM checks ch JOIN items i ON i.id=ch.item_id "
            "WHERE ch.status='pending' AND ch.check_at <= ?",
            (now_s,),
        ).fetchall()

        for chk in due_checks:
            c.execute("UPDATE checks SET status='sent' WHERE id=?", (chk["id"],))

    for item in due_items:
        try:
            await ctx.bot.send_message(
                CHAT_ID, f"🔔 {TYPE_LABEL.get(item['type'], item['type'])}: {item['content']}"
            )
        except Exception:
            log.exception("Hatırlatma gönderilemedi: item_id=%s", item["id"])

    for chk in due_checks:
        iid = chk["item_id"]
        kb  = [[
            InlineKeyboardButton("✅ Tamamlandı", callback_data=f"done:{iid}"),
            InlineKeyboardButton("❌ İptal",      callback_data=f"cancel:{iid}"),
            InlineKeyboardButton("⏱ Ertele",     callback_data=f"ertele:{iid}"),
        ]]
        try:
            await ctx.bot.send_message(
                CHAT_ID,
                f"🔍 Tamamlandı mı?\n{TYPE_LABEL.get(chk['type'], chk['type'])}: {chk['content']}",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        except Exception:
            log.exception("Kontrol mesajı gönderilemedi: item_id=%s", chk["item_id"])


async def weekly_summary_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    pendings = get_all_open_pendings()
    if not pendings:
        return

    by_user: dict[int, list[dict]] = {}
    for p in pendings:
        by_user.setdefault(p["user_id"], []).append(p)

    for user_id, items in by_user.items():
        lines = ["📋 Haftalık hatırlatma", "Şu işler hâlâ bekliyor:"]
        for item in items:
            lines.append(f"• [{item['created_at']}] — {item['text']}")
        lines.append("\nKapatmak için: /tamam <id>")
        try:
            await ctx.bot.send_message(user_id, "\n".join(lines))
        except Exception:
            log.exception("Haftalık özet gönderilemedi: user_id=%s", user_id)
