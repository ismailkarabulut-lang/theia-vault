# THEIA SİSTEM HARİTASI
> Son güncelleme: Nisan 2026 | Versiyon: 0.5-aktif

---

## 1. SİSTEM NE YAPIYOR (tek cümle)

Termux'ta çalışan bir Telegram botu — konuşmaları hatırlıyor, komutları risk seviyesine göre filtreler, web araması yapıyor ve her mesajı Vault'a kaydediyor.

---

## 2. ÇALIŞAN SERVİSLER (şu an aktif)

| Servis | Nasıl çalışıyor | Ne yapıyor |
|--------|----------------|------------|
| `main.py` | Termux `screen` veya `nohup` | Telegram botu — tüm mesajları karşılar |
| `agents/summarizer` | `main.py` içinde `asyncio.create_task` | Arka planda özet çıkarıcı |
| Tailscale | Android servis | Telefona uzaktan erişim (kapalıyken devre dışı) |

**Henüz çalışmayan:**
- `api.py` (bugün yazıldı, kurulmadı)

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
    ├─► "🌍" prefix   → web_agent.search()
    ├─► /cmd komutu   → handlers/shell.py
    │
    ▼
Paralel çalışır:
    ├─► memory_agent.get_context()   → Vault'tan ilgili geçmiş
    └─► web_agent.search()           → Brave/Tavily arama (prefix varsa)
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

## 4. KOMut ONAY AKIŞI (Gatekeeper)

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

**Log nerede:** `~/theia/gatekeeper_log.json`

---

## 5. VERİTABANI (~/theia/theia.db)

