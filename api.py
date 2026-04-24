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

from core.config import SYSTEM, SYSTEM_WEB, WEB_TOOLS, claude
from core.db import get_history, save_message
from handlers.memory import memory_manager

log = logging.getLogger(__name__)
app = FastAPI()

_SEARCH_RE = re.compile(r"\b(ara|bul|güncel|hava)\b|\bkur(?!ul|ban)", re.IGNORECASE)
_MEM_SAVE_RE = re.compile(r"bunu hatırla|bunu kaydet|önemli:", re.IGNORECASE)
_MEM_FORGET_RE = re.compile(r"bunu unut|bunu sil memory'den", re.IGNORECASE)
_MEM_VIEW_RE = re.compile(r"ne hatırlıyorsun", re.IGNORECASE)

VOICES = {
    "erkek": "tr-TR-AhmetNeural",
    "kadin": "tr-TR-EmelNeural",
}


class ChatRequest(BaseModel):
    user_id: int
    text: str
    voice: str = "kadin"
    tts: bool = True


def _build_system(user_memory: str, web: bool) -> str:
    base = SYSTEM_WEB if web else SYSTEM
    if not user_memory:
        return base
    return (
        base
        + f"\n\nBu kullanıcı hakkında bildiğin bilgiler:\n{user_memory}\n\n"
        "Bu bilgileri doğal olarak kullan."
    )


async def _claude_reply(user_id: int, text: str) -> str:
    save_message(user_id, "user", text)
    history = get_history(user_id)
    user_mem = memory_manager.load_memory(user_id)
    use_search = bool(_SEARCH_RE.search(text))

    kwargs = dict(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=_build_system(user_mem, use_search),
        messages=history,
    )
    if use_search:
        kwargs["tools"] = WEB_TOOLS

    resp = claude.messages.create(**kwargs)
    reply = "\n".join(b.text for b in resp.content if hasattr(b, "text")) or "Sonuç bulunamadı."
    save_message(user_id, "assistant", reply)

    asyncio.create_task(_memory_bg(user_id, get_history(user_id)))
    return reply


async def _memory_bg(user_id: int, history: list) -> None:
    if memory_manager.should_update_memory(user_id, history):
        new_mem = await memory_manager.extract_memory_update(user_id, history, claude)
        if new_mem:
            memory_manager.save_memory(user_id, new_mem)


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
            reply = await memory_manager.manual_save(req.user_id, req.text, claude)
        elif _MEM_FORGET_RE.search(req.text):
            reply = await memory_manager.manual_forget(req.user_id, req.text, claude)
        elif _MEM_VIEW_RE.search(req.text):
            reply = memory_manager.load_memory(req.user_id) or "Henüz bir şey kaydetmedim."
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