# THEIA VAULT — Claude Code Bağlamı

## Proje Nedir

Telegram üzerinden çalışan kişisel AI asistan botu.
Amaç: "Bu asistan beni tanıyor" hissi. Hız değil, kalite ve kişisellik.
Dedicated root'lu Android cihazda Termux üzerinde çalışıyor.
Ana model: Claude Sonnet API. Özet ajanı: Claude Haiku API.

---

## MEVCUT YAPI — DOKUNMADAN ÖNCE OKU

```
theia-vault/
  main.py                  ← Telegram bot entry point — ÇALIŞIYOR
  gatekeeper.py            ← Onay mekanizması — DOKUNMA
  requirements.txt

  core/
    config.py              ← TOKEN, API key, DB_PATH, VAULT_DIR
    db.py                  ← SQLite bağlantısı + init_db()

  handlers/
    message.py             ← Telegram mesaj handler — ana akış
    memory.py              ← /memory /kaydet /unut komutları
    schedule.py            ← Hatırlatıcı sistemi
    shell.py               ← Güvenli komut çalıştırma
    start.py               ← /start komutu

  memory/
    memory_manager.py      ← Mevcut hafıza sistemi (markdown tabanlı)
    users/                 ← {user_id}.md dosyaları (git dışı)

  .claude/                 ← Claude Code ayarları
```

### Mevcut DB Tabloları (core/db.py)
```
items         → hatırlatıcılar
checks        → hatırlatıcı kontrolleri
conversations → sohbet geçmişi (user_id, role, content, timestamp)
```

### Mevcut memory_manager.py Ne Yapıyor
- Her kullanıcı için memory/users/{user_id}.md markdown dosyası
- Her 5 mesajda Haiku ile otomatik güncelleme (should_update_memory)
- manual_save / manual_forget: kullanıcı komutuyla kayıt/silme
- asyncio.to_thread ile sync API çağrısı — bu pattern kullanılacak

---

## ENTEGRASYON PLANI

### Adım 1 — core/db.py: init_db() GENİŞLET

Mevcut 3 tabloyu silme. Sadece şunları EKLE:

```sql
CREATE TABLE IF NOT EXISTS entries (
    id           TEXT PRIMARY KEY,
    content      TEXT NOT NULL,
    summary      TEXT,
    topic_slug   TEXT,
    source       TEXT NOT NULL CHECK(source IN ('manual','telegram','gmail','drive','agent')),
    created_by   TEXT NOT NULL,
    confidence   REAL DEFAULT 1.0,
    version      INTEGER DEFAULT 1,
    deleted      INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    meta         TEXT DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    content, summary,
    content='entries', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS entries_fts_insert
AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, content, summary)
    VALUES (new.rowid, new.content, new.summary);
END;

CREATE TABLE IF NOT EXISTS topics (
    slug         TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL,
    version      INTEGER DEFAULT 1,
    entry_count  INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_entries (
    topic_slug   TEXT NOT NULL REFERENCES topics(slug),
    entry_id     TEXT NOT NULL REFERENCES entries(id),
    PRIMARY KEY (topic_slug, entry_id)
);

CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    action       TEXT NOT NULL,
    target_id    TEXT,
    actor        TEXT NOT NULL,
    status       TEXT DEFAULT 'ok',
    detail       TEXT,
    ts           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permissions (
    actor        TEXT NOT NULL,
    scope        TEXT NOT NULL,
    granted_at   TEXT NOT NULL,
    granted_by   TEXT NOT NULL,
    PRIMARY KEY (actor, scope)
);

INSERT OR IGNORE INTO permissions VALUES
    ('human',            'read',          datetime('now'), 'system'),
    ('human',            'write_entry',   datetime('now'), 'system'),
    ('human',            'delete',        datetime('now'), 'system'),
    ('human',            'admin',         datetime('now'), 'system'),
    ('haiku_summarizer', 'read',          datetime('now'), 'system'),
    ('haiku_summarizer', 'write_summary', datetime('now'), 'system'),
    ('web_agent',        'read',          datetime('now'), 'system'),
    ('web_agent',        'write_entry',   datetime('now'), 'system'),
    ('memory_agent',     'read',          datetime('now'), 'system'),
    ('orchestrator_v1',  'read',          datetime('now'), 'system'),
    ('orchestrator_v1',  'write_entry',   datetime('now'), 'system'),
    ('orchestrator_v1',  'merge_topic',   datetime('now'), 'system');

CREATE TABLE IF NOT EXISTS queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type     TEXT NOT NULL,
    payload      TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',
    attempts     INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
```