| Tablo | Ne tutuyor |
|-------|-----------|
| `conversations` | Tüm Telegram mesajları (role, content, timestamp) |
| `entries` | Vault hafıza girdileri — her mesaj buraya da yazılıyor |
| `entries_fts` | Full-text arama indeksi (entries'e bağlı) |
| `topics` | Girdilerin toplandığı konular |
| `topic_entries` | Konu ↔ girdi ilişkisi |
| `audit` | Sistem aksiyonları |
| `permissions` | Kim ne yapabilir (human, haiku_summarizer, web_agent...) |
| `items` | Görev/hatırlatıcılar |
| `checks` | Görev takip kayıtları |
| `queue` | Arka plan iş kuyruğu |

**DB yolu:** `Path.home() / "theia" / "theia.db"`

---

## 6. HAFIZA SİSTEMİ

### Nasıl çalışıyor:
1. Her mesaj `conversations` tablosuna kaydedilir
2. Her mesaj `vault_api.write_entry()` ile `entries` tablosuna da kaydedilir
3. `memory_agent.get_context()` — yeni mesaj geldiğinde Vault'ta ilgili geçmiş aranır, system prompt'a eklenir
4. `agents/summarizer` — arka planda özet çıkarır, `topics` tablosunu günceller

### Neden Telegram sohbetinde her şeyi hatırlıyor:
`get_history(user_id, limit=20)` — son 20 mesajı her seferinde Claude'a gönderiyor. Hafıza illüzyonu değil, gerçek geçmiş.

### Zayıf nokta:
Bot restart olursa `conversations` tablosu korunur ama aktif sohbet bağlamı ilk 20 mesajla sınırlı.

---

## 7. DOSYA YAPISI

```
~/theia-vault/              ← repo kök
├── main.py                 ← bot giriş noktası
├── gatekeeper.py           ← risk sınıflandırma + sandbox + audit
├── api.py                  ← (YENİ) web arayüzü için Flask API
├── requirements.txt
├── .env                    ← TOKEN, CHAT_ID, USER_ID, ANTHROPIC_API_KEY
│
├── core/
│   ├── config.py           ← ayarlar, claude istemci, SYSTEM prompt
│   ├── db.py               ← SQLite bağlantısı, tablo şemaları
│   └── pending.py          ← niyet takip tablosu
│
├── handlers/
│   ├── message.py          ← genel mesaj işleyici (ana akış burada)
│   ├── shell.py            ← /cmd komutu + Gatekeeper entegrasyonu
│   ├── memory.py           ← /memory /hafiza /kaydet /unut komutları
│   └── schedule.py         ← /liste /ekle /tamam görev yönetimi
│
├── agents/
│   ├── summarizer.py       ← arka plan özet ajanı
│   ├── memory_agent.py     ← vault bağlam çekici
│   └── web_agent.py        ← web arama (🌍 prefix ile tetiklenir)
│
└── memory/
    ├── vault_api.py        ← entries/topics CRUD
    └── memory_manager.py   ← (eski sistem, vault_api'ye geçildi)

~/theia/                    ← veri dizini (git dışı)
├── theia.db                ← SQLite veritabanı
├── .env                    ← gizli anahtarlar
└── gatekeeper_log.json     ← audit log (json array)
```

---

## 8. WEB ARAYÜZÜ (theia_vault_5.html)

### Modüller ve durumları:

| Modül | Renk | Durum | Backend |
|-------|------|-------|---------|
| CHAT | Mor | ✅ Çalışır | `POST /api/chat` → `localhost:8585` |
| THEIA TALK | Mor | ✅ Çalışır | Anthropic API direkt (kullanıcı key'i) |
| WOLFSTREET | Gümüş/Amber | 🔶 Mock data | Gmail entegrasyonu bekliyor |
| RITUALS | Turuncu | ⏳ Beklemede | `items` tablosu hazır, UI yok |
| GATEKEEPER | Kırmızı | ⏳ Beklemede | `gatekeeper_log.json` var, endpoint yok |
| VAULT | Mor | ⏳ Beklemede | `entries`/`topics` tablosu hazır, `api.py` kurulmadı |
| PIGEON | Mavi | ⏳ Beklemede | Telegram bot var, onay kuyruğu var |
| AUDIT LOG | Yeşil | ⏳ Beklemede | `audit` tablosu hazır, endpoint yok |

### Nasıl açılıyor:
Tarayıcıda direkt HTML dosyası olarak. Sunucu gerektirmiyor.

### Tailscale bağlantısı:
Telefon dışarıdayken `localhost:8585`'e ulaşmak için Tailscale açık olmalı. Kapalıyken Chat modülü çalışmaz.

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
  │                                ├── CHAT → localhost:8585/api/chat
  │                                │           (Tailscale üzerinden telefona)
  │                                │
  │                                └── TALK → api.anthropic.com/v1/messages
  │                                           (direkt, senin key'in)
  │
  └── Tailscale ─────────────► Telefonun IP'si (100.x.x.x)
                               localhost:8585 buradan erişilir
```

---

## 10. KURULU OLMAYAN / EKSİK

| Ne | Neden önemli | Ne zaman |
|----|-------------|----------|
| `api.py` kurulumu | Chat + Vault çalışması için şart | Akşam bilgisayarda |
| `flask flask-cors` pip kurulumu | api.py bağımlılığı | Akşam |
| localStorage (HTML) | Sayfa yenilenince konuşmalar gitmesin | Bir sonraki HTML versiyonu |
| Gatekeeper workspace UI | Risk log görselleştirme | Sıradaki modül |
| Vault workspace UI | entries/topics gösterimi | api.py sonrası |
| Rituals workspace UI | items tablosu görselleştirme | Vault'tan sonra |

---

## 11. GİDECEĞİMİZ YER

```
Şu an:     Telegram botu (çalışıyor) + HTML arayüz (kısmen)
Hedef:     Arayüz = Theia'nın gerçek zamanlı sinir sistemi

Adımlar:
1. api.py kur → Chat çalışır, Vault okunabilir
2. Gatekeeper workspace → risk log canlı görünür
3. Vault workspace → hafıza kartları, topic graph
4. Rituals workspace → streak takibi
5. Pigeon workspace → onay kuyruğu görselleştirme
6. Wolfstreet → Gmail bağlantısı (en son, en karmaşık)
```

---

## 12. HIZLI BAŞLATMA (Termux)

```bash
# Theia bot
cd ~/theia-vault
screen -S theia
python main.py
# Ctrl+A, D

# API servisi (kurulduktan sonra)
screen -S theia-api
python api.py
# Ctrl+A, D

# Servisleri kontrol et
screen -ls

# Tailscale
tailscale up
```

---

## 13. NOTLAR / ÖNEMLİ KARARLAR

- **Groq kaldırıldı** — tamamen Anthropic API'ye geçildi
- **Tek kullanıcı** — `USER_ID` ile kimlik doğrulama, başkası erişemez
- **Web araması** — mesajın başına 🌍 veya & koy, otomatik tetiklenir
- **Vault kayıt** — her konuşma otomatik kaydediliyor, `/kaydet` gerekmez
- **Gatekeeper log** — `~/theia/gatekeeper_log.json` JSON array formatında (ilerleyen versiyonda JSONL'e geçilecek — `AuditLog` sınıfı JSONL yazmaya hazır ama eski format korunuyor)
- **HTML arayüz** — sunucu gerektirmez, tarayıcıda direkt açılır
- **Talk modülü** — key localStorage'da saklanır, koda gömülmez, GitHub'a gitmez

