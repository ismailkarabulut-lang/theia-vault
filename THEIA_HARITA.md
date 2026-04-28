# THEIA SİSTEM HARİTASI
> Son güncelleme: Nisan 2026 | Versiyon: 0.6

---

## 1. SİSTEM NE YAPIYOR (tek cümle)

Termux'ta çalışan bir Telegram botu — konuşmaları hatırlıyor, komutları risk seviyesine göre filtreler, web araması yapıyor ve her mesajı Vault'a kaydediyor.

---

## 2. ÇALIŞAN SERVİSLER (şu an aktif)

| Servis | Nasıl çalışıyor | Ne yapıyor |
|--------|----------------|------------|
| `main.py` | Termux `screen` veya `nohup` | Telegram botu — tüm mesajları karşılar |
| `agents/summarizer` | `main.py` içinde `asyncio.create_task` | Arka planda özet çıkarıcı |
| Tailscale | Android servis | Telefona uzaktan erişim (kapalıyken `localhost:8000` ulaşılamaz) |

**Kurulu ama henüz başlatılmamış:**
- `api.py` — FastAPI servisi, akşam kurulacak

---

## 3. MİMARİ AKIŞ

```
Sen (Telegram)
    │
    ▼
main.py  ──► _auth() → sadece USER_ID geçer
    │
    ▼
handlers/message.py
    │
    ├─► "bunu hatırla" → vault_api.write_entry()
    ├─► "🌍" veya "&" prefix → web_agent.search()
    ├─► /cmd komutu   → handlers/shell.py
    │
    ▼
Paralel çalışır:
    ├─► memory_agent.get_context()   → Vault'tan ilgili geçmiş
    └─► web_agent.search()           → web araması (prefix varsa)
    │
    ▼
claude.messages.create()
    model: claude-sonnet-4-6
    system: SYSTEM + tarih + vault_context + web_context
    │
    ▼
Telegram'a cevap gönder
    +
vault_api.write_entry() → theia.db / entries tablosu (arka planda)
```

---

## 4. KOMUT ONAY AKIŞI (Gatekeeper)

```
/cmd <komut>
    │
    ▼
RiskClassifier.classify()
    │
    ├─► LOW      → Otomatik çalıştır, AuditLog'a yaz
    ├─► MEDIUM   → Telegram'da [Onayla] [Reddet] butonu
    ├─► HIGH     → Telegram'da 2 kez onay gerekli
    └─► CRITICAL → Direkt engelle, hiç çalıştırma
```

**Risk seviyeleri:**
- **LOW:** ls, cat, ps, df, grep, echo, python print...
- **MEDIUM:** apt install, pip, mv, chmod, docker, git push...
- **HIGH:** rm -rf, sudo rm, DROP TABLE, shred...
- **CRITICAL:** rm -rf /, dd if=/dev/zero, mkfs, fork bomb

**Gatekeeper log:** `~/theia/gatekeeper_log.json` — JSON array formatında.
Not: `AuditLog` sınıfı JSONL yazmaya hazır ama mevcut dosya eski JSON array formatıyla başladı, format korunuyor.

---

## 5. VERİTABANI (~/theia/theia.db)

