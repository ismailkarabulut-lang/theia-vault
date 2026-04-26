"""THEIA FastAPI katmanı — Telegram olmadan HTTP üzerinden Claude erişimi."""
import asyncio
import logging
import re
import tempfile
from datetime import datetime, timedelta

import edge_tts
import anthropic
import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import memory_agent, web_agent
from agents.web_agent import has_prefix
from core.config import SYSTEM, SYSTEM_WEB, USER_ID, claude
from handlers.schedule import dt_str, parse_time
from core.db import db, get_history, save_message
from memory import vault_api

log = logging.getLogger(__name__)

# Telegram user_id ile aynı — conversations tablosunu ortak kullanır
KAPTAN_ID = USER_ID

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")

api_router = APIRouter(prefix="/api")

_MEM_SAVE_RE   = re.compile(r"bunu hatırla|bunu kaydet|önemli:", re.IGNORECASE)
_MEM_FORGET_RE = re.compile(r"bunu unut|bunu sil memory'den", re.IGNORECASE)
_MEM_VIEW_RE   = re.compile(r"ne hatırlıyorsun", re.IGNORECASE)

VOICES = {
    "erkek": "tr-TR-AhmetNeural",
    "kadin": "tr-TR-EmelNeural",
}


class ChatRequest(BaseModel):
    message: str
    tts: bool = False


class ItemCreate(BaseModel):
    type: str
    content: str
    scheduled_time: str
    check_after: int = 0
    recurrence: str = "none"


class DelayRequest(BaseModel):
    minutes: int


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


async def _claude_reply(text: str) -> str:
    web_requested, clean_msg = has_prefix(text)

    save_message(KAPTAN_ID, "user", clean_msg)
    history = get_history(KAPTAN_ID)

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
    save_message(KAPTAN_ID, "assistant", reply)

    asyncio.create_task(_save_to_vault(clean_msg, reply))
    return reply


async def _tts(text: str, voice_key: str) -> str:
    voice = VOICES.get(voice_key, VOICES["kadin"])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()
    await edge_tts.Communicate(text, voice).save(tmp.name)
    return tmp.name


@api_router.post("/chat")
async def chat(req: ChatRequest):
    try:
        if _MEM_SAVE_RE.search(req.message):
            content = re.sub(r"^.*?(bunu hatırla|bunu kaydet|önemli:):?\s*", "", req.message,
                             flags=re.IGNORECASE).strip() or req.message
            await vault_api.write_entry({"content": content, "source": "manual"}, actor="human")
            reply = "✓ Kaydedildi."

        elif _MEM_FORGET_RE.search(req.message):
            query   = re.sub(r"^.*?(bunu unut|bunu sil memory'den)\s*", "", req.message,
                             flags=re.IGNORECASE).strip() or req.message
            results = await vault_api.search_entries(query, actor="human", limit=3)
            if results:
                await vault_api.soft_delete(results[0]["id"], actor="human")
                reply = f"✓ Silindi: {results[0]['content'][:80]!r}"
            else:
                reply = "İlgili bir kayıt bulunamadı."

        elif _MEM_VIEW_RE.search(req.message):
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
            reply = await _claude_reply(req.message)

        if not req.tts:
            return {"response": reply}

        audio_path = await _tts(reply, "kadin")
        return FileResponse(audio_path, media_type="audio/mpeg", filename="reply.mp3")

    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limit, biraz bekle.")
    except Exception as e:
        log.exception("API hatası")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/reminders")
async def reminders():
    """Zamanı gelmiş, henüz gönderilmemiş kontrol bildirimlerini döndür."""
    try:
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
        with db() as c:
            rows = c.execute(
                """SELECT ch.id, ch.item_id, i.content, i.type, ch.check_at
                   FROM checks ch
                   JOIN items i ON i.id = ch.item_id
                   WHERE ch.status = 'pending' AND ch.check_at <= ?""",
                (now_s,)
            ).fetchall()
            for row in rows:
                c.execute(
                    "UPDATE checks SET status='sent' WHERE id=?",
                    (row["id"],)
                )
        return {"reminders": [
            {"id": r["id"], "item_id": r["item_id"],
             "content": r["content"], "type": r["type"],
             "check_at": r["check_at"]}
            for r in rows
        ]}
    except Exception as e:
        log.exception("Reminders hatası")
        return {"reminders": []}


@app.post("/items")
async def create_item(req: ItemCreate):
    try:
        dt = parse_time(req.scheduled_time)
        if dt is None:
            raise HTTPException(status_code=400, detail="Geçersiz saat formatı.")
        with db() as c:
            cur = c.execute(
                "INSERT INTO items (type, content, scheduled_time, check_after, recurrence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (req.type, req.content, dt_str(dt), req.check_after,
                 req.recurrence, dt_str(datetime.now())),
            )
            item_id = cur.lastrowid
        return {"ok": True, "id": item_id}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Item ekleme hatası")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/items")
async def list_items():
    try:
        with db() as c:
            rows = c.execute(
                "SELECT * FROM items WHERE status IN ('active','triggered') ORDER BY scheduled_time"
            ).fetchall()
        return {"items": [dict(r) for r in rows]}
    except Exception as e:
        log.exception("Item listeleme hatası")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/items/{item_id}/complete")
async def complete_item(item_id: int):
    try:
        with db() as c:
            c.execute("UPDATE items SET status='completed' WHERE id=?", (item_id,))
        return {"ok": True}
    except Exception as e:
        log.exception("Item tamamlama hatası")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/items/{item_id}/delay")
async def delay_item(item_id: int, req: DelayRequest):
    try:
        new_time = dt_str(datetime.now() + timedelta(minutes=req.minutes))
        with db() as c:
            c.execute(
                "UPDATE items SET scheduled_time=?, status='active' WHERE id=?",
                (new_time, item_id),
            )
        return {"ok": True}
    except Exception as e:
        log.exception("Item erteleme hatası")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pendings")
async def get_pendings():
    """Çözümlenmemiş niyetleri Theia'nın sesiyle döndür."""
    try:
        from core.pending import get_open_pendings
        items = get_open_pendings(KAPTAN_ID)
        if not items:
            return {"pendings": []}

        pending_texts = "\n".join(
            f"- [{p['created_at']}]: {p['text']}"
            for p in items[:3]
        )
        prompt = (
            f"Kaptan şu niyetleri belirtti ama uzun süredir dönmedi:\n"
            f"{pending_texts}\n\n"
            f"Theia olarak tek bir doğal Türkçe cümleyle sor. "
            f"Saygılı, meraklı, vazgeçmeyen ton. "
            f"'Kaptan' diye başla. Maksimum 2 cümle."
        )
        resp = await asyncio.to_thread(
            claude.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        message = resp.content[0].text.strip()
        return {"pendings": [{"text": message, "ids": [p["id"] for p in items[:3]]}]}
    except Exception as e:
        log.exception("Pendings hatası")
        return {"pendings": []}


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@api_router.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8585, reload=False)
