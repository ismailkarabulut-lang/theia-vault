# THEIA SİSTEM HARİTASI
> Son güncelleme: Mayıs 2026 | Versiyon: 0.9

---

## 1. SİSTEM NE YAPIYOR (tek cümle)

Termux'ta çalışan bir Telegram botu — konuşmaları hatırlıyor, komutları risk seviyesine göre filtreler, web araması yapıyor ve her mesajı Vault'a kaydediyor.

---

## 2. ÇALIŞAN SERVİSLER (şu an aktif)

| Servis | Nasıl çalışıyor | Ne yapıyor |
|--------|----------------|------------|
| `main.py` | Termux `screen` veya `nohup` | Telegram botu — tüm mesajları karşılar |
| `agents/summarizer` | `main.py` içinde `asyncio.create_task` | Arka planda özet çıkarıcı |
| `api.py` | `nohup uvicorn` port 8000 | FastAPI HTTP katmanı — HUD + Chat endpoint'leri |
| Tailscale | Android servis | Telefona uzaktan erişim (kapalıyken `localhost:8000` ulaşılamaz) |

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
    +
supabase_sync.sync_entry() → Supabase bulut backup (fire-and-forget)
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
├── api.py                  ← FastAPI HTTP katmanı (port 8000) ✅ aktif
├── gatekeeper.py           ← risk sınıflandırma + sandbox + audit
├── supabase_sync.py        ← Supabase bulut sync (fire-and-forget) ✅ yeni
├── theia_hud.html          ← eski HUD arayüzü (pasif)
├── voice.py                ← yerel sesli asistan — DONDURULDU, ileriki faz
├── requirements.txt
├── .env                    ← TOKEN, CHAT_ID, USER_ID, ANTHROPIC_API_KEY
├── CLAUDE.md               ← Claude Code kuralları
├── THEIA_HARITA.md         ← bu dosya
│
├── _archive/               ← pasif / eski dosyalar
│   ├── README.md           ← arşiv notları
│   ├── theia_api.py        ← api.py'nin eski paraleli (arşivlendi)
│   ├── permissions.py      ← tek kullanıcılı sistemde erken soyutlama
│   └── migration_script.py ← DB stabil olduktan sonra arşivlendi
│
├── core/
│   ├── config.py           ← ayarlar, claude istemci, SYSTEM prompt
│   ├── db.py               ← SQLite bağlantısı, tüm tablo şemaları
│   ├── pending.py          ← niyet takip tablosu
│   └── shared.py           ← ortak regex tanımları (_MEM_SAVE_RE vb.) ✅ yeni
│
├── handlers/
│   ├── message.py          ← genel mesaj işleyici (ana akış burada)
│   ├── shell.py            ← /cmd komutu + Gatekeeper entegrasyonu
│   ├── memory.py           ← /memory /hafiza /kaydet /unut komutları
│   ├── schedule.py         ← /liste /ekle /tamam görev yönetimi (502 satır — izleniyor)
│   └── start.py            ← /start komutu
│
├── agents/
│   ├── summarizer.py       ← arka plan özet ajanı (Haiku)
│   ├── memory_agent.py     ← vault bağlam çekici
│   └── web_agent.py        ← web arama (🌍 veya & prefix ile tetiklenir)
│
├── memory/
│   ├── vault_api.py        ← entries/topics CRUD + Supabase sync hook ✅ güncellendi
│   └── memory_manager.py   ← eski hafıza sistemi (pasif, silinmedi)
│
└── static/
    ├── deepwebtheia.html   ← aktif HUD arayüzü ✅ v0.9
    ├── index.html          ← eski HUD (pasif)
    └── theia_hud_v2.html   ← orta versiyon (pasif)

~/theia/                    ← veri dizini (git dışı)
├── theia.db                ← SQLite veritabanı (225 entry + tüm tablolar)
├── .env                    ← gizli anahtarlar (SUPABASE_URL + SUPABASE_ANON_KEY dahil)
└── gatekeeper_log.json     ← audit log
```

---

## 8. WEB ARAYÜZÜ (deepwebtheia.html)

**Erişim:** `http://localhost:8000/static/deepwebtheia.html`

**Başlatma (3 adım):**
```bash
1. Termux aç
2. cd ~/theia-vault && python3 api.py
3. Tarayıcıdan localhost:8000/static/deepwebtheia.html
```

