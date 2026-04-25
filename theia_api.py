"""
THEIA HUD API — theia-vault için web arayüzü backend'i.
Mevcut gatekeeper_log.json + bot state'i okuyarak HUD'a veri sağlar.

Kurulum:
    pip install fastapi uvicorn

Çalıştırma:
    uvicorn theia_api:app --host 0.0.0.0 --port 8585 --reload

Veya arka planda:
    nohup uvicorn theia_api:app --host 0.0.0.0 --port 8585 > theia_hud.log 2>&1 &
"""

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.staticfiles import StaticFiles

# ── Yapılandırma ─────────────────────────────────────────────────────────────
BASE_DIR = Path.home() / "theia"
AUDIT_LOG = BASE_DIR / "gatekeeper_log.json"
MEMORY_DIR = Path.home() / "theia-vault" / "memory" / "users"
BOT_STATE_FILE = BASE_DIR / "bot_state.json"  # opsiyonel: manuel yazılabilir

START_TIME = time.time()

app = FastAPI(title="Theia HUD API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def load_audit_log() -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    try:
        return json.loads(AUDIT_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def uptime_str() -> str:
    secs = int(time.time() - START_TIME)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def memory_user_count() -> int:
    if not MEMORY_DIR.exists():
        return 0
    return len(list(MEMORY_DIR.glob("*")))


def memory_total_entries() -> int:
    if not MEMORY_DIR.exists():
        return 0
    total = 0
    for f in MEMORY_DIR.glob("*"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                total += len(data)
            elif isinstance(data, dict):
                total += len(data.get("entries", data.get("memories", [])))
        except Exception:
            pass
    return total


# ── Endpoint'ler ──────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    """Bot ve sistem genel durumu."""
    records = load_audit_log()
    last_cmd = records[-1] if records else None

    return {
        "system": "THEIA CORE SYSTEM",
        "status": "ONLINE",
        "uptime": uptime_str(),
        "api_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_commands": len(records),
        "last_command": last_cmd,
        "memory_users": memory_user_count(),
        "memory_entries": memory_total_entries(),
        "superposition_state": "ACTIVE",
    }


@app.get("/api/gatekeeper")
def get_gatekeeper():
    """Risk sınıflandırma istatistikleri ve son komutlar."""
    records = load_audit_log()

    risk_counts = Counter(r.get("risk", "UNKNOWN") for r in records)
    decision_counts = Counter(r.get("decision", "UNKNOWN") for r in records)

    # Son 20 komut (yeniden eskiye)
    recent = records[-20:][::-1]

    # Son 24 saatin saatlik dağılımı
    hourly: dict[int, int] = defaultdict(int)
    cutoff = datetime.now() - timedelta(hours=24)
    for r in records:
        try:
            ts = datetime.fromisoformat(r["ts"])
            if ts >= cutoff:
                hourly[ts.hour] += 1
        except Exception:
            pass

    hourly_list = [{"hour": h, "count": hourly.get(h, 0)} for h in range(24)]

    return {
        "risk_distribution": {
            "LOW": risk_counts.get("LOW", 0),
            "MEDIUM": risk_counts.get("MEDIUM", 0),
            "HIGH": risk_counts.get("HIGH", 0),
            "CRITICAL": risk_counts.get("CRITICAL", 0),
        },
        "decision_distribution": dict(decision_counts),
        "recent_commands": recent,
        "hourly_activity": hourly_list,
    }


@app.get("/api/memory")
def get_memory():
    """Hafıza sistemi durumu."""
    users = []
    if MEMORY_DIR.exists():
        for f in MEMORY_DIR.glob("*"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entry_count = 0
                if isinstance(data, list):
                    entry_count = len(data)
                elif isinstance(data, dict):
                    entry_count = len(data.get("entries", data.get("memories", [])))
                users.append({
                    "user_id": f.stem,
                    "entries": entry_count,
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%H:%M:%S"),
                })
            except Exception:
                pass

    return {
        "total_users": len(users),
        "total_entries": sum(u["entries"] for u in users),
        "users": users,
    }


@app.get("/api/activity")
def get_activity():
    """Son 7 günlük günlük aktivite."""
    records = load_audit_log()
    daily: dict[str, dict] = defaultdict(lambda: {"total": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0})

    for r in records:
        try:
            day = r["ts"][:10]
            daily[day]["total"] += 1
            risk = r.get("risk", "MEDIUM")
            daily[day][risk] = daily[day].get(risk, 0) + 1
        except Exception:
            pass

    # Son 7 gün
    days = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        entry = daily.get(d, {"total": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0})
        entry["date"] = d
        entry["label"] = (datetime.now() - timedelta(days=i)).strftime("%a")
        days.append(entry)

    return {"daily": days}


@app.get("/api/stream")
def get_stream():
    """Son mesaj akışı — chat log veya audit log son satırları."""
    records = load_audit_log()
    last_10 = records[-10:][::-1]

    stream = []
    for r in last_10:
        risk = r.get("risk", "MEDIUM")
        color_map = {"LOW": "#00ff88", "MEDIUM": "#00cfff", "HIGH": "#ffaa00", "CRITICAL": "#ff3355"}
        stream.append({
            "ts": r.get("ts", ""),
            "cmd": r.get("cmd", ""),
            "risk": risk,
            "decision": r.get("decision", ""),
            "color": color_map.get(risk, "#00cfff"),
        })

    return {"stream": stream}


# ── Sağlık kontrolü ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.now().isoformat()}


# ── Chat endpoint ─────────────────────────────────────────────────────────────
import anthropic as _anthropic

@app.post("/api/chat")
async def chat(payload: dict):
    msg = payload.get("message", "").strip()
    if not msg:
        return {"response": "Mesaj boş."}
    try:
        client = _anthropic.Anthropic()
        result = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=f"Sen Theia'sın — Kaptan İsmail'in kişisel AI asistanı. Kısa, net, Türkçe cevap ver. Şu anki tarih ve saat: {datetime.now().strftime('%Y-%m-%d %H:%M')}. Sistem adı: theia-core.",
            messages=[{"role": "user", "content": msg}],
        )
        return {"response": result.content[0].text}
    except Exception as e:
        return {"response": f"Hata: {e}"}

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Screenshot endpoint ───────────────────────────────────────────────────────
import base64
import subprocess as _sp

@app.post("/api/screenshot")
async def screenshot(payload: dict = {}):
    question = payload.get("question", "Bu ekranda ne görüyorsun? Hata varsa açıkla.")
    try:
        # Ekran görüntüsü al
        _sp.run(["scrot", "/tmp/theia_screen.png", "--overwrite"], check=True)
        # Base64'e çevir
        with open("/tmp/theia_screen.png", "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        # Claude vision API
        client = _anthropic.Anthropic()
        result = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=f"Sen Theia'sın — Kaptan İsmail'in AI asistanı. Ekran görüntüsünü analiz et, Türkçe kısa ve net yanıt ver. Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": question}
                ]
            }]
        )
        return {"response": result.content[0].text}
    except Exception as e:
        return {"response": f"Hata: {e}"}


# ── Screenshot endpoint ───────────────────────────────────────────────────────
import base64
import subprocess as _sp

@app.post("/api/screenshot")
async def screenshot(payload: dict = {}):
    question = payload.get("question", "Bu ekranda ne görüyorsun? Hata varsa açıkla.")
    try:
        # Ekran görüntüsü al
        _sp.run(["scrot", "/tmp/theia_screen.png", "--overwrite"], check=True)
        # Base64'e çevir
        with open("/tmp/theia_screen.png", "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        # Claude vision API
        client = _anthropic.Anthropic()
        result = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=f"Sen Theia'sın — Kaptan İsmail'in AI asistanı. Ekran görüntüsünü analiz et, Türkçe kısa ve net yanıt ver. Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": question}
                ]
            }]
        )
        return {"response": result.content[0].text}
    except Exception as e:
        return {"response": f"Hata: {e}"}