| Tablo | Ne tutuyor |
|-------|-----------|
| `conversations` | Tüm Telegram mesajları (role, content, timestamp) |
| `items` | Görev / rutin / hatırlatıcılar |
| `checks` | Görev takip kayıtları |
| `pending_actions` | Kullanıcı niyetleri ("bakacağım", "yapacağım"...) |
| `entries` | Vault hafıza girdileri — her mesaj buraya da yazılıyor |
| `entries_fts` | Full-text arama indeksi (entries'e bağlı) |
| `topics` | Girdilerin toplandığı konular |
| `topic_entries` | Konu ↔ girdi ilişkisi |
| `audit` | Sistem aksiyonları |
| `permissions` | Kim ne yapabilir (human, haiku_summarizer, web_agent...) |
| `queue` | Arka plan iş kuyruğu |

**DB yolu:** `~/theia/theia.db`

---

## 6. HAFIZA SİSTEMİ

### Nasıl çalışıyor:
1. Her mesaj `conversations` tablosuna kaydedilir
2. Her mesaj `vault_api.write_entry()` ile `entries` tablosuna da yazılır
3. `memory_agent.get_context()` — yeni mesaj geldiğinde Vault'ta ilgili geçmiş aranır, system prompt'a eklenir
4. `agents/summarizer` — arka planda özet çıkarır, `topics` tablosunu günceller

### Neden Telegram'da her şeyi hatırlıyor:
`get_history(user_id, limit=20)` + `memory_agent.get_context()` — son 20 mesaj + vault bağlamı her seferinde Claude'a gönderiliyor.

### Eski sistem (artık kullanılmıyor):
`memory/memory_manager.py` — `memory/users/{user_id}.md` dosyalarına yazıyordu. `vault_api`'ye geçildi, dosyalar hâlâ duruyor ama aktif değil.

---

## 7. DOSYA YAPISI

```
~/theia-vault/              ← repo kök
├── main.py                 ← bot giriş noktası
├── api.py                  ← FastAPI HTTP katmanı (port 8000)
├── gatekeeper.py           ← risk sınıflandırma + sandbox + audit
├── voice.py                ← yerel sesli asistan (Vosk STT + Piper TTS, sadece local)
├── requirements.txt
├── .env                    ← TOKEN, CHAT_ID, USER_ID, ANTHROPIC_API_KEY
├── CLAUDE.md               ← Claude Code kuralları
├── THEIA_HARITA.md         ← bu dosya
│
├── core/
│   ├── config.py           ← ayarlar, claude istemci, SYSTEM prompt
│   ├── db.py               ← SQLite bağlantısı, tüm tablo şemaları
│   └── pending.py          ← niyet takip tablosu
│
├── handlers/
│   ├── message.py          ← genel mesaj işleyici (ana akış burada)
│   ├── shell.py            ← /cmd komutu + Gatekeeper entegrasyonu
│   ├── memory.py           ← /memory /hafiza /kaydet /unut komutları
│   ├── schedule.py         ← /liste /ekle /tamam görev yönetimi
│   └── start.py            ← /start komutu
│
├── agents/
│   ├── summarizer.py       ← arka plan özet ajanı (Haiku)
│   ├── memory_agent.py     ← vault bağlam çekici
│   └── web_agent.py        ← web arama (🌍 veya & prefix ile tetiklenir)
│
└── memory/
    ├── vault_api.py        ← entries/topics CRUD (aktif sistem)
    └── memory_manager.py   ← eski hafıza sistemi (pasif)

~/theia/                    ← veri dizini (git dışı)
├── theia.db                ← SQLite veritabanı
├── .env                    ← gizli anahtarlar
└── gatekeeper_log.json     ← audit log
```

---

## 8. WEB ARAYÜZÜ (theia_vault_5.html)

### Modüller ve durumları:

| Modül | Renk | Durum | Backend |
|-------|------|-------|---------|
| CHAT | Mor | ⏳ api.py kurulunca çalışır | `POST /api/chat` → `localhost:8000` |
| THEIA TALK | Mor | ✅ Çalışır | Anthropic API direkt (kullanıcı key'i, localStorage) |
| WOLFSTREET | Gümüş/Amber | 🔶 Mock data | Gmail entegrasyonu bekliyor |
| RITUALS | Turuncu | ⏳ Beklemede | `items` tablosu hazır, UI yok |
| GATEKEEPER | Kırmızı | ⏳ Beklemede | `gatekeeper_log.json` var, endpoint yok |
| VAULT | Mor | ⏳ Beklemede | `entries`/`topics` tablosu hazır, api.py kurulmadı |
| PIGEON | Mavi | ⏳ Beklemede | Telegram bot var, onay kuyruğu var |
| AUDIT LOG | Yeşil | ⏳ Beklemede | `audit` tablosu hazır, endpoint yok |

### Nasıl açılıyor:
Tarayıcıda direkt HTML dosyası olarak. Sunucu gerektirmiyor — sadece Chat/Vault modülleri `api.py`'a bağlanıyor.

### ⚠️ Bekleyen düzeltme:
HTML'deki Chat modülü hâlâ `localhost:8585` kullanıyor. `8000` olarak güncellenmesi lazım.

### Tailscale bağlantısı:
Telefon dışarıdayken `localhost:8000`'e ulaşmak için Tailscale açık olmalı.

---

## 9. BAĞLANTILAR VE KİMDEN KİME

```
[Sen]
  │
  ├── Telegram ──────────────► main.py (Termux/Android)
  │                                │
  │                                ├── Anthropic API (claude-sonnet-4-6)
  │                                ├── theia.db (SQLite)
  │                                └── gatekeeper_log.json
  │
  ├── Tarayıcı ──────────────► theia_vault_5.html (lokal dosya)
  │                                │
  │                                ├── CHAT → localhost:8000/api/chat
  │                                │         (Tailscale üzerinden telefona)
  │                                │
  │                                └── TALK → api.anthropic.com/v1/messages
  │                                           (direkt, senin key'in)
  │
  └── Tailscale ─────────────► Telefonun Tailscale IP'si (100.x.x.x)
                               localhost:8000 buradan erişilir
```

---

## 10. STACK

| Katman | Teknoloji | Not |
|--------|-----------|-----|
| Dil | Python 3.13 | |
| Telegram | python-telegram-bot 22.7 | |
| HTTP API | FastAPI + uvicorn | port 8000 |
| Ana model | claude-sonnet-4-6 | Telegram konuşma |
| Hafıza modeli | claude-haiku-4-5-20251001 | summarizer + api.py |
| Veritabanı | SQLite | ~/theia/theia.db |
| Ses (local) | Vosk STT + Piper TTS + edge-tts | voice.py, deploy edilmez |
| Ağ tüneli | Tailscale | Android |

---

## 11. YAPILACAKLAR SIRALI

| # | İş | Bağımlılık |
|---|-----|-----------|
| 1 | `pip install fastapi uvicorn` → `api.py` başlat | — |
| 2 | HTML'de port 8585 → 8000 güncelle | api.py çalışıyor olmalı |
| 3 | HTML'de localStorage ekle (konuşmalar kaybolmasın) | — |
| 4 | Gatekeeper workspace UI | api.py |
| 5 | Vault workspace UI | api.py |
| 6 | Rituals workspace UI | api.py |
| 7 | Pigeon workspace UI | api.py |
| 8 | Wolfstreet → Gmail bağlantısı | En son, en karmaşık |
| 9 | README güncelle | Hepsi bittikten sonra |

---

## 12. HIZLI BAŞLATMA (Termux)

```bash
# Theia bot
cd ~/theia-vault
screen -S theia
python main.py
# Ctrl+A, D

# API servisi
screen -S theia-api
uvicorn api:app --host 0.0.0.0 --port 8000
# Ctrl+A, D

# Servisleri kontrol et
screen -ls

# Tailscale
tailscale up
```

---

## 13. ÖNEMLİ KARARLAR / NOTLAR

- **Groq kaldırıldı** — tamamen Anthropic API
- **Tek kullanıcı** — `USER_ID` ile kimlik doğrulama
- **Web araması** — mesajın başına 🌍 veya & koy
- **Vault kayıt** — her konuşma otomatik kaydediliyor, `/kaydet` gerekmez
- **Talk modülü** — Anthropic key localStorage'da, koda gömülmez, GitHub'a gitmez
- **voice.py** — sadece local, Render'a deploy edilmez
- **CLAUDE.md güncellemesi gerekiyor** — FastAPI/uvicorn doğru, DB tabloları eksik, model adları eski, vault_api sistemi eklenmeli
