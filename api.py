"""THEIA FastAPI katmanı — Telegram olmadan HTTP üzerinden Claude erişimi."""
import asyncio
import logging
import tempfile
from datetime import datetime, timedelta

import edge_tts
import anthropic
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from agents import memory_agent, web_agent
from agents.web_agent import has_prefix
from core.config import SYSTEM, SYSTEM_WEB, USER_ID, claude
from core.shared import _MEM_SAVE_RE, _MEM_FORGET_RE, _MEM_VIEW_RE
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


@api_router.get("/health")
async def health():
    return {"status": "ok"}


# ── VAULT ─────────────────────────────────────────────────────────────────────
@api_router.get("/vault/entries")
async def vault_entries(
    limit: int = Query(50, ge=1, le=200),
    topic: str = Query(None),
    q: str = Query(None),
):
    try:
        with db() as c:
            if q:
                rows = c.execute(
                    """SELECT e.id, e.content, e.summary, e.topic_slug, e.source,
                              e.confidence, e.created_at, e.updated_at
                       FROM entries e
                       JOIN entries_fts f ON e.rowid = f.rowid
                       WHERE f.entries_fts MATCH ? AND e.deleted=0
                       ORDER BY e.updated_at DESC LIMIT ?""",
                    (q, limit),
                ).fetchall()
            elif topic:
                rows = c.execute(
                    """SELECT e.id, e.content, e.summary, e.topic_slug, e.source,
                              e.confidence, e.created_at, e.updated_at
                       FROM entries e
                       JOIN topic_entries te ON e.id = te.entry_id
                       WHERE te.topic_slug=? AND e.deleted=0
                       ORDER BY e.updated_at DESC LIMIT ?""",
                    (topic, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    """SELECT id, content, summary, topic_slug, source,
                              confidence, created_at, updated_at
                       FROM entries WHERE deleted=0
                       ORDER BY updated_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return {"entries": [dict(r) for r in rows]}
    except Exception as e:
        log.exception("Vault entries hatası")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/vault/topics")
async def vault_topics():
    try:
        with db() as c:
            rows = c.execute(
                "SELECT slug, title, summary, entry_count, updated_at "
                "FROM topics ORDER BY entry_count DESC"
            ).fetchall()
        return {"topics": [dict(r) for r in rows]}
    except Exception as e:
        log.exception("Vault topics hatası")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/vault/stats")
async def vault_stats():
    try:
        with db() as c:
            total    = c.execute("SELECT COUNT(*) FROM entries WHERE deleted=0").fetchone()[0]
            topics_n = c.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
            sources  = c.execute(
                "SELECT source, COUNT(*) as n FROM entries WHERE deleted=0 GROUP BY source"
            ).fetchall()
            latest   = c.execute(
                "SELECT updated_at FROM entries WHERE deleted=0 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return {
            "total_entries": total,
            "total_topics":  topics_n,
            "sources":       {r["source"]: r["n"] for r in sources},
            "last_updated":  latest["updated_at"] if latest else None,
        }
    except Exception as e:
        log.exception("Vault stats hatası")
        raise HTTPException(status_code=500, detail=str(e))


# ── AUDIT ─────────────────────────────────────────────────────────────────────
@api_router.get("/audit")
async def audit_log(n: int = Query(50, ge=1, le=500)):
    try:
        with db() as c:
            rows = c.execute(
                "SELECT id, action, target_id, actor, status, detail, ts "
                "FROM audit ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()
        return {"events": [dict(r) for r in rows]}
    except Exception as e:
        log.exception("Audit log hatası")
        raise HTTPException(status_code=500, detail=str(e))


# ── CONVERSATIONS ─────────────────────────────────────────────────────────────
@api_router.get("/conversations/stats")
async def conv_stats():
    try:
        with db() as c:
            total = c.execute(
                "SELECT COUNT(*) FROM conversations WHERE user_id=?", (KAPTAN_ID,)
            ).fetchone()[0]
            today = c.execute(
                "SELECT COUNT(*) FROM conversations "
                "WHERE user_id=? AND timestamp >= date('now')",
                (KAPTAN_ID,),
            ).fetchone()[0]
            last = c.execute(
                "SELECT timestamp FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (KAPTAN_ID,),
            ).fetchone()
        return {
            "total_messages": total,
            "today":          today,
            "last_message":   last["timestamp"] if last else None,
        }
    except Exception as e:
        log.exception("Conv stats hatası")
        raise HTTPException(status_code=500, detail=str(e))


# ── DİĞER MEVCUT ENDPOINT'LER ─────────────────────────────────────────────────
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



# ── GATEKEEPER ────────────────────────────────────────────────────────────────
@api_router.get("/gatekeeper/log")
async def gatekeeper_log(n: int = Query(50, ge=1, le=500)):
    import json, os
    log_path = os.path.expanduser("~/theia/gatekeeper_log.json")
    try:
        with open(log_path) as f:
            data = json.load(f)
        return {"events": data[-n:]}
    except FileNotFoundError:
        return {"events": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── RITUALS ───────────────────────────────────────────────────────────────────
@api_router.get("/rituals")
async def rituals(status: str = Query(None)):
    try:
        with db() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM items WHERE type='ritual' AND status=? ORDER BY scheduled_time",
                    (status,)
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM items WHERE type='ritual' ORDER BY scheduled_time"
                ).fetchall()
        return {"rituals": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






# ── HUD ENDPOINT'LERİ ─────────────────────────────────────────────────────────
import json as _json
import os as _os
from datetime import datetime as _dt

@api_router.get("/status")
async def status():
    try:
        with db() as c:
            total_cmds = c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            mem_entries = c.execute("SELECT COUNT(*) FROM entries WHERE deleted=0").fetchone()[0]
        return {
            "uptime": "active",
            "total_commands": total_cmds,
            "memory_entries": mem_entries,
            "memory_users": 1,
            "superposition_state": "ACTIVE"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/gatekeeper")
async def gatekeeper():
    log_path = _os.path.expanduser("~/theia/gatekeeper_log.json")
    try:
        with open(log_path) as f:
            events = _json.load(f)
        dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for e in events:
            r = e.get("risk", "LOW")
            dist[r] = dist.get(r, 0) + 1
        hourly = [{"hour": h, "count": sum(
            1 for e in events
            if _dt.fromisoformat(e["ts"]).hour == h
        )} for h in range(24)]
        recent = sorted(events, key=lambda x: x["ts"], reverse=True)[:8]
        cmds = [{"ts": e["ts"], "cmd": e.get("cmd",""), "risk": e.get("risk","LOW"),
                 "decision": e.get("decision","").upper()} for e in recent]
        return {"risk_distribution": dist, "recent_commands": cmds, "hourly_activity": hourly}
    except FileNotFoundError:
        return {"risk_distribution": {"LOW":0,"MEDIUM":0,"HIGH":0,"CRITICAL":0},
                "recent_commands": [], "hourly_activity": [{"hour":h,"count":0} for h in range(24)]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/memory")
async def memory():
    try:
        with db() as c:
            total = c.execute("SELECT COUNT(*) FROM entries WHERE deleted=0").fetchone()[0]
        return {"total_users": 1, "total_entries": total, "users": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/activity")
async def activity():
    try:
        with db() as c:
            rows = c.execute(
                """SELECT date(ts) as day, COUNT(*) as n
                   FROM audit
                   WHERE ts >= date('now','-7 days')
                   GROUP BY day ORDER BY day"""
            ).fetchall()
        daily = []
        for r in rows:
            label = _dt.strptime(r["day"], "%Y-%m-%d").strftime("%a")
            daily.append({"label": label, "total": r["n"], "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0})
        return {"daily": daily}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/stream")
async def stream():
    try:
        with db() as c:
            rows = c.execute(
                """SELECT timestamp as ts, role, content FROM conversations
                   WHERE user_id=? ORDER BY id DESC LIMIT 6""",
                (KAPTAN_ID,)
            ).fetchall()
        items = [{
            "ts": r["ts"][11:19] if r["ts"] else "",
            "cmd": r["content"][:60],
            "risk": "LOW",
            "decision": "EXECUTED",
            "color": "#00ff88"
        } for r in rows]
        return {"stream": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)
