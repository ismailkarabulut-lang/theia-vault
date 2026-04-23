#!/usr/bin/env python3
"""THEIA — Kaptan İsmail'in kişisel AI asistanı."""

import asyncio
import logging
import os
import re
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from gatekeeper import AuditLog, Risk, RiskClassifier, SandboxExecutor
from memory.memory_manager import MemoryManager

# ── Environment ───────────────────────────────────────────────────────────────
_env = Path.home() / "theia" / ".env"
load_dotenv(_env if _env.exists() else ".env")

TOKEN     = os.environ["TELEGRAM_TOKEN"]
CHAT_ID   = int(os.environ["CHAT_ID"])
USER_ID   = int(os.environ["USER_ID"])
DB_PATH   = Path.home() / "theia" / "theia.db"
VAULT_DIR = Path.home() / "theia-vault"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Anthropic ─────────────────────────────────────────────────────────────────
_claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
SYSTEM = (
    "Ben THEIA'yım. Kaptan İsmail'in dijital asistanıyım. "
    "Kısa ve net konuşurum. Türkçe cevap veririm. Kaptanıma saygılıyım."
)
SYSTEM_WEB = SYSTEM + (
    " Web arama sonuçları geldiğinde doğrudan özet ver, "
    "alternatif site önerme. Sonuç yoksa kısa söyle."
)

# ── Web search trigger ───────────────────────────────────────────────────────
_SEARCH_RE = re.compile(r"\b(ara|bul|güncel|hava)\b|\bkur(?!ul|ban)", re.IGNORECASE)
_WEB_TOOLS = [{"type": "web_search_20250305", "name": "web_search"}]

# ── Memory ────────────────────────────────────────────────────────────────────
memory_manager = MemoryManager()

_MEM_SAVE_RE   = re.compile(r"bunu hatırla|bunu kaydet|önemli:", re.IGNORECASE)
_MEM_FORGET_RE = re.compile(r"bunu unut|bunu sil memory'den", re.IGNORECASE)
_MEM_VIEW_RE   = re.compile(r"ne hatırlıyorsun", re.IGNORECASE)

# ── Gatekeeper ───────────────────────────────────────────────────────────────
_classifier = RiskClassifier()
_executor   = SandboxExecutor()
_audit      = AuditLog()
_pending: dict[str, dict] = {}  # uid → {cmd, risk, reason, step}

_RISK_ICON = {Risk.LOW: "✅", Risk.MEDIUM: "⚠️", Risk.HIGH: "🔴", Risk.CRITICAL: "☠️"}

# ── Conversation states ───────────────────────────────────────────────────────
ASK_TYPE, ASK_CONTENT, ASK_TIME, ASK_RECURRENCE, ASK_RECURRENCE_DETAIL, ASK_CHECK = range(6)

# ── DB ────────────────────────────────────────────────────────────────────────
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                type           TEXT NOT NULL,
                content        TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                check_after    INTEGER DEFAULT 0,
                status         TEXT DEFAULT 'active',
                recurrence     TEXT DEFAULT 'none',
                created_at     TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id  INTEGER NOT NULL,
                check_at TEXT NOT NULL,
                status   TEXT DEFAULT 'pending'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)


# ── Time utilities ────────────────────────────────────────────────────────────
def parse_time(text: str) -> datetime | None:
    text = text.strip()
    now = datetime.now().replace(second=0, microsecond=0)
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
        days = sorted(int(d) for d in rule[7:].split(","))
        candidate = base + timedelta(days=1)
        for _ in range(8):
            if candidate.weekday() in days:
                return candidate.replace(hour=h, minute=m, second=0, microsecond=0)
            candidate += timedelta(days=1)
    if rule.startswith("monthly:"):
        day = int(rule[8:])
        next_month = (base.replace(day=1) + timedelta(days=32)).replace(day=1)
        try:
            return next_month.replace(day=day, hour=h, minute=m, second=0, microsecond=0)
        except ValueError:
            return None
    return None