### Adım 2 — memory/vault_api.py: YENİ DOSYA

Vault CRUD + search + audit. Actor her zaman belirtilmeli.
memory_manager.py'ye dokunma — paralel çalışır.
core/db.py'deki db() sync — asyncio.to_thread ile sar (memory_manager.py ile aynı pattern).

```python
async def write_entry(entry: dict, actor: str) -> dict
async def get_entry(entry_id: str, actor: str) -> dict | None
async def soft_delete(entry_id: str, actor: str) -> bool
async def search_entries(query: str, actor: str, limit: int = 10) -> list[dict]
async def merge_to_topic(slug: str, entry_ids: list, summary: str, actor: str)
```

Her write: yaz + audit + queue'ya summarize ekle (atomik, tek transaction).

### Adım 3 — memory/permissions.py: YENİ DOSYA

```python
async def require_permission(actor: str, scope: str) -> None
    # permissions tablosuna bak, yoksa PermissionDenied + audit 'denied'

async def grant_permission(actor: str, scope: str, granted_by: str) -> None
    # yeni ajan = yeni DB kaydı, kod değişmez
```

### Adım 4 — agents/: YENİ KLASÖR

```
agents/
  __init__.py
  summarizer.py   ← queue worker, Haiku ile özet + topic_merge
  web_agent.py    ← 🌍 veya & prefix tetikli web arama
  memory_agent.py ← FTS araması + bağlam metni üretimi
```

summarizer.py asyncio loop'ta çalışır.
main.py'de bot başlarken asyncio.create_task ile başlatılır.

### Adım 5 — handlers/message.py: GENİŞLET

```python
WEB_PREFIXES = {"🌍", "&"}

# Mevcut akışa eklenenler:
# 1. prefix_parser → web_requested, clean_msg
# 2. asyncio.gather(
#      memory_agent.get_context(clean_msg),
#      web_agent.search(clean_msg) if web_requested else empty()
#    )
# 3. bağlamları sistem prompt'a enjekte et
# 4. Claude Sonnet'e gönder (mevcut conversations history ile)
# 5. cevabı Telegram'a gönder
# 6. asyncio.create_task → vault'a kaydet (cevabı bekleme)
```

### Adım 6 — memory_manager.py GEÇİŞİ (SONRA — HENÜZ YAPMA)

Vault stabil olduktan sonra:
1. migration_script.py: memory/users/*.md → entries tablosuna
   source="manual", created_by="migration"
2. handlers/memory.py komutlarını vault_api'ye yönlendir
3. memory_manager.py kaldır

---

## ALINAN KARARLAR

- Ana model: claude-sonnet-4-6
- Özet ajanı: claude-haiku-4-5-20251001 (memory_manager.py ile aynı)
- Vault kayıt of truth: lokal SQLite (mevcut DB'ye eklenir)
- Web ajanı sadece 🌍 veya & prefix ile tetiklenir
- Orchestrator'a DELETE yetkisi yok — insan onayı gerekir
- Her işlem audit log'a düşer
- Silme soft delete — gerçekten silinmez
- memory_manager.py paralel çalışır, aniden silinmez

---

## TEKNİK NOTLAR

- core/db.py sync, handlers async → asyncio.to_thread pattern
  memory_manager.py zaten bu şekilde — aynısını uygula
- gatekeeper.py ilerisi için vault write onayına entegre edilebilir
- voice.py (local, repoda yok) — ses katmanı var, vault entegrasyonu ayrıca
- Yeni ajan: grant_permission("yeni_ajan", "write_entry", "human")
- Model string'lerini core/config.py'e taşı
- Fleet (6-7 cihaz) planı var — bu repo sadece Theia cihazı

---

## ENTEGRASYON SIRASI (Bu Sırayı Bozma)

1. core/db.py → init_db() genişlet, python main.py ile test et
2. memory/vault_api.py → CRUD yaz
3. memory/permissions.py → scope kontrolü
4. agents/summarizer.py → queue worker + main.py'e create_task
5. agents/memory_agent.py → FTS arama + bağlam
6. agents/web_agent.py → web search
7. handlers/message.py → hepsini birleştir
8. Test: Telegram'dan mesaj gönder, vault'a yazıldığını doğrula
