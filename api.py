"""THEIA FastAPI katmanı — Telegram olmadan HTTP üzerinden Claude erişimi."""
import asyncio
import logging
import re
import tempfile

import edge_tts
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents import memory_agent, web_agent
from agents.web_agent import has_prefix
from core.config import SYSTEM, SYSTEM_WEB, claude
from core.db import get_history, save_message
from memory import vault_api

log = logging.getLogger(__name__)
app = FastAPI()

_MEM_SAVE_RE   = re.compile(r"bunu hatırla|bunu kaydet|önemli:", re.IGNORECASE)
_MEM_FORGET_RE = re.compile(r"bunu unut|bunu sil memory'den", re.IGNORECASE)
_MEM_VIEW_RE   = re.compile(r"ne hatırlıyorsun", re.IGNORECASE)

VOICES = {
    "erkek": "tr-TR-AhmetNeural",
    "kadin": "tr-TR-EmelNeural",
}


class ChatRequest(BaseModel):
    user_id: int
    text: str
    voice: str = "kadin"
    tts: bool = True


def _build_system(web: bool, vault_context: str = "", web_context: str = "") -> str:
    base = SYSTEM_WEB if web else SYSTEM
    if vault_context:
        base += f"\n\n{vault_context}"
    if web_context:
        base += f"\n\n{web_context}"
    return base


async def _empty() -> str:
    return ""


async def _save_to_vault(user_msg: str, assistant_reply: str) -> None:
    try:
        await vault_api.write_entry({"content": user_msg, "source": "telegram"}, actor="human")
        await vault_api.write_entry({"content": assistant_reply, "source": "telegram"}, actor="orchestrator_v1")
    except Exception:
        log.exception("vault kayıt başarısız")


async def _claude_reply(user_id: int, text: str) -> str:
    web_requested, clean_msg = has_prefix(text)

    save_message(user_id, "user", clean_msg)
    history = get_history(user_id)

    mem_ctx, web_ctx = await asyncio.gather(
        memory_agent.get_context(clean_msg),
        web_agent.search(clean_msg) if web_requested else _empty(),
    )

    resp = await asyncio.to_thread(
        claude.messages.create,
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=_build_system(web=web_requested and bool(web_ctx),
                             vault_context=mem_ctx, web_context=web_ctx),
        messages=history,
    )
    reply = "\n".join(b.text for b in resp.content if hasattr(b, "text")) or "Sonuç bulunamadı."
    save_message(user_id, "assistant", reply)

    asyncio.create_task(_save_to_vault(clean_msg, reply))
    return reply


async def _tts(text: str, voice_key: str) -> str:
    voice = VOICES.get(voice_key, VOICES["kadin"])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()
    await edge_tts.Communicate(text, voice).save(tmp.name)
    return tmp.name


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        if _MEM_SAVE_RE.search(req.text):
            content = re.sub(r"^.*?(bunu hatırla|bunu kaydet|önemli:):?\s*", "", req.text,
                             flags=re.IGNORECASE).strip() or req.text
            await vault_api.write_entry({"content": content, "source": "manual"}, actor="human")
            reply = "✓ Kaydedildi."

        elif _MEM_FORGET_RE.search(req.text):
            query   = re.sub(r"^.*?(bunu unut|bunu sil memory'den)\s*", "", req.text,
                             flags=re.IGNORECASE).strip() or req.text
            results = await vault_api.search_entries(query, actor="human", limit=3)
            if results:
                await vault_api.soft_delete(results[0]["id"], actor="human")
                reply = f"✓ Silindi: {results[0]['content'][:80]!r}"
            else:
                reply = "İlgili bir kayıt bulunamadı."

        elif _MEM_VIEW_RE.search(req.text):
            from handlers.memory import _sync_recent
            entries = await asyncio.to_thread(_sync_recent, 10)
            if entries:
                lines = ["Son kayıtlar:"] + [
                    f"• {e.get('summary') or e['content'][:120]}" for e in entries
                ]
                reply = "\n".join(lines)
            else:
                reply = "Henüz hiçbir şey kaydetmedim."

        else:
            reply = await _claude_reply(req.user_id, req.text)

        if not req.tts:
            return {"reply_text": reply}

        audio_path = await _tts(reply, req.voice)
        return FileResponse(audio_path, media_type="audio/mpeg", filename="reply.mp3")

    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limit, biraz bekle.")
    except Exception as e:
        log.exception("API hatası user_id=%s", req.user_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}
