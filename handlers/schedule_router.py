"""Telegram handler'ları: /ekle, /liste, /sifirla, /tamam, callback'ler."""

import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from core.db import db
from core.pending import resolve_pending
from handlers.schedule_crud import (
    ASK_TYPE, ASK_CONTENT, ASK_TIME, ASK_RECURRENCE, ASK_RECURRENCE_DETAIL, ASK_CHECK,
    TYPE_LABEL,
    parse_time, dt_str, fmt_item,
    export_to_vault, git_push_vault,
)

log = logging.getLogger(__name__)


async def ekle_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    kb = [[
        InlineKeyboardButton("Görev",      callback_data="t:task"),
        InlineKeyboardButton("Rutin",      callback_data="t:routine"),
        InlineKeyboardButton("Hatırlatma", callback_data="t:reminder"),
    ]]
    await update.message.reply_text("Ne eklemek istersiniz?", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_TYPE


async def got_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["type"] = q.data[2:]
    await q.edit_message_text("İçerik nedir?")
    return ASK_CONTENT


async def got_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["content"] = update.message.text
    await update.message.reply_text(
        "Ne zaman? (örn: `14:30` veya `23.04 14:30` veya `23.04.2026 14:30`)",
        parse_mode="Markdown",
    )
    return ASK_TIME


async def got_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    dt = parse_time(update.message.text)
    if not dt:
        await update.message.reply_text(
            "Anlamadım. Örnek: `14:30` veya `23.04.2026 09:00`", parse_mode="Markdown"
        )
        return ASK_TIME
    ctx.user_data["scheduled_time"] = dt

    if ctx.user_data["type"] == "routine":
        kb = [[
            InlineKeyboardButton("Her gün",  callback_data="r:daily"),
            InlineKeyboardButton("Haftalık", callback_data="r:weekly"),
            InlineKeyboardButton("Aylık",    callback_data="r:monthly"),
        ]]
        await update.message.reply_text("Tekrar sıklığı?", reply_markup=InlineKeyboardMarkup(kb))
        return ASK_RECURRENCE

    return await _ask_check(update.message)


async def got_recurrence(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    rtype = q.data[2:]

    if rtype == "daily":
        ctx.user_data["recurrence"] = "daily"
        return await _ask_check(q)

    ctx.user_data["recurrence_type"] = rtype
    if rtype == "weekly":
        await q.edit_message_text(
            "Hangi günler? `1`=Pzt `2`=Sal `3`=Çrş `4`=Per `5`=Cum `6`=Cmt `7`=Paz\n"
            "Virgülle yaz — örn: `1,3,5`",
            parse_mode="Markdown",
        )
    else:
        await q.edit_message_text("Ayın kaçı? Örn: `15`", parse_mode="Markdown")
    return ASK_RECURRENCE_DETAIL


async def got_recurrence_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text  = update.message.text.strip()
    rtype = ctx.user_data.get("recurrence_type", "")

    if rtype == "weekly":
        try:
            nums    = [int(x.strip()) for x in text.split(",")]
            if not all(1 <= n <= 7 for n in nums):
                raise ValueError
            py_days = sorted(set(n - 1 for n in nums))
            ctx.user_data["recurrence"] = "weekly:" + ",".join(str(d) for d in py_days)
        except ValueError:
            await update.message.reply_text("Geçersiz. Örnek: `1,3,5`", parse_mode="Markdown")
            return ASK_RECURRENCE_DETAIL
    else:
        try:
            day = int(text)
            if not 1 <= day <= 31:
                raise ValueError
            ctx.user_data["recurrence"] = f"monthly:{day}"
        except ValueError:
            await update.message.reply_text("Geçersiz. Örnek: `15`", parse_mode="Markdown")
            return ASK_RECURRENCE_DETAIL

    return await _ask_check(update.message)


async def _ask_check(msg_or_query) -> int:
    kb = [
        [
            InlineKeyboardButton("5 dk",  callback_data="c:5"),
            InlineKeyboardButton("10 dk", callback_data="c:10"),
            InlineKeyboardButton("15 dk", callback_data="c:15"),
        ],
        [
            InlineKeyboardButton("30 dk",        callback_data="c:30"),
            InlineKeyboardButton("1 saat",       callback_data="c:60"),
            InlineKeyboardButton("Kontrol etme", callback_data="c:0"),
        ],
    ]
    if hasattr(msg_or_query, "edit_message_text"):
        await msg_or_query.edit_message_text("Kontrol süresi?", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await msg_or_query.reply_text("Kontrol süresi?", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_CHECK


async def got_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    check_after = int(q.data[2:])
    d  = ctx.user_data
    dt: datetime = d["scheduled_time"]

    with db() as c:
        c.execute(
            "INSERT INTO items (type, content, scheduled_time, check_after, recurrence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (d["type"], d["content"], dt_str(dt), check_after,
             d.get("recurrence", "none"), dt_str(datetime.now())),
        )

    label = TYPE_LABEL.get(d["type"], d["type"])
    await q.edit_message_text(
        f"✅ {label} eklendi.\n📝 {d['content']}\n⏰ {dt.strftime('%d.%m.%Y %H:%M')}"
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def ekle_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text("İptal edildi.")
    return ConversationHandler.END


async def liste(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    with db() as c:
        rows = c.execute(
            "SELECT * FROM items WHERE status IN ('active','triggered') ORDER BY scheduled_time"
        ).fetchall()
    if not rows:
        await update.message.reply_text("Aktif görev yok.")
        return
    await update.message.reply_text("\n".join(fmt_item(r) for r in rows))


async def sifirla(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    filepath = export_to_vault(user_id)
    if filepath:
        success, git_msg = git_push_vault(filepath)
        icon   = "✅" if success else "⚠️"
        status = f"📝 `{filepath.name}` kaydedildi.\n{icon} {git_msg}"
    else:
        status = "ℹ️ Kaydedilecek konuşma yok."

    with db() as c:
        c.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))

    await update.message.reply_text(
        f"{status}\n\n🗑 Konuşma geçmişi temizlendi.", parse_mode="Markdown"
    )


async def cb_done(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    iid = int(q.data.split(":")[1])
    with db() as c:
        row = c.execute("SELECT recurrence FROM items WHERE id=?", (iid,)).fetchone()
        if row and row["recurrence"] == "none":
            c.execute("UPDATE items SET status='completed' WHERE id=?", (iid,))
    await q.edit_message_text((q.message.text or "") + "\n\n✅ Tamamlandı.")


async def cb_cancel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    iid = int(q.data.split(":")[1])
    with db() as c:
        c.execute("UPDATE items SET status='cancelled' WHERE id=?", (iid,))
    await q.edit_message_text((q.message.text or "") + "\n\n❌ İptal edildi.")


async def cb_ertele(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    iid = q.data.split(":")[1]
    kb  = [[
        InlineKeyboardButton("15 dk",  callback_data=f"d:15:{iid}"),
        InlineKeyboardButton("30 dk",  callback_data=f"d:30:{iid}"),
        InlineKeyboardButton("1 saat", callback_data=f"d:60:{iid}"),
        InlineKeyboardButton("2 saat", callback_data=f"d:120:{iid}"),
    ]]
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))


async def cb_delay(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    _, mins_s, iid_s = q.data.split(":")
    mins = int(mins_s)
    iid  = int(iid_s)
    new_time = dt_str(datetime.now() + timedelta(minutes=mins))

    with db() as c:
        row = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if row:
            if row["recurrence"] == "none":
                c.execute(
                    "UPDATE items SET scheduled_time=?, status='active' WHERE id=?",
                    (new_time, iid),
                )
            else:
                c.execute(
                    "INSERT INTO items (type, content, scheduled_time, check_after, recurrence, created_at) "
                    "VALUES (?, ?, ?, ?, 'none', ?)",
                    (row["type"], row["content"], new_time,
                     row["check_after"], dt_str(datetime.now())),
                )

    label = f"{mins} dk" if mins < 60 else f"{mins // 60} saat"
    await q.edit_message_text((q.message.text or "") + f"\n\n⏱ {label} sonraya ertelendi.")


async def tamam_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = (update.message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await update.message.reply_text("Kullanım: `/tamam <id>`", parse_mode="Markdown")
        return
    resolve_pending(int(parts[1].strip()))
    await update.message.reply_text("✅ Kapatıldı.")


ekle_conv = ConversationHandler(
    entry_points=[CommandHandler("ekle", ekle_start)],
    states={
        ASK_TYPE:              [CallbackQueryHandler(got_type,              pattern=r"^t:")],
        ASK_CONTENT:           [MessageHandler(filters.TEXT & ~filters.COMMAND, got_content)],
        ASK_TIME:              [MessageHandler(filters.TEXT & ~filters.COMMAND, got_time)],
        ASK_RECURRENCE:        [CallbackQueryHandler(got_recurrence,        pattern=r"^r:")],
        ASK_RECURRENCE_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_recurrence_detail)],
        ASK_CHECK:             [CallbackQueryHandler(got_check,             pattern=r"^c:")],
    },
    fallbacks=[CommandHandler("iptal", ekle_cancel)],
    allow_reentry=True,
)