def dt_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


TYPE_LABEL = {"task": "Görev", "routine": "Rutin", "reminder": "Hatırlatma"}


def fmt_item(r) -> str:
    t = TYPE_LABEL.get(r["type"], r["type"])
    recur = f" [{r['recurrence']}]" if r["recurrence"] != "none" else ""
    return f"• [{t}]{recur} {r['content']} — {r['scheduled_time']}"


def ok(update: Update) -> bool:
    user = update.effective_user
    if user is None or user.id != USER_ID:
        if user is not None:
            log.warning(
                "Yetkisiz erişim girişimi: user_id=%s username=%s",
                user.id,
                user.username or "?",
            )
        return False
    return True


# ── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    await update.message.reply_text("THEIA hazır, Kaptan.")


# ── /ekle conversation ────────────────────────────────────────────────────────
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
    text = update.message.text.strip()
    rtype = ctx.user_data.get("recurrence_type", "")

    if rtype == "weekly":
        try:
            nums = [int(x.strip()) for x in text.split(",")]
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
    d = ctx.user_data
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


# ── /liste ────────────────────────────────────────────────────────────────────
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


# ── Minute job ────────────────────────────────────────────────────────────────
async def minute_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now().replace(second=0, microsecond=0)
    now_s = dt_str(now)
    due_items = []
    due_checks = []

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
        except Exception as e:
            log.error("Hatırlatma gönderilemedi: %s", e)

    for chk in due_checks:
        iid = chk["item_id"]
        kb = [[
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
        except Exception as e:
            log.error("Kontrol mesajı gönderilemedi: %s", e)


# ── Post-reminder callbacks ───────────────────────────────────────────────────
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
    kb = [[
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
                # Routine: insert a one-off ghost so the recurring schedule is untouched
                c.execute(
                    "INSERT INTO items (type, content, scheduled_time, check_after, recurrence, created_at) "
                    "VALUES (?, ?, ?, ?, 'none', ?)",
                    (row["type"], row["content"], new_time, row["check_after"], dt_str(datetime.now())),
                )

    label = f"{mins} dk" if mins < 60 else f"{mins // 60} saat"
    await q.edit_message_text((q.message.text or "") + f"\n\n⏱ {label} sonraya ertelendi.")


# ── /cmd ─────────────────────────────────────────────────────────────────────
async def cmd_handler(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    parts = (update.message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("Kullanım: `/cmd <komut>`", parse_mode="Markdown")
        return

    command = parts[1].strip()
    result  = _classifier.classify(command)
    icon    = _RISK_ICON[result.risk]

    if result.risk == Risk.CRITICAL:
        _audit.write(command, result.risk, "blocked")
        await update.message.reply_text(
            f"☠️ CRITICAL — Engellendi\n`{command}`\n\nNeden: {result.reason}",
            parse_mode="Markdown",
        )
        return

    if result.risk == Risk.LOW:
        _audit.write(command, result.risk, "auto_run")
        await update.message.reply_text(
            f"✅ LOW — Çalıştırılıyor...\n`{command}`", parse_mode="Markdown"
        )
        success, output = _executor.run(command)
        text = ("✅" if success else "❌") + f" `{command}`\n\n{output}"
        if len(text) > 4000:
            text = text[:3990] + "\n…(kesildi)"
        _audit.write(command, result.risk, "executed", output)
        await update.message.reply_text(text, parse_mode=None)
        return

    # MEDIUM / HIGH → onay gerekli
    uid = uuid.uuid4().hex[:10]
    _pending[uid] = {"cmd": command, "risk": result.risk, "reason": result.reason, "step": 1}
    kb = [[
        InlineKeyboardButton("✅ Onayla", callback_data=f"cmd_ok:{uid}"),
        InlineKeyboardButton("❌ Reddet", callback_data=f"cmd_no:{uid}"),
    ]]
    await update.message.reply_text(
        f"{icon} {result.risk} — Onay gerekli\n`{command}`\n\nNeden: {result.reason}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def cb_cmd_ok(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not ok(update):
        return
    uid = q.data.split(":")[1]
    pending = _pending.get(uid)
    if not pending:
        await q.edit_message_text((q.message.text or "") + "\n\n⚠️ İşlem süresi doldu.")
        return

    command = pending["cmd"]
    risk    = pending["risk"]

    if risk == Risk.HIGH and pending["step"] == 1:
        pending["step"] = 2
        kb = [[
            InlineKeyboardButton("⚠️ Kesin Onayla", callback_data=f"cmd_ok2:{uid}"),
            InlineKeyboardButton("❌ Reddet",        callback_data=f"cmd_no:{uid}"),
        ]]
        await q.edit_message_text(
            f"🔴 HIGH — İkinci onay gerekli!\n`{command}`\n\nBu işlem geri alınamayabilir. Emin misiniz?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    _pending.pop(uid, None)
    await _run_and_reply(q, command, risk)


async def cb_cmd_ok2(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not ok(update):
        return
    uid = q.data.split(":")[1]
    pending = _pending.pop(uid, None)
    if not pending:
        await q.edit_message_text((q.message.text or "") + "\n\n⚠️ İşlem süresi doldu.")
        return
    await _run_and_reply(q, pending["cmd"], pending["risk"])


async def cb_cmd_no(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not ok(update):
        return
    uid = q.data.split(":")[1]
    pending = _pending.pop(uid, None)
    if pending:
        _audit.write(pending["cmd"], pending["risk"], "rejected")
    cmd = pending["cmd"] if pending else "?"
    await q.edit_message_text(f"❌ Reddedildi.\n`{cmd}`", parse_mode="Markdown")


async def _run_and_reply(q, command: str, risk: Risk) -> None:
    await q.edit_message_text(f"⚙️ Çalıştırılıyor...\n`{command}`", parse_mode="Markdown")
    success, output = _executor.run(command)
    text = ("✅" if success else "❌") + f" `{command}`\n\n{output}"
    if len(text) > 4000:
        text = text[:3990] + "\n…(kesildi)"
    _audit.write(command, risk, "executed", output)
    await q.edit_message_text(text, parse_mode=None)


# ── Conversation history helpers ─────────────────────────────────────────────
def save_message(user_id: int, role: str, content: str) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, dt_str(datetime.now())),
        )


def get_history(user_id: int, limit: int = 20) -> list[dict]:
    with db() as c:
        rows = c.execute(
            "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_full_history(user_id: int) -> list[dict]:
    with db() as c:
        rows = c.execute(
            "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ── Obsidian vault export ─────────────────────────────────────────────────────
_TR_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart",    4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım",  12: "Aralık",
}


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
        remote_url = (
            f"https://{token}@github.com/ismailkarabulut-lang/theia-vault.git"
        )
        for cmd in [
            ["git", "-C", str(VAULT_DIR), "init"],
            ["git", "-C", str(VAULT_DIR), "remote", "add", "origin", remote_url],
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return False, f"`{cmd[2]}` hata: {r.stderr.strip()}"

    for cmd in [
        ["git", "-C", str(VAULT_DIR), "add", filepath.name],
        ["git", "-C", str(VAULT_DIR), "commit", "-m", f"Konuşma: {filepath.stem.replace('_', ' ')}"],
        ["git", "-C", str(VAULT_DIR), "push", "-u", "origin", "HEAD"],
    ]:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, f"`{' '.join(cmd[2:])}` hata: {r.stderr.strip() or r.stdout.strip()}"
    return True, "Push tamamlandı."


# ── /sifirla ──────────────────────────────────────────────────────────────────
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


# ── Memory command/trigger handlers ──────────────────────────────────────────
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
    msg = await memory_manager.manual_save(update.effective_user.id, parts[1].strip(), _claude)
    await update.message.reply_text(msg)


async def mem_forget_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    parts = (update.message.text or "").split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("Kullanım: `/unut <bilgi>`", parse_mode="Markdown")
        return
    msg = await memory_manager.manual_forget(update.effective_user.id, parts[1].strip(), _claude)
    await update.message.reply_text(msg)


async def _update_memory_bg(user_id: int, history: list) -> None:
    if memory_manager.should_update_memory(user_id, history):
        new_mem = await memory_manager.extract_memory_update(user_id, history, _claude)
        if new_mem:
            memory_manager.save_memory(user_id, new_mem)


def _build_system(user_memory: str, web: bool) -> str:
    base = SYSTEM_WEB if web else SYSTEM
    if not user_memory:
        return base
    return (
        base +
        f"\n\nBu kullanıcı hakkında bildiğin bilgiler:\n{user_memory}\n\n"
        "Bu bilgileri doğal olarak kullan, her seferinde 'biliyorum ki...' deme."
    )


# ── General message → Claude ──────────────────────────────────────────────────
async def handle_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ok(update):
        return
    user_id = update.effective_user.id
    text    = update.message.text

    # Manuel memory tetikleyicileri
    if _MEM_SAVE_RE.search(text):
        msg = await memory_manager.manual_save(user_id, text, _claude)
        await update.message.reply_text(msg)
        return
    if _MEM_FORGET_RE.search(text):
        msg = await memory_manager.manual_forget(user_id, text, _claude)
        await update.message.reply_text(msg)
        return
    if _MEM_VIEW_RE.search(text):
        await _mem_view(update, user_id)
        return

    save_message(user_id, "user", text)
    history    = get_history(user_id)
    user_mem   = memory_manager.load_memory(user_id)
    use_search = bool(_SEARCH_RE.search(text))

    try:
        kwargs: dict = dict(model="claude-sonnet-4-5", max_tokens=1024,
                            system=_build_system(user_mem, use_search),
                            messages=history)
        if use_search:
            kwargs["tools"] = _WEB_TOOLS
        resp  = _claude.messages.create(**kwargs)
        reply = "\n".join(b.text for b in resp.content if hasattr(b, "text")) or "Sonuç bulunamadı."
        save_message(user_id, "assistant", reply)
        await update.message.reply_text(reply)

        # Arka planda memory güncelle — kullanıcıyı beklетme
        asyncio.create_task(_update_memory_bg(user_id, get_history(user_id)))
    except Exception as e:
        log.error("Claude hatası: %s", e)
        await update.message.reply_text("Bir hata oluştu, tekrar deneyin.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    init_db()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    app = Application.builder().token(TOKEN).build()

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

    app.add_handler(ekle_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("liste", liste))
    app.add_handler(CommandHandler("sifirla", sifirla))
    app.add_handler(CommandHandler("memory",  mem_view_cmd))
    app.add_handler(CommandHandler("hafiza",  mem_view_cmd))
    app.add_handler(CommandHandler("remember", mem_save_cmd))
    app.add_handler(CommandHandler("kaydet",  mem_save_cmd))
    app.add_handler(CommandHandler("forget",  mem_forget_cmd))
    app.add_handler(CommandHandler("unut",    mem_forget_cmd))
    app.add_handler(CallbackQueryHandler(cb_done,   pattern=r"^done:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_cancel, pattern=r"^cancel:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ertele, pattern=r"^ertele:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_delay,   pattern=r"^d:\d+:\d+$"))
    app.add_handler(CommandHandler("cmd", cmd_handler))
    app.add_handler(CallbackQueryHandler(cb_cmd_ok,  pattern=r"^cmd_ok:[0-9a-f]+$"))
    app.add_handler(CallbackQueryHandler(cb_cmd_ok2, pattern=r"^cmd_ok2:[0-9a-f]+$"))
    app.add_handler(CallbackQueryHandler(cb_cmd_no,  pattern=r"^cmd_no:[0-9a-f]+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(minute_job, interval=60, first=5)

    log.info("THEIA başlatıldı.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
