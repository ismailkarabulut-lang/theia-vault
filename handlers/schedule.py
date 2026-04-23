"""Görev/rutin/hatırlatma yönetimi: /ekle, /liste, /sifirla, cron job ve callbacks."""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from core.config import CHAT_ID, VAULT_DIR, ok
from core.db import db, get_full_history
import os

log = logging.getLogger(__name__)

ASK_TYPE, ASK_CONTENT, ASK_TIME, ASK_RECURRENCE, ASK_RECURRENCE_DETAIL, ASK_CHECK = range(6)

TYPE_LABEL = {"task": "Görev", "routine": "Rutin", "reminder": "Hatırlatma"}

_TR_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart",    4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım",  12: "Aralık",
}


def parse_time(text: str) -> datetime | None:
    text = text.strip()
    now  = datetime.now().replace(second=0, microsecond=0)
    for fmt, today_only in [
        ("%H:%M",           True),
        ("%d.%m %H:%M",     False),
        ("%d.%m.%Y %H:%M",  False),
        ("%Y-%m-%d %H:%M",  False),
    ]:
        try:
            dt = datetime.strptime(text, fmt)
            if today_only:
                dt = now.replace(hour=dt.hour, minute=dt.minute)
                if dt <= now:
                    dt += timedelta(days=1)
            elif dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt
        except ValueError:
            continue
    return None


def next_occurrence(rule: str, after: datetime) -> datetime | None:
    h, m = after.hour, after.minute
    base = after.replace(second=0, microsecond=0)
    if rule == "daily":
        return base + timedelta(days=1)
    if rule.startswith("weekly:"):
        days      = sorted(int(d) for d in rule[7:].split(","))
        candidate = base + timedelta(days=1)
        for _ in range(8):
            if candidate.weekday() in days:
                return candidate.replace(hour=h, minute=m, second=0, microsecond=0)
            candidate += timedelta(days=1)
    if rule.startswith("monthly:"):
        day        = int(rule[8:])
        next_month = (base.replace(day=1) + timedelta(days=32)).replace(day=1)
        try:
            return next_month.replace(day=day, hour=h, minute=m, second=0, microsecond=0)
        except ValueError:
            return None
    return None


def dt_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_item(r) -> str:
    t     = TYPE_LABEL.get(r["type"], r["type"])
    recur = f" [{r['recurrence']}]" if r["recurrence"] != "none" else ""
    return f"• [{t}]{recur} {r['content']} — {r['scheduled_time']}"


# ── /ekle conversation ─────────────────────────────────────────────────────────

async def ekle_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not ok(update):
        return ConversationHandler.END
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
    if not ok(update):
        return ConversationHandler.END
    ctx.user_data["type"] = q.data[2:]
    await q.edit_message_text("İçerik nedir?")
    return ASK_CONTENT


async def got_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not ok(update):
        return ConversationHandler.END
    ctx.user_data["content"] = update.message.text
    await update.message.reply_text(
        "Ne zaman? (örn: `14:30` veya `23.04 14:30` veya `23.04.2026 14:30`)",
        parse_mode="Markdown",
    )
    return ASK_TIME


async def got_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not ok(update):
        return ConversationHandler.END
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
    if not ok(update):
        return ConversationHandler.END
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
    if not ok(update):
        return ConversationHandler.END
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
    if not ok(update):
        return ConversationHandler.END
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
    if not ok(update):
        return ConversationHandler.END
    ctx.user_data.clear()
    await update.message.reply_text("İptal edildi.")
    return ConversationHandler.END


# ── /liste ─────────────────────────────────────────────────────────────────────

async def liste(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    with db() as c:
        rows = c.execute(
            "SELECT * FROM items WHERE status IN ('active','triggered') ORDER BY scheduled_time"
        ).fetchall()
    if not rows:
        await update.message.reply_text("Aktif görev yok.")
        return
    await update.message.reply_text("\n".join(fmt_item(r) for r in rows))


# ── Vault export & git push ────────────────────────────────────────────────────

def export_to_vault(user_id: int) -> Path | None:
    rows = get_full_history(user_id)
    if not rows:
        return None

    now      = datetime.now()
    filename = now.strftime("%Y-%m-%d_%H-%M") + ".md"
    date_str = f"{now.day} {_TR_MONTHS[now.month]} {now.year} {now.strftime('%H:%M')}"

    lines = [f"# Theia Konuşması — {date_str}", ""]
    for msg in rows:
        speaker = "İsmail" if msg["role"] == "user" else "Theia"
        lines.append(f"**{speaker}:** {msg['content']}")
        lines.append("")

    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = VAULT_DIR / filename
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


def git_push_vault(filepath: Path) -> tuple[bool, str]:
    is_new = not (VAULT_DIR / ".git").exists()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    if is_new:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return False, "GITHUB_TOKEN .env dosyasında bulunamadı."
        remote_url = f"https://{token}@github.com/ismailkarabulut-lang/theia-vault.git"
        for cmd in [
            ["git", "-C", str(VAULT_DIR), "init"],
            ["git", "-C", str(VAULT_DIR), "remote", "add", "origin", remote_url],
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return False, f"`{cmd[2]}` hata: {r.stderr.strip()}"

    for cmd in [
        ["git", "-C", str(VAULT_DIR), "add", filepath.name],
        ["git", "-C", str(VAULT_DIR), "commit", "-m",
         f"Konuşma: {filepath.stem.replace('_', ' ')}"],
        ["git", "-C", str(VAULT_DIR), "push", "-u", "origin", "HEAD"],
    ]:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, f"`{' '.join(cmd[2:])}` hata: {r.stderr.strip() or r.stdout.strip()}"
    return True, "Push tamamlandı."


# ── /sifirla ───────────────────────────────────────────────────────────────────

async def sifirla(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
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


# ── Post-reminder callbacks ────────────────────────────────────────────────────

async def cb_done(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not ok(update):
        return
    iid = int(q.data.split(":")[1])
    with db() as c:
        row = c.execute("SELECT recurrence FROM items WHERE id=?", (iid,)).fetchone()
        if row and row["recurrence"] == "none":
            c.execute("UPDATE items SET status='completed' WHERE id=?", (iid,))
    await q.edit_message_text((q.message.text or "") + "\n\n✅ Tamamlandı.")


async def cb_cancel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not ok(update):
        return
    iid = int(q.data.split(":")[1])
    with db() as c:
        c.execute("UPDATE items SET status='cancelled' WHERE id=?", (iid,))
    await q.edit_message_text((q.message.text or "") + "\n\n❌ İptal edildi.")


async def cb_ertele(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not ok(update):
        return
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
    if not ok(update):
        return
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


# ── Dakika başı cron job ───────────────────────────────────────────────────────

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


# ── ConversationHandler ────────────────────────────────────────────────────────

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
