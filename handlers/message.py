"""Genel mesaj işleyici — Claude API entegrasyonu."""

import asyncio
import logging
import re
from datetime import datetime

import anthropic
from telegram import Update
from telegram.ext import ContextTypes

from agents import memory_agent, web_agent
from agents.web_agent import has_prefix
from core.config import SYSTEM, SYSTEM_WEB, claude
from core.db import get_history, save_message
from core.pending import add_pending
from handlers.memory import _mem_view
from memory import vault_api

log = logging.getLogger(__name__)

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


def _build_system(
    user_memory: str,
    web: bool,
    vault_context: str = "",
    web_context: str = "",
) -> str:
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    base = (SYSTEM_WEB if web else SYSTEM) + f"\n\nŞu anki tarih ve saat: {now} (UTC+3)"
    if user_memory:
        base += (
            f"\n\nBu kullanıcı hakkında bildiğin bilgiler:\n{user_memory}\n\n"
            "Bu bilgileri doğal olarak kullan, her seferinde 'biliyorum ki...' deme."
        )
    if vault_context:
        base += f"\n\n{vault_context}"
    if web_context:
        base += f"\n\n{web_context}"
    return base


async def _empty() -> str:
    return ""


async def _save_to_vault(user_msg: str, assistant_reply: str) -> None:
    try:
        await vault_api.write_entry(
            {"content": user_msg, "source": "telegram"},
            actor="human",
        )
        await vault_api.write_entry(
            {"content": assistant_reply, "source": "telegram"},
            actor="orchestrator_v1",
        )
    except Exception:
        log.exception("vault kayıt başarısız")


async def handle_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text    = update.message.text

    # Memory komutları — öncelikli, prefix parse'dan önce
    if _MEM_SAVE_RE.search(text):
        content = re.sub(r"^.*?(bunu hatırla|bunu kaydet|önemli:):?\s*", "", text, flags=re.IGNORECASE).strip() or text
        await vault_api.write_entry({"content": content, "source": "manual"}, actor="human")
        await update.message.reply_text("✓ Kaydedildi.")
        return
    if _MEM_FORGET_RE.search(text):
        query   = re.sub(r"^.*?(bunu unut|bunu sil memory'den)\s*", "", text, flags=re.IGNORECASE).strip() or text
        results = await vault_api.search_entries(query, actor="human", limit=3)
        if results:
            await vault_api.soft_delete(results[0]["id"], actor="human")
            await update.message.reply_text(f"✓ Silindi: {results[0]['content'][:80]!r}")
        else:
            await update.message.reply_text("İlgili bir kayıt bulunamadı.")
        return
    if _MEM_VIEW_RE.search(text):
        await _mem_view(update, user_id)
        return

    # 1. Prefix parse: 🌍 / & → web_requested, clean_msg
    web_requested, clean_msg = has_prefix(text)

    if _INTENT_RE.search(clean_msg):
        add_pending(user_id, clean_msg)

    save_message(user_id, "user", clean_msg)
    history  = get_history(user_id)

    # 2. Paralel: vault bağlamı + web araması (sadece prefix varsa)
    mem_ctx, web_ctx = await asyncio.gather(
        memory_agent.get_context(clean_msg),
        web_agent.search(clean_msg) if web_requested else _empty(),
    )

    # 3. Sistem prompt'a enjekte et
    system = _build_system(
        "",
        web=web_requested and bool(web_ctx),
        vault_context=mem_ctx,
        web_context=web_ctx,
    )

    try:
        # 4. Claude Sonnet — web araması web_agent'ta yapıldı, WEB_TOOLS gerekmez
        resp = await asyncio.to_thread(
            claude.messages.create,
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system,
            messages=history,
        )
        reply = "\n".join(b.text for b in resp.content if hasattr(b, "text")) or "Sonuç bulunamadı."
        save_message(user_id, "assistant", reply)

        # 5. Telegram'a gönder
        await update.message.reply_text(reply)

        # 6. Vault'a kaydet — arka planda, cevabı bekleme
        asyncio.create_task(_save_to_vault(clean_msg, reply))

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
