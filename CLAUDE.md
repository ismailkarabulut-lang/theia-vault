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
- `core/db.py` — SQLite işlemleri (items, checks, conversations, pending_actions tabloları)
- `core/pending.py` — Bekleyen niyetler
- `handlers/message.py` — Telegram mesaj işleyici, Claude entegrasyonu
- `handlers/schedule.py` — Görev/rutin/hatırlatma yönetimi, minute_job cron
- `handlers/shell.py` — /cmd komutu, gatekeeper entegrasyonu
- `handlers/memory.py` — Hafıza komutları
- `handlers/start.py` — /start komutu
- `memory/memory_manager.py` — Kullanıcı başına kalıcı hafıza (memory/users/{user_id}.md)

## Stack
- Python 3.13
- python-telegram-bot 22.7 (Telegram bot için)
- FastAPI + uvicorn (HTTP API için)
- Anthropic Claude API (claude-sonnet-4-6 ana model, claude-haiku-4-5-20251001 memory için)
- SQLite (~/theia/theia.db)
- edge-tts (TTS için, sadece api.py)
- vosk + PyAudio (sadece voice.py, yerel kullanım, Render'a deploy edilmez)

## Veritabanı Tabloları
- `items` — görev/rutin/hatırlatma (type, content, scheduled_time, check_after, status, recurrence)
- `checks` — kontrol bildirimleri (item_id, check_at, status: pending/sent)
- `conversations` — sohbet geçmişi (user_id, role, content, timestamp)
- `pending_actions` — kullanıcı niyetleri (user_id, text, created_at, resolved_at)

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
