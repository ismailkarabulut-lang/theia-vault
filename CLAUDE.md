# CLAUDE.md
Bu dosya Claude Code'un bu repoda çalışırken uyması gereken kurallardır.

## Proje
**Theia** — Kaptan İsmail Karabulut'un kişisel AI asistan sistemi.
Dil: Türkçe.

## Gerçek Dosya Yapısı
- `main.py` — Telegram bot giriş noktası
- `api.py` — FastAPI HTTP katmanı (/chat, /health)
- `gatekeeper.py` — Komut onay ve risk sınıflandırma sistemi
- `voice.py` — Yerel sesli asistan (Vosk STT + Piper TTS, sadece local)
- `core/config.py` — Ayarlar, paylaşılan istemciler
- `core/db.py` — SQLite işlemleri (tüm tablo şemaları burada)
- `core/pending.py` — Bekleyen niyetler
- `handlers/message.py` — Telegram mesaj işleyici, Claude entegrasyonu
- `handlers/schedule.py` — Görev/rutin/hatırlatma yönetimi, minute_job cron
- `handlers/shell.py` — /cmd komutu, gatekeeper entegrasyonu
- `handlers/memory.py` — Hafıza komutları
- `handlers/start.py` — /start komutu
- `agents/summarizer.py` — Arka plan özet ajanı (Haiku, asyncio.create_task ile çalışır)
- `agents/memory_agent.py` — Vault bağlam çekici (get_context, her mesajda çağrılır)
- `agents/web_agent.py` — Web arama ajanı (🌍 veya & prefix ile tetiklenir)
- `memory/vault_api.py` — **AKTİF hafıza sistemi.** entries/topics CRUD işlemleri.
  Vault'a yazmak için DAIMA bunu kullan.
- `memory/memory_manager.py` — **PASİF, kullanılmıyor.** memory/users/{user_id}.md
  dosyalarına yazıyordu. Dokunma, silme, yeni kod buraya yazma.

## Stack
- Python 3.13
- python-telegram-bot 22.7 (Telegram bot için)
- FastAPI + uvicorn (HTTP API için)
- Anthropic Claude API (claude-sonnet-4-6 ana model, claude-haiku-4-5-20251001 memory için)
- SQLite (~/theia/theia.db)
- edge-tts (TTS için, sadece api.py)
- vosk + PyAudio (sadece voice.py, yerel kullanım, Render'a deploy edilmez)

## Veritabanı Tabloları
- `conversations` — sohbet geçmişi (user_id, role, content, timestamp)
- `items` — görev/rutin/hatırlatma (type, content, scheduled_time, check_after, status, recurrence)
- `checks` — kontrol bildirimleri (item_id, check_at, status: pending/sent)
- `pending_actions` — kullanıcı niyetleri (user_id, text, created_at, resolved_at)
- `entries` — Vault hafıza girdileri (her mesaj otomatik kaydedilir)
- `entries_fts` — Full-text arama indeksi (entries'e bağlı)
- `topics` — girdilerin gruplandığı konular
- `topic_entries` — konu ↔ girdi ilişkisi
- `audit` — sistem aksiyonları
- `permissions` — ajan yetki tanımları (human, haiku_summarizer, web_agent...)
- `queue` — arka plan iş kuyruğu

## Ortam Değişkenleri (.env)
- TELEGRAM_TOKEN
- CHAT_ID
- USER_ID
- ANTHROPIC_API_KEY
- GITHUB_TOKEN (opsiyonel, vault push için)

## Çalıştırma
- Telegram bot: `python main.py`
- API: `uvicorn api:app --host 0.0.0.0 --port 8000`
- Sesli asistan: `python voice.py` (sadece local, Termux/desktop)

## Geliştirme Kuralları
- Her değişiklikten önce ne yapacağını söyle, onay bekle
- Dosyaları silme veya taşıma — sadece düzenle veya oluştur
- git push, deploy, dış API çağrısı öncesi MUTLAKA dur ve sor
- Mevcut Türkçe kullanıcı mesajlarını koru
- theia.db'ye şema değişikliği öncesi sor
- Gereksiz bağımlılık ekleme
- Tek dosyayı düzenle, tüm projeyi yeniden yazma
- Vault'a yazmak için vault_api kullan, eski memory klasörüne yazma

