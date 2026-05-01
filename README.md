# Theia Vault

Kişisel kullanım için tasarlanmış, Claude tabanlı Telegram asistan botu ve web arayüzü. Sohbet etmekle kalmaz — sizi tanır, hatırlar ve zamanla daha iyi hizmet verir.

---

## Özellikler

**Hafıza Sistemi (Vault)**
Her konuşma otomatik olarak Vault'a kaydedilir. Full-text arama ve konu kümeleme ile geçmiş bağlam her yanıtta hazır bekler. Manuel `/kaydet` gerektirmez.

**Web Taraması**
Mesajın başına `🌍` veya `&` ekleyin — Theia güncel bilgi için internette arama yapar.

**Görev & Hatırlatıcı Takibi**
Görev listesi, rutin takibi ve hatırlatıcı yönetimi Telegram üzerinden `/liste`, `/ekle`, `/tamam` komutlarıyla çalışır.

**Güvenli Komut Çalıştırma (Gatekeeper)**
`/cmd` ile sistem komutu gönderirsiniz. Gatekeeper her komutu risk seviyesine göre sınıflandırır: düşük risk otomatik çalışır, yüksek risk için onay ister, kritik komutları tamamen engeller.

**Web Arayüzü (HUD)**
`localhost:8000/static/deepwebtheia.html` adresinden erişilen görsel kontrol paneli. Vault, Gatekeeper, Rituals, Audit ve Talk modüllerini içerir. Talk modülü üzerinden doğrudan Claude ile sohbet edilebilir; konuşmalar localStorage'da kalıcı olarak saklanır.

---

## Kurulum

### Gereksinimler

- Python 3.10+
- Telegram Bot Token ([BotFather](https://t.me/botfather))
- Anthropic API anahtarı

### Adımlar

```bash
git clone https://github.com/ismailkarabulut-lang/theia-vault
cd theia-vault
pip install -r requirements.txt
```

`.env` dosyası oluştur (`~/theia/.env` konumuna koy, git dışında kalır):

```env
TELEGRAM_BOT_TOKEN=your_token_here
ANTHROPIC_API_KEY=your_key_here
CHAT_ID=your_chat_id
USER_ID=your_user_id
```

Telegram botunu başlat:

```bash
python main.py
```

Web arayüzünü başlat (ayrı terminal):

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Tarayıcıdan aç:

```
http://localhost:8000/static/deepwebtheia.html
```

### Termux (Android) Kurulumu

```bash
pkg update && pkg upgrade
pkg install python git
git clone https://github.com/ismailkarabulut-lang/theia-vault
cd theia-vault
pip install -r requirements.txt
```

Arka planda çalıştır:

```bash
termux-wake-lock
nohup uvicorn api:app --host 0.0.0.0 --port 8000 > ~/theia/api.log 2>&1 &
python main.py
```

> Pil optimizasyonunu kapat: Ayarlar → Uygulama → Termux → Pil → Kısıtlama yok

---

## Telegram Komutları

| Komut | İşlev |
|-------|-------|
| `/memory` veya `/hafiza` | Vault'taki kayıtları göster |
| `/kaydet` veya `/remember` | O anki bilgiyi Vault'a yaz |
| `/unut` veya `/forget` | Belirtilen kaydı sil |
| `bunu hatırla: ...` | Doğal dille Vault kaydı |
| `/liste` | Görev listesini göster |
| `/ekle <görev>` | Yeni görev ekle |
| `/tamam <id>` | Görevi tamamlandı işaretle |
| `/cmd <komut>` | Sistem komutu çalıştır (Gatekeeper üzerinden) |
| `🌍 <soru>` veya `& <soru>` | Web aramalı yanıt al |

---

## Gatekeeper Risk Seviyeleri

| Seviye | Davranış | Örnekler |
|--------|----------|----------|
| LOW | Otomatik çalıştır | `ls`, `cat`, `ps`, `grep`, `echo` |
| MEDIUM | 1 onay butonu | `apt install`, `pip`, `mv`, `chmod`, `git push` |
| HIGH | 2 kez onay | `rm -rf`, `DROP TABLE`, `shred` |
| CRITICAL | Tamamen engelle | `rm -rf /`, `mkfs`, fork bomb |

---

## Proje Yapısı

```
theia-vault/
├── main.py                 # Bot giriş noktası
├── api.py                  # FastAPI HTTP katmanı (port 8000)
├── gatekeeper.py           # Risk sınıflandırma + komut sandbox
├── static/
│   └── deepwebtheia.html   # Web arayüzü (HUD)
├── core/
│   ├── config.py           # Ayarlar, Claude istemci, system prompt
│   ├── db.py               # SQLite bağlantısı ve tablo şemaları
│   └── pending.py          # Niyet takibi
├── handlers/
│   ├── message.py          # Ana mesaj akışı
│   ├── schedule.py         # Görev ve hatırlatıcı yönetimi
│   ├── shell.py            # /cmd komutu
│   └── memory.py           # Hafıza komutları
├── agents/
│   ├── memory_agent.py     # Vault bağlam çekici
│   ├── summarizer.py       # Arka plan özetleme (Haiku)
│   └── web_agent.py        # Web arama ajanı
├── memory/
│   └── vault_api.py        # Vault CRUD operasyonları
├── .env                    # API anahtarları — git dışı
└── requirements.txt
```

Veriler `~/theia/` altında tutulur (`theia.db`, `gatekeeper_log.json`) ve git dışında kalır.

---

## Notlar

- **Tek kullanıcı** — `USER_ID` ve `CHAT_ID` ile kimlik doğrulama, yalnızca tanımlı kullanıcı erişebilir
- **Hafıza** — her mesaj otomatik Vault'a yazılır, `memory_agent` ilgili geçmişi her yanıtta sistem prompt'a ekler
- **Model** — ana konuşma `claude-sonnet-4-6`, özetleme `claude-haiku-4-5` (maliyet optimize)
- **HUD kalıcılığı** — Talk modülü konuşmaları localStorage'a yazar, sayfa kapansa da kaybolmaz (max 40 konuşma)
- **Tailscale** — dışarıdan erişim için gerekli, aynı ağdayken gerekmez

---

*Kişisel kullanım için geliştirilmiştir.*
