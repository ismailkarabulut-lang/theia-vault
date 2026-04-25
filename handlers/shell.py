"""/cmd komutu — komut çalıştırma ve onay akışı."""

import uuid
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from gatekeeper import AuditLog, Risk, RiskClassifier, SandboxExecutor

_classifier = RiskClassifier()
_executor   = SandboxExecutor()
_audit      = AuditLog()

_pending: dict[str, dict[str, Any]] = {}

_RISK_ICON = {Risk.LOW: "✅", Risk.MEDIUM: "⚠️", Risk.HIGH: "🔴", Risk.CRITICAL: "☠️"}


async def _run_and_reply(q, command: str, risk: Risk) -> None:
    await q.edit_message_text(f"⚙️ Çalıştırılıyor...\n`{command}`", parse_mode="Markdown")
    success, output = _executor.run(command)
    text = ("✅" if success else "❌") + f" `{command}`\n\n{output}"
    if len(text) > 4000:
        text = text[:3990] + "\n…(kesildi)"
    _audit.write(command, risk, "executed", output)
    await q.edit_message_text(text, parse_mode=None)


async def cmd_handler(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
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
    uid = q.data.split(":")[1]
    pending = _pending.pop(uid, None)
    if not pending:
        await q.edit_message_text((q.message.text or "") + "\n\n⚠️ İşlem süresi doldu.")
        return
    await _run_and_reply(q, pending["cmd"], pending["risk"])


async def cb_cmd_no(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    uid = q.data.split(":")[1]
    pending = _pending.pop(uid, None)
    if pending:
        _audit.write(pending["cmd"], pending["risk"], "rejected")
    cmd = pending["cmd"] if pending else "?"
    await q.edit_message_text(f"❌ Reddedildi.\n`{cmd}`", parse_mode="Markdown")