### Modüller ve durumları:

| Modül | Durum | Backend |
|-------|-------|---------|
| THEIA TALK | ✅ Çalışır | Anthropic API direkt (kullanıcı key'i, localStorage) / localhost:8000 fallback |
| WOLFSTREET | 🔶 Mock data | Gmail entegrasyonu bekliyor |
| RITUALS | ✅ Endpoint hazır | `GET /api/rituals` |
| GATEKEEPER | ✅ Endpoint hazır | `GET /api/gatekeeper` + `GET /api/gatekeeper/log` |
| VAULT | ✅ Endpoint hazır | `GET /api/vault/entries` + `/vault/topics` + `/vault/stats` |
| PIGEON | ⏳ UI beklemede | Telegram bot var, onay kuyruğu var |
| AUDIT LOG | ✅ Endpoint hazır | `GET /api/audit` |
| INTENT | ⏳ Skeleton | NL engine entegrasyonu bekliyor |

### Talk modülü davranışı:
- API key varsa → direkt `api.anthropic.com` (claude-sonnet-4-6)
- API key yoksa → `localhost:8000/api/chat` (Telegram botu üzerinden)
- Konuşmalar localStorage'a kaydediliyor — sayfa kapansa da kaybolmuyor
- Max 40 konuşma, konuşma başına son 80 mesaj saklanır

### Notlar:
- CHAT modülü kaldırıldı (Talk ile duplicate idi)
- API key tarayıcıda localStorage'da, koda gömülmez, GitHub'a gitmez
- Modüller sürükle-bırak ile yeniden sıralanabilir

---

## 9. API ENDPOINTLERİ (api.py — port 8000)

| Endpoint | Metod | Ne döndürür |
|----------|-------|-------------|
| `/api/health` | GET | `{"status": "ok"}` |
| `/api/chat` | POST | Claude yanıtı (+ opsiyonel TTS) |
| `/api/status` | GET | uptime, total_commands, memory_entries |
| `/api/gatekeeper` | GET | risk_distribution, recent_commands, hourly_activity |
| `/api/gatekeeper/log` | GET | ham gatekeeper log (n parametreli) |
| `/api/memory` | GET | total_users, total_entries |
| `/api/activity` | GET | 7 günlük aktivite |
| `/api/stream` | GET | son 6 konuşma |
| `/api/vault/entries` | GET | vault girdileri (limit, topic, q) |
| `/api/vault/topics` | GET | tüm konular |
| `/api/vault/stats` | GET | vault istatistikleri |
| `/api/audit` | GET | audit log (n parametreli) |
| `/api/rituals` | GET | ritüeller (status filtreli) |
| `/api/conversations/stats` | GET | konuşma istatistikleri |
| `/reminders` | GET | zamanı gelmiş hatırlatıcılar |
| `/items` | GET/POST | görev listesi |
| `/pendings` | GET | çözümlenmemiş niyetler |
| `/static/*` | GET | statik dosyalar (deepwebtheia.html dahil) |

---

## 10. BAĞLANTILAR VE KİMDEN KİME

```
[Sen]
  │
  ├── Telegram ──────────────► main.py (Termux/Android)
  │                                │
  │                                ├── Anthropic API (claude-sonnet-4-6)
  │                                ├── theia.db (SQLite)
  │                                └── gatekeeper_log.json
  │
  ├── Tarayıcı ──────────────► localhost:8000/static/deepwebtheia.html
  │                                │
  │                                ├── TALK → api.anthropic.com/v1/messages
  │                                │         (direkt, senin key'in — localStorage)
  │                                │
  │                                └── TALK fallback → localhost:8000/api/chat
  │
  └── Tailscale ─────────────► Telefonun Tailscale IP'si (100.x.x.x)
                               Dışarıdan erişim için gerekli
                               Aynı ağdayken gerekmez
```

---

## 11. STACK

| Katman | Teknoloji | Not |
|--------|-----------|-----|
| Dil | Python 3.13 | |
| Telegram | python-telegram-bot 22.7 | |
| HTTP API | FastAPI + uvicorn | port 8000 ✅ aktif |
| Ana model | claude-sonnet-4-6 | Telegram konuşma + Talk modülü |
| Hafıza modeli | claude-haiku-4-5-20251001 | summarizer + api.py |
| Veritabanı | SQLite | ~/theia/theia.db |
| Ses (local) | edge-tts | TTS aktif; Vosk STT + Piper TTS donduruldu |
| Ağ tüneli | Tailscale | Android, dışarıdan erişim için |

---

## 12. YAPILACAKLAR SIRALI

| # | İş | Durum |
|---|-----|-------|
| 1 | `api.py` başlat (port 8000) | ✅ Tamamlandı |
| 2 | HTML'de port 8585 → 8000 | ✅ Tamamlandı |
| 3 | HUD endpoint'leri ekle | ✅ Tamamlandı |
| 4 | CHAT modülünü kaldır (Talk ile birleştir) | ✅ Tamamlandı |
| 5 | Talk localStorage — konuşma kalıcılığı | ✅ Tamamlandı |
| 6 | deepwebtheia.html → static/ klasörüne taşı | ✅ Tamamlandı |
| 7 | Pasif dosyalar → _archive/ (theia_api.py, permissions.py, migration_script.py) | ✅ Tamamlandı |
| 8 | core/shared.py — ortak regex tanımları | ✅ Tamamlandı |
| 9 | api.py duplicate import temizliği | ✅ Tamamlandı |
| 10 | Supabase bulut backup — supabase_sync.py | ✅ Tamamlandı |
| 11 | api.py `_build_system` → message.py versiyonuyla eşitle | ⏳ Beklemede (B aşaması) |
| 12 | Pigeon workspace UI | ⏳ Beklemede |
| 13 | schedule.py bölünmesi (502 satır → crud + jobs) | ⏳ Büyüyünce |
| 14 | Wolfstreet → Gmail bağlantısı | ⏳ En son, en karmaşık |
| 15 | README güncelle | ⏳ Hepsi bittikten sonra |

---

## 13. HIZLI BAŞLATMA

### Termux (Android) — güncel:
```bash
cd ~/theia-vault
python3 api.py
# Tarayıcıdan: localhost:8000/static/deepwebtheia.html
```

### Termux — Telegram botu da çalıştırmak için:
```bash
cd ~/theia-vault
nohup uvicorn api:app --host 0.0.0.0 --port 8000 > ~/theia/api.log 2>&1 &
python3 main.py
```

### Debian (bilgisayar):
```bash
cd ~/theia-vault
uvicorn api:app --host 0.0.0.0 --port 8000
```

### Tailscale (dışarıdan erişim):
```bash
tailscale up
# Telefon IP: tailscale ip
```

---

## 14. ÖNEMLİ KARARLAR / NOTLAR

- **Groq kaldırıldı** — tamamen Anthropic API
- **Tek kullanıcı** — `USER_ID` ile kimlik doğrulama
- **Web araması** — mesajın başına 🌍 veya & koy
- **Vault kayıt** — her konuşma otomatik kaydediliyor, `/kaydet` gerekmez
- **Supabase bulut backup** — `supabase_sync.py` vault_api'ye entegre, her write/delete/merge otomatik sync. 225 entry migrate edildi. Telefon veya laptop gitse veriler kaybolmuyor.
- **Supabase proje** — `theiafinal` (AWS ap-south-1), `entries` + `topics` tabloları, RLS kapalı
- **Talk modülü** — API key localStorage'da, koda gömülmez, GitHub'a gitmez
- **Talk kalıcılık** — konuşmalar localStorage'a yazılıyor (max 40 konuşma / 80 mesaj)
- **CHAT modülü kaldırıldı** — Talk modülü her iki modu (direkt API + localhost) kapsıyor
- **Ana arayüz** — `static/deepwebtheia.html` (port 8000 üzerinden)
- **theia_hud.html / index.html / theia_hud_v2.html** — repo'da duruyor, pasif, temizlenecek
- **voice.py** — DONDURULDU, ileriki faz için beklemede
- **theia_api.py** — _archive/ altına taşındı (Mayıs 2026)
- **core/shared.py** — message.py ve api.py ortak regex tanımları buradan import eder
- **api.py `_build_system`** — message.py versiyonundan farklı (user_memory, tarih eksik) — B aşaması bekliyor
- **schedule.py** — 502 satır, izleniyor; büyüyünce crud + jobs olarak bölünecek
- **.env konumu** — `~/theia/.env` (git dışı), SUPABASE_URL + SUPABASE_ANON_KEY burada
