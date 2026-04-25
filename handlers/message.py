"""Genel mesaj işleyici — Claude API entegrasyonu."""

import asyncio
import logging
import re
from datetime import datetime

import anthropic
from telegram import Update
from telegram.ext import ContextTypes

from core.config import SYSTEM, SYSTEM_WEB, WEB_TOOLS, claude
from core.db import get_history, save_message
from core.pending import add_pending
from handlers.memory import _mem_view, memory_manager

log = logging.getLogger(__name__)

_SEARCH_RE     = re.compile(r"\b(ara|bul|güncel|hava)\b|\bkur(?!ul|ban)", re.IGNORECASE)
_MEM_SAVE_RE   = re.compile(r"bunu hatırla|bunu kaydet|önemli:", re.IGNORECASE)
_MEM_FORGET_RE = re.compile(r"bunu unut|bunu sil memory'den", re.IGNORECASE)
_MEM_VIEW_RE   = re.compile(r"ne hatırlıyorsun", re.IGNORECASE)
_INTENT_RE     = re.compile(
    r"\b(bakacağım|bakarım|bakayım"
    r"|yapacağım|yaparım|yapayım"
    r"|deneyeceğim|denerim|deneyeyim"
    r"|hallederim|halledeceğim"
    r"|araştıracağım|araştırırım"
    r"|düşüneceğim|düşüneyim"
    r"|ekleyeceğim|eklerim"
    r"|yazacağım|yazarım)\b",
    re.IGNORECASE,
)


def _build_system(user_memory: str, web: bool) -> str:
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    base = (SYSTEM_WEB if web else SYSTEM) + f"\n\nŞu anki tarih ve saat: {now} (UTC+3)"
    if not user_memory:
        return base
    return (
        base
        + f"\n\nBu kullanıcı hakkında bildiğin bilgiler:\n{user_memory}\n\n"
        "Bu bilgileri doğal olarak kullan, her seferinde 'biliyorum ki...' deme."
    )


async def _update_memory_bg(user_id: int, history: list) -> None:
    if memory_manager.should_update_memory(user_id, history):
        new_mem = await memory_manager.extract_memory_update(user_id, history, claude)
        if new_mem:
            memory_manager.save_memory(user_id, new_mem)


async def handle_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text    = update.message.text

    if _MEM_SAVE_RE.search(text):
        msg = await memory_manager.manual_save(user_id, text, claude)
        await update.message.reply_text(msg)
        return
    if _MEM_FORGET_RE.search(text):
        msg = await memory_manager.manual_forget(user_id, text, claude)
        await update.message.reply_text(msg)
        return
    if _MEM_VIEW_RE.search(text):
        await _mem_view(update, user_id)
        return

    if _INTENT_RE.search(text):
        add_pending(user_id, text)

    save_message(user_id, "user", text)
    history    = get_history(user_id)
    user_mem   = memory_manager.load_memory(user_id)
    use_search = bool(_SEARCH_RE.search(text))

    try:
        kwargs: dict = dict(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            system=_build_system(user_mem, use_search),
            messages=history,
        )
        if use_search:
            kwargs["tools"] = WEB_TOOLS
        resp  = await asyncio.to_thread(claude.messages.create, **kwargs)
        reply = "\n".join(b.text for b in resp.content if hasattr(b, "text")) or "Sonuç bulunamadı."
        save_message(user_id, "assistant", reply)
        await update.message.reply_text(reply)

        asyncio.create_task(_update_memory_bg(user_id, get_history(user_id)))
    except anthropic.RateLimitError:
        log.warning("Claude rate limit aşıldı: user_id=%s", user_id)
        await update.message.reply_text("Şu an yoğunluk var, biraz sonra tekrar deneyin.")
    except anthropic.APIStatusError as e:
        log.error("Claude API hatası: status=%s user_id=%s", e.status_code, user_id)
        await update.message.reply_text("Bir hata oluştu, tekrar deneyin.")
    except anthropic.APIConnectionError:
        log.error("Claude API bağlantı hatası: user_id=%s", user_id)
        await update.message.reply_text("Bağlantı hatası, tekrar deneyin.")
    except Exception:
        log.exception("Beklenmeyen hata (handle_message): user_id=%s", user_id)
        await update.message.reply_text("Bir hata oluştu, tekrar deneyin.")
